from __future__ import annotations

from fastapi import APIRouter, status

from app.deps import DbDep
from app.graph import crud, projects
from app.models.edges import EdgeCreate, EdgeOut, EdgeUpdate

router = APIRouter(prefix="/api", tags=["edges"])


@router.get("/projects/{project_id}/edges", response_model=list[EdgeOut])
async def list_edges(project_id: str, db: DbDep) -> list[EdgeOut]:
    await projects.get_project(db, project_id)
    return await crud.list_edges(db, project_id)


@router.post(
    "/projects/{project_id}/edges", response_model=EdgeOut, status_code=status.HTTP_201_CREATED
)
async def create_edge(project_id: str, data: EdgeCreate, db: DbDep) -> EdgeOut:
    await projects.get_project(db, project_id)
    return await crud.create_edge(db, project_id, data)


@router.get("/edges/{edge_id}", response_model=EdgeOut)
async def get_edge(edge_id: str, db: DbDep) -> EdgeOut:
    return await crud.get_edge(db, edge_id)


@router.patch("/edges/{edge_id}", response_model=EdgeOut)
async def update_edge(edge_id: str, data: EdgeUpdate, db: DbDep) -> EdgeOut:
    return await crud.update_edge(db, edge_id, data)


@router.delete("/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_edge(edge_id: str, db: DbDep) -> None:
    await crud.delete_edge(db, edge_id)
