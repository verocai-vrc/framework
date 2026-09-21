"""FastAPI application factory: driver lifecycle, routers, and the static front-end."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app import __version__
from app.collectors.registry import make_http
from app.config import FRONTEND_DIR, get_settings
from app.db.driver import Neo4jClient, Neo4jUnavailable
from app.errors import DomainError
from app.i18n import t
from app.routers import analysis, collectors, edges, health, io, nodes, projects, review, schema

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    client = Neo4jClient(settings)
    await client.connect()
    app.state.db = client
    app.state.http = make_http(settings)
    if await client.ensure_schema():
        log.info("connected to neo4j at %s", settings.neo4j_uri)
    else:
        log.warning("neo4j unreachable at %s; API starts degraded", settings.neo4j_uri)
    log.info("PASSIVE_ONLY=%s", settings.passive_only)
    try:
        yield
    finally:
        await app.state.http.aclose()
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
    app.include_router(collectors.router)
    app.include_router(review.router)
    app.include_router(analysis.router)

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        locale = request.headers.get("x-locale", settings.default_locale)
        detail = t(exc.key, locale, **exc.extra) or exc.message
        # The localised sentence for a rejected collector input is generic; the specific
        # reason ("needs a domain seed") is what lets the analyst fix it.
        if exc.key == "error.collector_input" and exc.message:
            detail = f"{detail} {exc.message[0].upper()}{exc.message[1:]}."
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": detail,
                "code": exc.key,
                "message": exc.message,
                **exc.extra,
            },
        )

    # Body validation raises FastAPI's RequestValidationError, not pydantic's ValidationError;
    # both are flattened to one readable ``detail`` string (the UI shows it as-is).
    @app.exception_handler(ValidationError)
    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _: Request, exc: ValidationError | RequestValidationError
    ) -> JSONResponse:
        raw = exc.errors(include_url=False) if isinstance(exc, ValidationError) else exc.errors()
        errors = [
            {
                # "body.attrs.address" -> "address": the field name is what the analyst typed in.
                "loc": [str(x) for x in e.get("loc", ()) if x not in ("body", "attrs")],
                "msg": str(e.get("msg", "")).removeprefix("Value error, "),
            }
            for e in raw
        ]
        detail = "; ".join(f"{'.'.join(e['loc']) or 'value'}: {e['msg']}" for e in errors)
        return JSONResponse(
            status_code=422,
            content={"detail": detail, "code": "error.validation", "errors": errors},
        )

    @app.exception_handler(Neo4jUnavailable)
    async def _neo4j_unavailable(_: Request, exc: Neo4jUnavailable) -> JSONResponse:
        log.warning("neo4j unavailable during request: %s", exc)
        return JSONResponse(status_code=503, content={"detail": t("error.neo4j_unavailable")})

    # Mounted last so API routes win; ``html=True`` serves index.html at ``/``.
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
