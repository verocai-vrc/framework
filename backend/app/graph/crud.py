"""Typed node/edge CRUD against Neo4j with edge-validity enforcement and provenance.

Labels and relationship types spliced into Cypher always come from the schema enums, so
the statements stay safe; every value travels as a parameter.
"""

from __future__ import annotations

import json
from typing import Any

from neo4j.graph import Node, Relationship

from app.db.driver import Neo4jClient
from app.db.schema import (
    ENTITY_LABEL,
    LABEL_SPECS,
    Axis,
    Layer,
    NodeLabel,
    RelType,
    allowed_rel_types,
    is_allowed_edge,
)
from app.errors import Conflict, InvalidEdge, NotFound
from app.models.common import Impact, new_id, utcnow_iso
from app.models.edges import EdgeCreate, EdgeOut, EdgeUpdate, GraphOut
from app.models.nodes import (
    RESERVED_PROPS,
    NodeCreate,
    NodeOut,
    NodeUpdate,
    resolve_layer,
    validate_attrs,
)

# --- (de)serialisation ------------------------------------------------------------------


def _label_of(labels: list[str]) -> NodeLabel:
    for candidate in labels:
        if candidate != ENTITY_LABEL:
            return NodeLabel(candidate)
    raise ValueError(f"node without a thesis label: {labels}")


def node_to_out(node: Node, labels: list[str]) -> NodeOut:
    props = dict(node)
    label = _label_of(labels)
    attrs = {k: v for k, v in props.items() if k not in RESERVED_PROPS}
    return NodeOut(
        id=props["id"],
        project_id=props["project_id"],
        label=label,
        label_display=props.get("label_display", LABEL_SPECS[label].display_pt),
        axis=Axis(props["axis"]),
        layer=Layer(props["layer"]) if props.get("layer") else None,
        title=props.get("title", ""),
        description=props.get("description", ""),
        notes=props.get("notes", ""),
        attrs=attrs,
        metadata=json.loads(props.get("metadata_json") or "{}"),
        source=props.get("source", "manual"),
        collected_at=props.get("collected_at", ""),
        reviewed=bool(props.get("reviewed", False)),
        created_at=props.get("created_at", ""),
        updated_at=props.get("updated_at", ""),
    )


