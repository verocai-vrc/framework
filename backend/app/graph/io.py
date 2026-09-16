"""Project import/export.

* ``osintree/1`` — the typed format: a lossless round trip of project, nodes and edges,
  including ids and provenance.
* Legacy — the reference tool's ``{meta, nodes, edges}`` export (accented ``tipo``/``rel``
  values, structural ``Esfera``/``Ferramentas`` nodes, per-node ``page`` with
  ``nome/descricao/observacoes/metadados``). Imported best-effort with warnings; unknown
  types become an axis-appropriate label the analyst can re-type later.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app import __version__
from app.db.driver import Neo4jClient
from app.db.schema import (
    ENTITY_LABEL,
    LABEL_SPECS,
    PROJECT_LABEL,
    NodeLabel,
    RelType,
    allowed_rel_types,
    is_allowed_edge,
)
from app.errors import ValidationFailed
from app.graph import crud, projects
from app.models.common import Impact, Provenance, new_id, utcnow_iso
from app.models.edges import EdgeCreate, EdgeOut
from app.models.nodes import NodeCreate, NodeOut, validate_attrs
from app.models.projects import ProjectCreate, ProjectOut

FORMAT = "osintree/1"
LEGACY_SOURCE = "legacy_import"


class ProjectExport(BaseModel):
    format: str = FORMAT
    app_version: str = __version__
    exported_at: str = Field(default_factory=utcnow_iso)
    project: ProjectOut
    nodes: list[NodeOut]
    edges: list[EdgeOut]


class ImportReport(BaseModel):
    project: ProjectOut
    format: str
    nodes_created: int
    edges_created: int
    ids_remapped: bool = False
    warnings: list[str] = Field(default_factory=list)


# --- export -----------------------------------------------------------------------------


async def export_project(db: Neo4jClient, project_id: str) -> ProjectExport:
    project = await projects.get_project(db, project_id)
    graph = await crud.get_graph(db, project_id)
    return ProjectExport(project=project, nodes=graph.nodes, edges=graph.edges)


# --- typed import -----------------------------------------------------------------------


def detect_format(payload: dict[str, Any]) -> str:
    if payload.get("format") == FORMAT:
        return FORMAT
    nodes = payload.get("nodes")
    if isinstance(nodes, list) and (not nodes or "tipo" in nodes[0] or "page" in nodes[0]):
        return "legacy"
    raise ValidationFailed("unrecognised import format")


async def _ids_in_use(db: Neo4jClient, ids: list[str]) -> bool:
    rec = await db.run_one(
        f"MATCH (n:{ENTITY_LABEL}) WHERE n.id IN $ids RETURN count(n) AS n",
        {"ids": ids},
        readonly=True,
    )
    return bool(rec and rec["n"])


async def import_typed(
    db: Neo4jClient, payload: dict[str, Any], name: str | None = None
) -> ImportReport:
    try:
        data = ProjectExport.model_validate(payload)
    except ValidationError as exc:
        raise ValidationFailed(f"invalid {FORMAT} file: {exc.errors()[0]['msg']}") from exc

    warnings: list[str] = []
    remap = await _ids_in_use(db, [n.id for n in data.nodes])
    id_map = {n.id: (new_id() if remap else n.id) for n in data.nodes}
    if remap:
        warnings.append("node ids already existed in the database; fresh ids were assigned")

    src = data.project
    project_id = new_id()
    now = utcnow_iso()
    props: dict[str, Any] = {
        "id": project_id,
        "name": name or src.name,
        "description": src.description,
        "created_at": now,
        "updated_at": now,
    }
    if src.org_name:
        props["org_name"] = src.org_name
    if src.seed_domain:
        props["seed_domain"] = src.seed_domain
    if src.root_node_id and src.root_node_id in id_map:
        props["root_node_id"] = id_map[src.root_node_id]
    await db.run(f"CREATE (p:{PROJECT_LABEL}) SET p = $props", {"props": props})

    nodes_created = 0
    for n in data.nodes:
        node_props = {
            **n.attrs,
            "id": id_map[n.id],
            "project_id": project_id,
            "label_display": n.label_display,
            "axis": n.axis.value,
            "title": n.title,
            "description": n.description,
            "notes": n.notes,
            "metadata_json": json.dumps(n.metadata, ensure_ascii=False),
            "source": n.source,
            "collected_at": n.collected_at,
            "reviewed": n.reviewed,
            "created_at": n.created_at or now,
            "updated_at": n.updated_at or now,
        }
        if n.layer:
            node_props["layer"] = n.layer.value
        await db.run(
            f"CREATE (x:{ENTITY_LABEL}:{n.label.value}) SET x = $props", {"props": node_props}
        )
        nodes_created += 1

    edges_created = 0
    for e in data.edges:
        if e.source_id not in id_map or e.target_id not in id_map:
            warnings.append(f"edge {e.rel} skipped: endpoint missing from the file")
            continue
        if not is_allowed_edge(e.source_label, e.rel, e.target_label):
            warnings.append(
                f"edge {e.source_label} -[{e.rel}]-> {e.target_label} skipped: not allowed"
            )
            continue
        edge_props: dict[str, Any] = {
            "id": new_id() if remap else e.id,
            "project_id": project_id,
            "notes": e.notes,
            "source": e.source,
            "collected_at": e.collected_at,
            "reviewed": e.reviewed,
            "created_at": e.created_at or now,
            "updated_at": e.updated_at or now,
        }
        if e.impact:
            edge_props["impact"] = e.impact.value
        if e.weight is not None:
            edge_props["weight"] = e.weight
        await db.run(
            f"MATCH (a:{ENTITY_LABEL} {{id: $sid}}), (b:{ENTITY_LABEL} {{id: $tid}}) "
            f"CREATE (a)-[r:{e.rel.value}]->(b) SET r = $props",
            {"sid": id_map[e.source_id], "tid": id_map[e.target_id], "props": edge_props},
        )
        edges_created += 1

    return ImportReport(
        project=await projects.get_project(db, project_id),
        format=FORMAT,
        nodes_created=nodes_created,
        edges_created=edges_created,
        ids_remapped=remap,
        warnings=warnings,
    )


# --- legacy import ----------------------------------------------------------------------


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _ascii(s).lower()).strip("_")


_LABEL_BY_NORM = {_norm(label.value): label for label in NodeLabel}
_LABEL_BY_NORM.update({_norm(spec.display_pt): label for label, spec in LABEL_SPECS.items()})
_LABEL_BY_NORM.update({_norm(spec.display_en): label for label, spec in LABEL_SPECS.items()})
STRUCTURAL_TIPOS = {"esfera", "ferramentas", "ferramenta"}
STRUCTURAL_RELS = {"agrupa", "contem"}
_REL_BY_NORM = {_norm(r.value): r for r in RelType}
_IMPACT_BY_NORM = {
    "critico": Impact.CRITICO,
    "alto": Impact.ALTO,
    "medio": Impact.MEDIO,
    "baixo": Impact.BAIXO,
}
_DEFAULT_LABEL_BY_EIXO = {
    "central": NodeLabel.ORGANIZACAO,
    "digital": NodeLabel.SOFTWARE,
    "humano": NodeLabel.FUNCIONARIO,
    "fisico": NodeLabel.INSTALACAO_FISICA,
    "ecossistema": NodeLabel.FORNECEDOR,
}
_ANCHOR_REL = {
    NodeLabel.DOMINIO: RelType.PERTENCE_A,
    NodeLabel.INSTALACAO_FISICA: RelType.PERTENCE_A,
    NodeLabel.FORNECEDOR: RelType.FORNECE_PARA,
    NodeLabel.FUNCIONARIO: RelType.TRABALHA_EM,
}


def _meta(md: dict[str, Any], *keys: str) -> str | None:
    """First metadados value whose normalised key matches one of ``keys``."""
    normalised = {_norm(k): v for k, v in md.items()}
    for key in keys:
        v = normalised.get(_norm(key))
        if v not in (None, ""):
            return str(v)
    return None


def _float(v: str | None) -> float | None:
    if v is None:
        return None
    m = re.search(r"-?\d+(?:[.,]\d+)?", v)
    return float(m.group().replace(",", ".")) if m else None


def _int(v: str | None) -> int | None:
    if v is None:
        return None
    m = re.search(r"\d+", v)
    return int(m.group()) if m else None


def legacy_attrs(
    label: NodeLabel, raw_label: str, page: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Best-effort typed attributes from the legacy node label and ``page.metadados``.

    Returns the attrs and the metadados keys consumed (the rest becomes ``metadata``)."""
    md: dict[str, Any] = page.get("metadados") or {}
    used: list[str] = []

    def take(*keys: str) -> str | None:
        v = _meta(md, *keys)
        if v is not None:
            used.extend(k for k in md if _norm(k) in {_norm(x) for x in keys})
        return v

    nome = page.get("nome") or raw_label
    attrs: dict[str, Any]
    if label is NodeLabel.ORGANIZACAO:
        attrs = {"name": raw_label, "sector": take("setor", "sector")}
    elif label is NodeLabel.DOMINIO:
        attrs = {"name": take("dominio", "domain", "fqdn") or raw_label}
    elif label is NodeLabel.ENDERECO_IP:
        asn_raw = take("asn")
        attrs = {
            "address": take("ip", "endereco", "address") or raw_label,
            "asn": _int(asn_raw),
            "asn_name": asn_raw.split("-", 1)[1].strip() if asn_raw and "-" in asn_raw else None,
            "country": take("pais", "country", "geolocalizacao", "geolocation"),
        }
    elif label is NodeLabel.SERVICO:
        port = _int(take("porta", "port")) or _int(
            raw_label.rsplit(":", 1)[-1] if ":" in raw_label else None
        )
        attrs = {
            "port": port if port is not None else 0,
            "protocol": (take("protocolo", "protocol") or "tcp")[:16],
            "service": raw_label.split(":")[0].strip()[:64] or None,
            "banner": take("banner"),
        }
    elif label is NodeLabel.SOFTWARE:
        # "FortiOS 6.0" -> product "FortiOS", version "6.0"; metadados.versao wins when present.
        product, version = raw_label, take("versao", "version")
        m = re.match(r"^(.*?)\s+(v?\d[\w.\-]*)$", raw_label)
        if m:
            product, version = m.group(1), version or m.group(2)
        attrs = {
            "product": product,
            "version": version,
            "vendor": take("fabricante", "vendor"),
            "cpe": take("cpe"),
        }
    elif label is NodeLabel.DISPOSITIVO_INDUSTRIAL:
        attrs = {
            "vendor": take("fabricante", "vendor"),
            "model": take("modelo", "model") or raw_label,
            "device_type": take("tipo", "tipo_dispositivo", "device_type"),
            "protocol": take("protocolo", "protocol"),
        }
    elif label is NodeLabel.CVE:
        attrs = {
            "cve_id": take("id_cve", "cve", "cve_id") or raw_label,
            "cvss": _float(take("cvss")),
            "severity": take("severidade", "severity"),
            "published": take("publicado", "published"),
        }
    elif label is NodeLabel.FUNCIONARIO:
        attrs = {
            "name": nome,
            "role": take("cargo", "role"),
            "email": take("email", "e_mail"),
            "profile_url": take("perfil", "profile", "linkedin", "url"),
        }
    elif label is NodeLabel.CREDENCIAL_VAZADA:
        attrs = {
            "email": take("email", "e_mail", "usuario", "user") or raw_label,
            "leak_name": take("fonte_vazamento", "vazamento", "leak", "leak_name"),
            "leak_date": take("data", "date", "leak_date"),
            "secret_type": take("tipo_segredo", "hash", "secret_type"),
        }
    elif label is NodeLabel.INSTALACAO_FISICA:
        coords = take("coordenadas", "coordinates", "geo")
        lat = lon = None
        if coords:
            nums = re.findall(r"-?\d+(?:\.\d+)?", coords)
            if len(nums) >= 2:
                lat, lon = float(nums[0]), float(nums[1])
        attrs = {
            "name": raw_label,
            "address": take("endereco", "address"),
            "latitude": lat,
            "longitude": lon,
            "facility_type": take("tipo_instalacao", "tipo", "facility_type"),
        }
    else:  # FORNECEDOR
        attrs = {
            "name": raw_label,
            "service_provided": take("servico_prestado", "servico", "service"),
            "asn": _int(take("asn")),
            "contract_ref": take("contrato", "contract", "contract_ref"),
        }
    return {k: v for k, v in attrs.items() if v is not None}, used


