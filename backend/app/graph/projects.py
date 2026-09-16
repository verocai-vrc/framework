"""Project (investigation) abstraction. A project owns its nodes, edges and candidates and
optionally an ``Organizacao`` anchor node created from ``org_name``."""

from __future__ import annotations

from typing import Any

from neo4j.graph import Node

from app.db.driver import Neo4jClient
from app.db.schema import CANDIDATE_LABEL, ENTITY_LABEL, PROJECT_LABEL, NodeLabel
from app.errors import NotFound
from app.graph import crud
from app.models.common import new_id, utcnow_iso
from app.models.nodes import NodeCreate
from app.models.projects import ProjectCreate, ProjectOut, ProjectUpdate

_RETURN_PROJECT = f"""
OPTIONAL MATCH (n:{ENTITY_LABEL} {{project_id: p.id}})
WITH p, count(n) AS node_count
OPTIONAL MATCH (:{ENTITY_LABEL} {{project_id: p.id}})-[r]->(:{ENTITY_LABEL})
RETURN p, node_count, count(r) AS edge_count
"""


def _to_out(p: Node, node_count: int = 0, edge_count: int = 0) -> ProjectOut:
    props: dict[str, Any] = dict(p)
    return ProjectOut(
        id=props["id"],
        name=props["name"],
        description=props.get("description", ""),
        org_name=props.get("org_name"),
        seed_domain=props.get("seed_domain"),
        root_node_id=props.get("root_node_id"),
        created_at=props["created_at"],
        updated_at=props["updated_at"],
        node_count=node_count,
        edge_count=edge_count,
    )


async def create_project(db: Neo4jClient, data: ProjectCreate) -> ProjectOut:
    now = utcnow_iso()
    props: dict[str, Any] = {
        "id": new_id(),
        "name": data.name,
        "description": data.description,
        "created_at": now,
        "updated_at": now,
    }
    if data.org_name:
        props["org_name"] = data.org_name
    if data.seed_domain:
        props["seed_domain"] = data.seed_domain.strip().lower()
    await db.run(f"CREATE (p:{PROJECT_LABEL}) SET p = $props", {"props": props})

    if data.org_name:
        root = await crud.create_node(
            db,
            props["id"],
            NodeCreate(label=NodeLabel.ORGANIZACAO, attrs={"name": data.org_name}),
        )
        await db.run(
            f"MATCH (p:{PROJECT_LABEL} {{id: $id}}) SET p.root_node_id = $root",
            {"id": props["id"], "root": root.id},
        )
    return await get_project(db, props["id"])


async def get_project(db: Neo4jClient, project_id: str) -> ProjectOut:
    rec = await db.run_one(
        f"MATCH (p:{PROJECT_LABEL} {{id: $id}}) {_RETURN_PROJECT}",
        {"id": project_id},
        readonly=True,
    )
    if rec is None:
        raise NotFound("project not found", id=project_id)
    return _to_out(rec["p"], rec["node_count"], rec["edge_count"])


async def list_projects(db: Neo4jClient) -> list[ProjectOut]:
    recs = await db.run(
        f"MATCH (p:{PROJECT_LABEL}) {_RETURN_PROJECT} ORDER BY p.created_at, p.id", readonly=True
    )
    return [_to_out(r["p"], r["node_count"], r["edge_count"]) for r in recs]


async def update_project(db: Neo4jClient, project_id: str, data: ProjectUpdate) -> ProjectOut:
    set_props: dict[str, Any] = {"updated_at": utcnow_iso()}
    for key in ("name", "description", "org_name", "seed_domain"):
        value = getattr(data, key)
        if value is not None:
            set_props[key] = value.strip().lower() if key == "seed_domain" else value
    rec = await db.run_one(
        f"MATCH (p:{PROJECT_LABEL} {{id: $id}}) SET p += $props RETURN p",
        {"id": project_id, "props": set_props},
    )
    if rec is None:
        raise NotFound("project not found", id=project_id)
    return await get_project(db, project_id)


async def delete_project(db: Neo4jClient, project_id: str) -> None:
    await get_project(db, project_id)
    await db.run(
        f"MATCH (n:{ENTITY_LABEL} {{project_id: $id}}) DETACH DELETE n", {"id": project_id}
    )
    await db.run(
        f"MATCH (c:{CANDIDATE_LABEL} {{project_id: $id}}) DETACH DELETE c", {"id": project_id}
    )
    await db.run(f"MATCH (p:{PROJECT_LABEL} {{id: $id}}) DETACH DELETE p", {"id": project_id})
