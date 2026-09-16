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
from app.errors import DomainError
from app.i18n import t
from app.routers import edges, health, io, nodes, projects, schema

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
    app.include_router(schema.router)
    app.include_router(projects.router)
    app.include_router(nodes.router)
    app.include_router(edges.router)
    app.include_router(io.router)

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        locale = request.headers.get("x-locale", settings.default_locale)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": t(exc.key, locale, **exc.extra) or exc.message,
                "code": exc.key,
                "message": exc.message,
                **exc.extra,
            },
        )

    @app.exception_handler(Neo4jUnavailable)
    async def _neo4j_unavailable(_: Request, exc: Neo4jUnavailable) -> JSONResponse:
        log.warning("neo4j unavailable during request: %s", exc)
        return JSONResponse(status_code=503, content={"detail": t("error.neo4j_unavailable")})

    # Mounted last so API routes win; ``html=True`` serves index.html at ``/``.
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
