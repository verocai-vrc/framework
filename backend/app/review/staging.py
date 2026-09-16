"""Staging area: collector findings become ``:Candidate`` nodes that never carry the
``:Entity`` label, so they are invisible to graph queries until an analyst approves them.
Approval merges the candidate into the live graph with ``reviewed = true``.
"""

from __future__ import annotations

import json
from typing import Any

from neo4j.graph import Node

from app.collectors.base import Finding
from app.db.driver import Neo4jClient
from app.db.schema import CANDIDATE_LABEL, ENTITY_LABEL, NodeLabel, is_allowed_edge
from app.errors import Conflict, NotFound
from app.graph import crud
from app.models.candidates import CandidateOut, CandidateUpdate
from app.models.common import Provenance, new_id, utcnow_iso
from app.models.edges import EdgeCreate, EdgeOut
from app.models.nodes import NodeCreate, NodeOut, NodeUpdate, validate_attrs

# Attribute that identifies a node of each label when checking "already in the graph".
IDENTITY_ATTR: dict[NodeLabel, str] = {
    NodeLabel.ORGANIZACAO: "name",
    NodeLabel.DOMINIO: "name",
    NodeLabel.ENDERECO_IP: "address",
    NodeLabel.SERVICO: "port",
    NodeLabel.SOFTWARE: "product",
    NodeLabel.DISPOSITIVO_INDUSTRIAL: "model",
    NodeLabel.CVE: "cve_id",
    NodeLabel.FUNCIONARIO: "name",
    NodeLabel.CREDENCIAL_VAZADA: "email",
    NodeLabel.INSTALACAO_FISICA: "name",
    NodeLabel.FORNECEDOR: "name",
}


def _to_out(c: Node) -> CandidateOut:
    p = dict(c)
    payload = json.loads(p.get("payload_json") or "{}")
    return CandidateOut(
        id=p["id"],
        project_id=p["project_id"],
        collector=p["collector"],
        source_family=p.get("source_family", ""),
        seed=p.get("seed", ""),
        kind=p.get("kind", "node"),
        status=p.get("status", "pending"),
        label=NodeLabel(p["label"]) if p.get("label") else None,
        title=p.get("title", ""),
        attrs=payload.get("attrs", {}),
        description=payload.get("description", ""),
        notes=payload.get("notes", ""),
        metadata=payload.get("metadata", {}),
        layer=payload.get("layer"),
        target_id=payload.get("target_id"),
        edges=payload.get("edges", []),
        dedupe_key=p.get("dedupe_key", ""),
        evidence=p.get("evidence", ""),
        raw=payload.get("raw", {}),
        source=p.get("source", p["collector"]),
        collected_at=p.get("collected_at", ""),
        created_at=p.get("created_at", ""),
        decided_at=p.get("decided_at"),
        merged_node_id=p.get("merged_node_id"),
        warnings=json.loads(p.get("warnings_json") or "[]"),
    )


async def _in_graph(
    db: Neo4jClient, project_id: str, label: NodeLabel, attrs: dict[str, Any]
) -> bool:
    attr = IDENTITY_ATTR[label]
    value = attrs.get(attr)
    if value is None:
        return False
    rec = await db.run_one(
        f"MATCH (n:{ENTITY_LABEL}:{label.value} {{project_id: $pid}}) "
        "WHERE toLower(toString(n[$attr])) = toLower(toString($value)) RETURN n.id AS id",
        {"pid": project_id, "attr": attr, "value": value},
        readonly=True,
    )
    return rec is not None


