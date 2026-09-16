from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Query, status
from fastapi.responses import JSONResponse

from app.deps import DbDep
from app.graph import io

router = APIRouter(prefix="/api", tags=["import-export"])


@router.get("/projects/{project_id}/export")
async def export_project(project_id: str, db: DbDep) -> JSONResponse:
    data = await io.export_project(db, project_id)
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", data.project.name).strip("-").lower() or "project"
    return JSONResponse(
        content=data.model_dump(mode="json"),
        headers={"Content-Disposition": f'attachment; filename="{slug}.osintree.json"'},
    )


@router.post(
    "/projects/import", response_model=io.ImportReport, status_code=status.HTTP_201_CREATED
)
async def import_project(
    payload: dict[str, Any], db: DbDep, name: str | None = Query(default=None, max_length=120)
) -> io.ImportReport:
    """Accepts either an ``osintree/1`` export or the reference tool's legacy JSON."""
    return await io.import_project(db, payload, name)
