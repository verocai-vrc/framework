from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.collectors import registry
from app.deps import DbDep, SettingsDep
from app.models.candidates import RunReport, RunRequest

router = APIRouter(prefix="/api", tags=["collectors"])


@router.get("/collectors")
async def list_collectors(settings: SettingsDep) -> list[dict[str, Any]]:
    return [c.describe(settings.passive_only) for c in registry.REGISTRY.values()]


@router.post("/projects/{project_id}/collectors/{name}/run", response_model=RunReport)
async def run_collector(
    project_id: str, name: str, data: RunRequest, request: Request, db: DbDep, settings: SettingsDep
) -> RunReport:
    return await registry.run(
        name, project_id, db, settings, request.app.state.http, seed=data.seed, node_id=data.node_id
    )
