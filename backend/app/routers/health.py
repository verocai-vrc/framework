"""``GET /health``: app status plus Neo4j connectivity and schema state."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import __version__
from app.config import get_settings
from app.db.driver import Neo4jClient
from app.i18n import t

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    neo4j: str
    schema_applied: bool
    passive_only: bool


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = get_settings()
    client: Neo4jClient = request.app.state.db
    connected = await client.verify()
    if connected and not client.schema_applied:
        # Neo4j may have come up after the app did; finish startup work lazily.
        await client.ensure_schema()
    return HealthResponse(
        status=t("health.ok") if connected else t("health.degraded"),
        app=settings.app_name,
        version=__version__,
        neo4j=t("neo4j.connected") if connected else t("neo4j.unavailable"),
        schema_applied=client.schema_applied,
        passive_only=settings.passive_only,
    )