async def stage(
    db: Neo4jClient,
    project_id: str,
    collector: str,
    source_family: str,
    seed: str,
    findings: list[Finding],
    collected_at: str,
) -> tuple[list[CandidateOut], int, int]:
    """Store findings as pending candidates. Returns (staged, skipped_pending, skipped_in_graph)."""
    existing = await db.run(
        f"MATCH (c:{CANDIDATE_LABEL} {{project_id: $pid}}) "
        "WHERE c.status IN ['pending', 'approved'] RETURN c.dedupe_key AS k, c.status AS s",
        {"pid": project_id},
        readonly=True,
    )
    pending_keys = {r["k"] for r in existing if r["s"] == "pending"}
    approved_keys = {r["k"] for r in existing if r["s"] == "approved"}
    staged: list[CandidateOut] = []
    skipped_pending = skipped_in_graph = 0
    for f in findings:
        if f.dedupe_key in pending_keys:
            skipped_pending += 1
            continue
        if f.dedupe_key in approved_keys or (
            f.kind == "node" and f.label and await _in_graph(db, project_id, f.label, f.attrs)
        ):
            skipped_in_graph += 1
            continue
        title = f.title
        if not title and f.label and f.kind == "node":
            try:
                title = validate_attrs(f.label, f.attrs).default_title()
            except Exception:  # keep the candidate; the analyst fixes it in review
                title = f.dedupe_key
        payload = f.model_dump(mode="json", exclude={"kind", "label", "dedupe_key", "evidence"})
        props = {
            "id": new_id(),
            "project_id": project_id,
            "collector": collector,
            "source_family": source_family,
            "seed": seed,
            "kind": f.kind,
            "status": "pending",
            "label": f.label.value if f.label else None,
            "title": title or f.dedupe_key,
            "dedupe_key": f.dedupe_key,
            "evidence": f.evidence,
            "payload_json": json.dumps(payload, ensure_ascii=False),
            "source": collector,
            "collected_at": collected_at,
            "created_at": utcnow_iso(),
        }
        props = {k: v for k, v in props.items() if v is not None}
        rec = await db.run_one(
            f"CREATE (c:{CANDIDATE_LABEL}) SET c = $props RETURN c", {"props": props}
        )
        assert rec is not None
        staged.append(_to_out(rec["c"]))
        pending_keys.add(f.dedupe_key)
    return staged, skipped_pending, skipped_in_graph


async def list_candidates(
    db: Neo4jClient, project_id: str, status: str | None = None
) -> list[CandidateOut]:
    where = "AND c.status = $status" if status else ""
    recs = await db.run(
        f"MATCH (c:{CANDIDATE_LABEL} {{project_id: $pid}}) WHERE true {where} "
        "RETURN c ORDER BY c.created_at DESC, c.title",
        {"pid": project_id, "status": status},
        readonly=True,
    )
    return [_to_out(r["c"]) for r in recs]


async def count_pending(db: Neo4jClient, project_id: str) -> int:
    rec = await db.run_one(
        f"MATCH (c:{CANDIDATE_LABEL} {{project_id: $pid, status: 'pending'}}) RETURN count(c) AS n",
        {"pid": project_id},
        readonly=True,
    )
    return int(rec["n"]) if rec else 0


async def get_candidate(db: Neo4jClient, candidate_id: str) -> CandidateOut:
    rec = await db.run_one(
        f"MATCH (c:{CANDIDATE_LABEL} {{id: $id}}) RETURN c", {"id": candidate_id}, readonly=True
    )
    if rec is None:
        raise NotFound("candidate not found", id=candidate_id)
    return _to_out(rec["c"])


async def update_candidate(
    db: Neo4jClient, candidate_id: str, data: CandidateUpdate
) -> CandidateOut:
    c = await get_candidate(db, candidate_id)
    if c.status != "pending":
        raise Conflict("only pending candidates can be edited", status=c.status)
    payload = {
        "attrs": data.attrs if data.attrs is not None else c.attrs,
        "description": data.description if data.description is not None else c.description,
        "notes": data.notes if data.notes is not None else c.notes,
        "metadata": data.metadata if data.metadata is not None else c.metadata,
        "layer": data.layer.value if data.layer is not None else c.layer,
        "target_id": c.target_id,
        "edges": [
            e.model_dump(mode="json") for e in (data.edges if data.edges is not None else c.edges)
        ],
        "raw": c.raw,
    }
    if c.kind == "node" and c.label:
        validate_attrs(c.label, payload["attrs"])  # surface validation errors now, not on approve
    props = {"payload_json": json.dumps(payload, ensure_ascii=False)}
    if data.title is not None:
        props["title"] = data.title.strip() or c.title
    rec = await db.run_one(
        f"MATCH (c:{CANDIDATE_LABEL} {{id: $id}}) SET c += $props RETURN c",
        {"id": candidate_id, "props": props},
    )
    assert rec is not None
    return _to_out(rec["c"])