def _clean_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Drop ``None`` values: Neo4j has no null properties, and absence means the same."""
    return {k: v for k, v in attrs.items() if v is not None}


def node_props(project_id: str, data: NodeCreate) -> dict[str, Any]:
    attrs_model = validate_attrs(data.label, data.attrs)
    spec = LABEL_SPECS[data.label]
    now = utcnow_iso()
    props: dict[str, Any] = {
        "id": new_id(),
        "project_id": project_id,
        "label_display": spec.display_pt,
        "axis": spec.axis.value,
        "title": (data.title or attrs_model.default_title() or data.label.value).strip(),
        "description": data.description,
        "notes": data.notes,
        "metadata_json": json.dumps(data.metadata, ensure_ascii=False),
        "source": data.provenance.source,
        "collected_at": data.provenance.collected_at,
        "reviewed": data.provenance.reviewed,
        "created_at": now,
        "updated_at": now,
    }
    layer = resolve_layer(data.label, data.layer)
    if layer is not None:
        props["layer"] = layer.value
    props.update(_clean_attrs(attrs_model.model_dump()))
    return props


def cross_axis(a_axis: Axis, a_layer: Layer | None, b_axis: Axis, b_layer: Layer | None) -> bool:
    """True when the endpoints sit in different axes, or in different IT/OT layers of the
    DIGITAL axis (Tabela 8 treats TI -> TO as a crossing)."""
    if a_axis != b_axis:
        return True
    return (
        a_axis == Axis.DIGITAL
        and a_layer is not None
        and b_layer is not None
        and a_layer != b_layer
    )


def edge_to_out(
    rel: Relationship,
    rel_type: str,
    a: NodeOut | Node,
    a_labels: list[str],
    b: NodeOut | Node,
    b_labels: list[str],
) -> EdgeOut:
    a_out = a if isinstance(a, NodeOut) else node_to_out(a, a_labels)
    b_out = b if isinstance(b, NodeOut) else node_to_out(b, b_labels)
    props = dict(rel)
    return EdgeOut(
        id=props["id"],
        project_id=props["project_id"],
        rel=RelType(rel_type),
        source_id=a_out.id,
        target_id=b_out.id,
        source_label=a_out.label,
        target_label=b_out.label,
        cross_axis=cross_axis(a_out.axis, a_out.layer, b_out.axis, b_out.layer),
        notes=props.get("notes", ""),
        impact=Impact(props["impact"]) if props.get("impact") else None,
        weight=props.get("weight"),
        source=props.get("source", "manual"),
        collected_at=props.get("collected_at", ""),
        reviewed=bool(props.get("reviewed", False)),
        created_at=props.get("created_at", ""),
        updated_at=props.get("updated_at", ""),
    )


# --- nodes ------------------------------------------------------------------------------

_RETURN_NODE = "RETURN n, labels(n) AS labels"


async def create_node(db: Neo4jClient, project_id: str, data: NodeCreate) -> NodeOut:
    props = node_props(project_id, data)
    rec = await db.run_one(
        f"CREATE (n:{ENTITY_LABEL}:{data.label.value}) SET n = $props {_RETURN_NODE}",
        {"props": props},
    )
    assert rec is not None
    return node_to_out(rec["n"], rec["labels"])


async def get_node(db: Neo4jClient, node_id: str) -> NodeOut:
    rec = await db.run_one(
        f"MATCH (n:{ENTITY_LABEL} {{id: $id}}) {_RETURN_NODE}", {"id": node_id}, readonly=True
    )
    if rec is None:
        raise NotFound("node not found", id=node_id)
    return node_to_out(rec["n"], rec["labels"])


async def list_nodes(db: Neo4jClient, project_id: str) -> list[NodeOut]:
    recs = await db.run(
        f"MATCH (n:{ENTITY_LABEL} {{project_id: $pid}}) {_RETURN_NODE} ORDER BY n.created_at, n.id",
        {"pid": project_id},
        readonly=True,
    )
    return [node_to_out(r["n"], r["labels"]) for r in recs]


async def update_node(db: Neo4jClient, node_id: str, data: NodeUpdate) -> NodeOut:
    current = await get_node(db, node_id)
    rec = await db.run_one(
        f"MATCH (n:{ENTITY_LABEL} {{id: $id}}) RETURN n", {"id": node_id}, readonly=True
    )
    assert rec is not None
    props: dict[str, Any] = dict(rec["n"])

    if data.attrs is not None:
        attrs_model = validate_attrs(current.label, data.attrs)
        for key in list(props):
            if key not in RESERVED_PROPS:
                del props[key]
        props.update(_clean_attrs(attrs_model.model_dump()))
        old_default = validate_attrs(current.label, current.attrs).default_title()
        if data.title is None and current.title == old_default:
            # The title was derived from the attributes, so follow them.
            props["title"] = attrs_model.default_title() or current.title
    if data.title is not None:
        props["title"] = data.title.strip() or props["title"]
    if data.description is not None:
        props["description"] = data.description
    if data.notes is not None:
        props["notes"] = data.notes
    if data.metadata is not None:
        props["metadata_json"] = json.dumps(data.metadata, ensure_ascii=False)
    if data.layer is not None:
        layer = resolve_layer(current.label, data.layer)
        if layer is not None:
            props["layer"] = layer.value
    props["updated_at"] = utcnow_iso()

    rec = await db.run_one(
        f"MATCH (n:{ENTITY_LABEL} {{id: $id}}) SET n = $props {_RETURN_NODE}",
        {"id": node_id, "props": props},
    )
    assert rec is not None
    return node_to_out(rec["n"], rec["labels"])


async def delete_node(db: Neo4jClient, node_id: str) -> None:
    rec = await db.run_one(
        f"MATCH (n:{ENTITY_LABEL} {{id: $id}}) DETACH DELETE n RETURN count(n) AS deleted",
        {"id": node_id},
    )
    if rec is None or rec["deleted"] == 0:
        raise NotFound("node not found", id=node_id)


# --- edges ------------------------------------------------------------------------------

_MATCH_EDGE_BY_ID = f"MATCH (a:{ENTITY_LABEL})-[r]->(b:{ENTITY_LABEL}) WHERE r.id = $id"
_RETURN_EDGE = "RETURN r, type(r) AS rel, a, labels(a) AS a_labels, b, labels(b) AS b_labels"


def check_edge_allowed(source: NodeOut, rel: RelType, target: NodeOut) -> None:
    """Raise ``InvalidEdge`` with a hint listing what *is* allowed between the endpoints."""
    if is_allowed_edge(source.label, rel, target.label):
        return
    raise InvalidEdge(
        f"{source.label.value} -[{rel.value}]-> {target.label.value} is not allowed",
        rel=rel.value,
        source_label=source.label.value,
        target_label=target.label.value,
        allowed=[r.value for r in allowed_rel_types(source.label, target.label)],
        reverse_allowed=[r.value for r in allowed_rel_types(target.label, source.label)],
    )


async def create_edge(db: Neo4jClient, project_id: str, data: EdgeCreate) -> EdgeOut:
    if data.source_id == data.target_id:
        raise InvalidEdge("an edge cannot connect a node to itself", rel=data.rel.value)
    source = await get_node(db, data.source_id)
    target = await get_node(db, data.target_id)
    if source.project_id != project_id or target.project_id != project_id:
        raise InvalidEdge("both endpoints must belong to the project", rel=data.rel.value)
    check_edge_allowed(source, data.rel, target)

    dup = await db.run_one(
        f"MATCH (a:{ENTITY_LABEL} {{id: $sid}})-[r:{data.rel.value}]->"
        f"(b:{ENTITY_LABEL} {{id: $tid}}) RETURN r.id AS id",
        {"sid": data.source_id, "tid": data.target_id},
        readonly=True,
    )
    if dup is not None:
        raise Conflict("this relationship already exists", id=dup["id"])

    now = utcnow_iso()
    props: dict[str, Any] = {
        "id": new_id(),
        "project_id": project_id,
        "notes": data.notes,
        "source": data.provenance.source,
        "collected_at": data.provenance.collected_at,
        "reviewed": data.provenance.reviewed,
        "created_at": now,
        "updated_at": now,
    }
    if data.impact is not None:
        props["impact"] = data.impact.value
    if data.weight is not None:
        props["weight"] = data.weight
    rec = await db.run_one(
        f"MATCH (a:{ENTITY_LABEL} {{id: $sid}}), (b:{ENTITY_LABEL} {{id: $tid}}) "
        f"CREATE (a)-[r:{data.rel.value}]->(b) SET r = $props {_RETURN_EDGE}",
        {"sid": data.source_id, "tid": data.target_id, "props": props},
    )
    assert rec is not None
    return edge_to_out(rec["r"], rec["rel"], source, [], target, [])


async def get_edge(db: Neo4jClient, edge_id: str) -> EdgeOut:
    rec = await db.run_one(f"{_MATCH_EDGE_BY_ID} {_RETURN_EDGE}", {"id": edge_id}, readonly=True)
    if rec is None:
        raise NotFound("edge not found", id=edge_id)
    return edge_to_out(rec["r"], rec["rel"], rec["a"], rec["a_labels"], rec["b"], rec["b_labels"])


async def list_edges(db: Neo4jClient, project_id: str) -> list[EdgeOut]:
    recs = await db.run(
        f"MATCH (a:{ENTITY_LABEL} {{project_id: $pid}})-[r]->(b:{ENTITY_LABEL}) "
        f"{_RETURN_EDGE} ORDER BY r.created_at, r.id",
        {"pid": project_id},
        readonly=True,
    )
    return [
        edge_to_out(r["r"], r["rel"], r["a"], r["a_labels"], r["b"], r["b_labels"]) for r in recs
    ]


async def update_edge(db: Neo4jClient, edge_id: str, data: EdgeUpdate) -> EdgeOut:
    set_props: dict[str, Any] = {"updated_at": utcnow_iso()}
    if data.notes is not None:
        set_props["notes"] = data.notes
    if data.impact is not None:
        set_props["impact"] = data.impact.value
    if data.weight is not None:
        set_props["weight"] = data.weight
    rec = await db.run_one(
        f"{_MATCH_EDGE_BY_ID} SET r += $props {_RETURN_EDGE}", {"id": edge_id, "props": set_props}
    )
    if rec is None:
        raise NotFound("edge not found", id=edge_id)
    return edge_to_out(rec["r"], rec["rel"], rec["a"], rec["a_labels"], rec["b"], rec["b_labels"])


async def delete_edge(db: Neo4jClient, edge_id: str) -> None:
    rec = await db.run_one(
        f"{_MATCH_EDGE_BY_ID} DELETE r RETURN count(r) AS deleted", {"id": edge_id}
    )
    if rec is None or rec["deleted"] == 0:
        raise NotFound("edge not found", id=edge_id)


# --- whole graph ------------------------------------------------------------------------


async def get_graph(db: Neo4jClient, project_id: str) -> GraphOut:
    return GraphOut(
        project_id=project_id,
        nodes=await list_nodes(db, project_id),
        edges=await list_edges(db, project_id),
    )
