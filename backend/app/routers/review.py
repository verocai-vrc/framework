from __future__ import annotations

from fastapi import APIRouter, Query

from app.deps import DbDep
from app.graph import projects
from app.models.candidates import BulkIds, CandidateOut, CandidateUpdate
from app.review import staging

router = APIRouter(prefix="/api", tags=["review"])


@router.get("/projects/{project_id}/candidates", response_model=list[CandidateOut])
async def list_candidates(
    project_id: str,
    db: DbDep,
    status: str | None = Query(default=None, pattern="^(pending|approved|rejected)$"),
) -> list[CandidateOut]:
    await projects.get_project(db, project_id)
    return await staging.list_candidates(db, project_id, status)


@router.get("/projects/{project_id}/candidates/count")
async def count_pending(project_id: str, db: DbDep) -> dict[str, int]:
    return {"pending": await staging.count_pending(db, project_id)}


@router.delete("/projects/{project_id}/candidates")
async def purge_candidates(
    project_id: str, db: DbDep, status: str = Query(pattern="^(approved|rejected)$")
) -> dict[str, int]:
    await projects.get_project(db, project_id)
    return {"deleted": await staging.purge(db, project_id, status)}


@router.post("/projects/{project_id}/candidates/approve", response_model=list[CandidateOut])
async def approve_many(project_id: str, data: BulkIds, db: DbDep) -> list[CandidateOut]:
    await projects.get_project(db, project_id)
    return [await staging.approve(db, cid) for cid in data.ids]


@router.post("/projects/{project_id}/candidates/reject", response_model=list[CandidateOut])
async def reject_many(project_id: str, data: BulkIds, db: DbDep) -> list[CandidateOut]:
    await projects.get_project(db, project_id)
    return [await staging.reject(db, cid) for cid in data.ids]


@router.get("/candidates/{candidate_id}", response_model=CandidateOut)
async def get_candidate(candidate_id: str, db: DbDep) -> CandidateOut:
    return await staging.get_candidate(db, candidate_id)


@router.patch("/candidates/{candidate_id}", response_model=CandidateOut)
async def update_candidate(candidate_id: str, data: CandidateUpdate, db: DbDep) -> CandidateOut:
    return await staging.update_candidate(db, candidate_id, data)


@router.post("/candidates/{candidate_id}/approve", response_model=CandidateOut)
async def approve_candidate(candidate_id: str, db: DbDep) -> CandidateOut:
    return await staging.approve(db, candidate_id)


@router.post("/candidates/{candidate_id}/reject", response_model=CandidateOut)
async def reject_candidate(candidate_id: str, db: DbDep) -> CandidateOut:
    return await staging.reject(db, candidate_id)
