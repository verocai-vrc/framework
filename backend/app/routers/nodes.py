from __future__ import annotations

from fastapi import APIRouter, status

from app.deps import DbDep
from app.graph import crud, projects
from app.models.edges import GraphOut
from app.models.nodes import NodeCreate, NodeOut, NodeUpdate

router = APIRouter(prefix="/api", tags=["nodes"])


@router.get("/projects/{project_id}/graph", response_model=GraphOut)
async def get_graph(project_id: str, db: DbDep) -> GraphOut:
    await projects.get_project(db, project_id)
    return await crud.get_graph(db, project_id)


@router.get("/projects/{project_id}/nodes", response_model=list[NodeOut])
async def list_nodes(project_id: str, db: DbDep) -> list[NodeOut]:
    await projects.get_project(db, project_id)
    return await crud.list_nodes(db, project_id)


@router.post(
    "/projects/{project_id}/nodes", response_model=NodeOut, status_code=status.HTTP_201_CREATED
)
async def create_node(project_id: str, data: NodeCreate, db: DbDep) -> NodeOut:
    await projects.get_project(db, project_id)
    return await crud.create_node(db, project_id, data)


@router.get("/nodes/{node_id}", response_model=NodeOut)
async def get_node(node_id: str, db: DbDep) -> NodeOut:
    return await crud.get_node(db, node_id)


@router.patch("/nodes/{node_id}", response_model=NodeOut)
async def update_node(node_id: str, data: NodeUpdate, db: DbDep) -> NodeOut:
    return await crud.update_node(db, node_id, data)


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(node_id: str, db: DbDep) -> None:
    await crud.delete_node(db, node_id)
