"""Analysis endpoints: run the engine, download the report.

``POST /api/projects/{id}/analysis`` stamps risk on every edge (side effect) and returns
the full ``AnalysisResult``; ``GET /api/projects/{id}/report`` re-runs it and renders one
of the three formats as a download."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.analysis import criteria, report
from app.analysis.paths import EntryPolicy
from app.deps import DbDep, SettingsDep
from app.graph import crud
from app.i18n import SUPPORTED_LOCALES
from app.models.analysis import AnalysisOptions, AnalysisResult

router = APIRouter(prefix="/api", tags=["analysis"])


def _locale(requested: str | None, default: str) -> str:
    return requested if requested in SUPPORTED_LOCALES else default


@router.post("/projects/{project_id}/analysis", response_model=AnalysisResult)
async def run_analysis(
    project_id: str,
    db: DbDep,
    settings: SettingsDep,
    options: AnalysisOptions | None = None,
    entry: Annotated[EntryPolicy, Query()] = "digital",
    locale: Annotated[str | None, Query()] = None,
) -> AnalysisResult:
    return await criteria.analyse(
        db,
        project_id,
        options,
        entry=entry,
        locale=_locale(locale, settings.default_locale),
    )


@router.get("/projects/{project_id}/report")
async def download_report(
    project_id: str,
    db: DbDep,
    settings: SettingsDep,
    format: Annotated[Literal["md", "html", "json"], Query()] = "md",
    entry: Annotated[EntryPolicy, Query()] = "digital",
    locale: Annotated[str | None, Query()] = None,
    inline: Annotated[bool, Query(description="Render in the browser, not as a download")] = False,
) -> Response:
    loc = _locale(locale, settings.report_locale)
    result = await criteria.analyse(db, project_id, entry=entry, locale=loc)
    graph = await crud.get_graph(db, project_id)
    content, media_type = report.render(
        result, graph, format, locale=loc, app_name=settings.app_name, entry=entry
    )
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", result.project.name).strip("-").lower() or "project"
    disposition = "inline" if inline else "attachment"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{slug}-report.{format}"'},
    )
