"""FastAPI application factory: driver lifecycle, routers, and the static front-end."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import FRONTEND_DIR, get_settings
from app.db.driver import Neo4jClient, Neo4jUnavailable
from app.i18n import t
from app.routers import health

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    client = Neo4jClient(settings)
    await client.connect()
    app.state.db = client
    if await client.ensure_schema():
        log.info("connected to neo4j at %s", settings.neo4j_uri)
    else:
        log.warning("neo4j unreachable at %s; API starts degraded", settings.neo4j_uri)
    log.info("PASSIVE_ONLY=%s", settings.passive_only)
    try:
        yield
    finally:
        await client.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)

    app.include_router(health.router)

    @app.exception_handler(Neo4jUnavailable)
    async def _neo4j_unavailable(_: Request, exc: Neo4jUnavailable) -> JSONResponse:
        log.warning("neo4j unavailable during request: %s", exc)
        return JSONResponse(status_code=503, content={"detail": t("error.neo4j_unavailable")})

    # Mounted last so API routes win; ``html=True`` serves index.html at ``/``.
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
