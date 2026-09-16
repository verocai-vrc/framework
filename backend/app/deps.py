"""FastAPI dependencies shared by routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.config import Settings, get_settings
from app.db.driver import Neo4jClient
from app.i18n import t


def get_settings_dep() -> Settings:
    return get_settings()


async def get_db(request: Request) -> Neo4jClient:
    """Hand routers a ready database client, or a 503 that the UI can display."""
    client: Neo4jClient = request.app.state.db
    if not await client.ensure_schema():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=t("error.neo4j_unavailable"),
        )
    return client


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbDep = Annotated[Neo4jClient, Depends(get_db)]