async def _merge_edges(
    db: Neo4jClient, c: CandidateOut, anchor: NodeOut, provenance: Provenance
) -> tuple[list[EdgeOut], list[str]]:
    created: list[EdgeOut] = []
    warnings: list[str] = []
    for e in c.edges:
        try:
            other = await crud.get_node(db, e.other_id)
        except NotFound:
            warnings.append(f"edge {e.rel} skipped: node {e.other_id} no longer exists")
            continue
        src, dst = (anchor, other) if e.direction == "out" else (other, anchor)
        if not is_allowed_edge(src.label, e.rel, dst.label):
            warnings.append(f"edge {src.label} -[{e.rel}]-> {dst.label} skipped: not allowed")
            continue
        try:
            created.append(
                await crud.create_edge(
                    db,
                    c.project_id,
                    EdgeCreate(
                        source_id=src.id, target_id=dst.id, rel=e.rel, provenance=provenance
                    ),
                )
            )
        except Conflict:
            warnings.append(f"edge {e.rel} to {other.title} already existed")
    return created, warnings


async def approve(db: Neo4jClient, candidate_id: str) -> CandidateOut:
    """Merge-on-approve: copy the candidate into the live graph with ``reviewed = true``."""
    c = await get_candidate(db, candidate_id)
    if c.status != "pending":
        raise Conflict("candidate was already decided", status=c.status)
    provenance = Provenance(source=c.source, collected_at=c.collected_at, reviewed=True)
    warnings: list[str] = []

    if c.kind == "node":
        assert c.label is not None
        anchor = await crud.create_node(
            db,
            c.project_id,
            NodeCreate(
                label=c.label,
                attrs=c.attrs,
                title=c.title,
                description=c.description,
                notes=c.notes,
                metadata=c.metadata,
                layer=c.layer,
                provenance=provenance,
            ),
        )
    else:
        assert c.target_id is not None
        anchor = await crud.get_node(db, c.target_id)
        if c.kind == "node_update":
            attrs = {**anchor.attrs}
            for k, v in c.attrs.items():
                if attrs.get(k) in (None, "") and v not in (None, ""):
                    attrs[k] = v
            metadata = {**anchor.metadata, **c.metadata}
            notes = anchor.notes
            if c.notes:
                notes = f"{notes}\n\n{c.notes}".strip()
            anchor = await crud.update_node(
                db, anchor.id, NodeUpdate(attrs=attrs, metadata=metadata, notes=notes)
            )
    _, edge_warnings = await _merge_edges(db, c, anchor, provenance)
    warnings.extend(edge_warnings)

    rec = await db.run_one(
        f"MATCH (c:{CANDIDATE_LABEL} {{id: $id}}) "
        "SET c.status = 'approved', c.decided_at = $now, c.merged_node_id = $node, "
        "c.warnings_json = $w RETURN c",
        {"id": candidate_id, "now": utcnow_iso(), "node": anchor.id, "w": json.dumps(warnings)},
    )
    assert rec is not None
    return _to_out(rec["c"])


async def reject(db: Neo4jClient, candidate_id: str) -> CandidateOut:
    c = await get_candidate(db, candidate_id)
    if c.status != "pending":
        raise Conflict("candidate was already decided", status=c.status)
    rec = await db.run_one(
        f"MATCH (c:{CANDIDATE_LABEL} {{id: $id}}) "
        "SET c.status = 'rejected', c.decided_at = $now RETURN c",
        {"id": candidate_id, "now": utcnow_iso()},
    )
    assert rec is not None
    return _to_out(rec["c"])


async def purge(db: Neo4jClient, project_id: str, status: str) -> int:
    rec = await db.run_one(
        f"MATCH (c:{CANDIDATE_LABEL} {{project_id: $pid, status: $status}}) "
        "WITH c, count(c) AS n DETACH DELETE c RETURN count(*) AS deleted",
        {"pid": project_id, "status": status},
    )
    return int(rec["deleted"]) if rec else 0