def _legacy_notes(page: dict[str, Any]) -> str:
    obs = page.get("observacoes") or []
    return "\n".join(f"- {o}" for o in obs if str(o).strip())


async def import_legacy(
    db: Neo4jClient, payload: dict[str, Any], name: str | None = None
) -> ImportReport:
    meta = payload.get("meta") or {}
    raw_nodes: list[dict[str, Any]] = payload.get("nodes") or []
    raw_edges: list[dict[str, Any]] = payload.get("edges") or []
    warnings: list[str] = []

    project = await projects.create_project(
        db,
        ProjectCreate(
            name=name or str(meta.get("entidade") or "Imported project"),
            description=str(meta.get("tipo") or ""),
        ),
    )
    pid = project.id
    provenance = Provenance(source=LEGACY_SOURCE, reviewed=True)

    id_map: dict[str, NodeOut] = {}
    structural: set[str] = set()
    for raw in raw_nodes:
        rid = str(raw.get("id") or new_id())
        tipo = str(raw.get("tipo") or "")
        eixo = _norm(str(raw.get("eixo") or ""))
        raw_label = str(raw.get("label") or raw.get("id") or "node")
        page = raw.get("page") or {}
        if _norm(tipo) in STRUCTURAL_TIPOS or eixo == "ferramentas":
            structural.add(rid)
            continue
        label = _LABEL_BY_NORM.get(_norm(tipo))
        metadata: dict[str, str] = {}
        if label is None:
            label = _DEFAULT_LABEL_BY_EIXO.get(eixo, NodeLabel.SOFTWARE)
            metadata["legacy_tipo"] = tipo
            warnings.append(
                f"node '{raw_label}': unknown type '{tipo}', imported as {label.value} (re-type it)"
            )
        attrs, used = legacy_attrs(label, raw_label, page)
        md = page.get("metadados") or {}
        for k, v in md.items():
            if k not in used and v not in (None, ""):
                metadata[str(k)] = str(v)
        if page.get("nome") and page["nome"] != raw_label:
            metadata.setdefault("nome", str(page["nome"]))
        try:
            validate_attrs(label, attrs)
        except ValidationError as exc:
            # Keep the analyst's data: fall back to the axis default label with a generic name.
            fallback = _DEFAULT_LABEL_BY_EIXO.get(eixo, NodeLabel.SOFTWARE)
            warnings.append(
                f"node '{raw_label}': {label.value} attributes invalid ({exc.errors()[0]['msg']}); "
                f"imported as {fallback.value} (re-type it)"
            )
            metadata["legacy_tipo"] = tipo
            label = fallback
            attrs, _ = legacy_attrs(label, raw_label, {"nome": page.get("nome"), "metadados": {}})
            if label is NodeLabel.SOFTWARE:
                attrs = {"product": raw_label}
        node = await crud.create_node(
            db,
            pid,
            NodeCreate(
                label=label,
                attrs=attrs,
                title=raw_label,
                description=str(page.get("descricao") or ""),
                notes=_legacy_notes(page),
                metadata=metadata,
                provenance=provenance,
            ),
        )
        id_map[rid] = node

    orgs = [n for n in id_map.values() if n.label is NodeLabel.ORGANIZACAO]
    root = orgs[0] if len(orgs) == 1 else None

    edges_created = 0
    anchored: set[str] = set()
    for raw in raw_edges:
        rel_raw = str(raw.get("rel") or "")
        rel_norm = _norm(rel_raw)
        src_id, dst_id = str(raw.get("from")), str(raw.get("to"))
        if rel_norm in STRUCTURAL_RELS:
            continue  # grouping edges of the reference layout, re-created as anchoring below
        if src_id in structural or dst_id in structural:
            continue
        src, dst = id_map.get(src_id), id_map.get(dst_id)
        if src is None or dst is None:
            warnings.append(
                f"edge {rel_raw} skipped: endpoint {src_id if src is None else dst_id} not imported"
            )
            continue
        rel = _REL_BY_NORM.get(rel_norm)
        if rel is None:
            warnings.append(
                f"edge {src.title} -[{rel_raw}]-> {dst.title} skipped: "
                "relationship type not in the schema"
            )
            continue
        if not is_allowed_edge(src.label, rel, dst.label):
            allowed = ", ".join(r.value for r in allowed_rel_types(src.label, dst.label)) or "none"
            warnings.append(
                f"edge {src.title} -[{rel.value}]-> {dst.title} skipped: not allowed between "
                f"{src.label.value} and {dst.label.value} (allowed: {allowed})"
            )
            continue
        impact = _IMPACT_BY_NORM.get(_norm(str(raw.get("impacto") or "")))
        try:
            await crud.create_edge(
                db,
                pid,
                EdgeCreate(
                    source_id=src.id,
                    target_id=dst.id,
                    rel=rel,
                    impact=impact,
                    provenance=provenance,
                ),
            )
            edges_created += 1
            if dst is root:
                anchored.add(src.id)
        except Exception as exc:  # one bad edge must not abort the whole import
            warnings.append(f"edge {src.title} -[{rel.value}]-> {dst.title} skipped: {exc}")

    if root is not None:
        for node in id_map.values():
            rel = _ANCHOR_REL.get(node.label)
            if rel is None or node.id in anchored:
                continue
            await crud.create_edge(
                db,
                pid,
                EdgeCreate(
                    source_id=node.id,
                    target_id=root.id,
                    rel=rel,
                    notes=(
                        "anchoring edge inferred on import "
                        "(replaces the reference layout's Esfera grouping)"
                    ),
                    provenance=provenance,
                ),
            )
            edges_created += 1
        await db.run(
            f"MATCH (p:{PROJECT_LABEL} {{id: $id}}) SET p.root_node_id = $root, p.org_name = $org",
            {"id": pid, "root": root.id, "org": root.title},
        )
    elif orgs:
        warnings.append("several Organizacao nodes found; no anchor was chosen")
    else:
        warnings.append("no Organizacao node found; nothing was anchored")

    seed_id = str(meta.get("seed") or "")
    seed = id_map.get(seed_id)
    if seed is not None and seed.label is NodeLabel.DOMINIO:
        await db.run(
            f"MATCH (p:{PROJECT_LABEL} {{id: $id}}) SET p.seed_domain = $seed",
            {"id": pid, "seed": seed.attrs.get("name")},
        )

    return ImportReport(
        project=await projects.get_project(db, pid),
        format="legacy",
        nodes_created=len(id_map),
        edges_created=edges_created,
        warnings=warnings,
    )


async def import_project(
    db: Neo4jClient, payload: dict[str, Any], name: str | None = None
) -> ImportReport:
    fmt = detect_format(payload)
    if fmt == FORMAT:
        return await import_typed(db, payload, name)
    return await import_legacy(db, payload, name)
