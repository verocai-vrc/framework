from __future__ import annotations

from fastapi import APIRouter, status

from app.deps import DbDep
from app.graph import projects
from app.models.projects import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
async def list_projects(db: DbDep) -> list[ProjectOut]:
    return await projects.list_projects(db)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(data: ProjectCreate, db: DbDep) -> ProjectOut:
    return await projects.create_project(db, data)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, db: DbDep) -> ProjectOut:
    return await projects.get_project(db, project_id)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(project_id: str, data: ProjectUpdate, db: DbDep) -> ProjectOut:
    return await projects.update_project(db, project_id, data)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str, db: DbDep) -> None:
    await projects.delete_project(db, project_id)
