"""Shared fixtures. Unit tests never touch the network or Neo4j; integration tests are
marked ``neo4j`` and skip themselves when no database is reachable."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from neo4j import Record

from app.config import Settings, get_settings
from app.db.driver import Neo4jClient
from app.main import create_app

os.environ.setdefault("NEO4J_PASSWORD", "osintree-dev")


class FakeNeo4jClient(Neo4jClient):
    """In-memory stand-in: records every query, answers from a canned table."""

    def __init__(self, settings: Settings, *, connected: bool = True) -> None:
        super().__init__(settings)
        self.connected = connected
        self.queries: list[tuple[str, dict[str, Any]]] = []
        self.responses: dict[str, list[Record]] = {}

    async def connect(self) -> None:  # no real driver
        return None

    async def close(self) -> None:
        return None

    async def verify(self) -> bool:
        return self.connected

    async def run(self, query, parameters=None, *, readonly=False):  # type: ignore[override]
        self.queries.append((query, dict(parameters or {})))
        return self.responses.get(query, [])


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def fake_db(settings: Settings) -> FakeNeo4jClient:
    return FakeNeo4jClient(settings)


@pytest.fixture
async def client(fake_db: FakeNeo4jClient) -> AsyncIterator[AsyncClient]:
    """HTTP client against the ASGI app with the fake database injected.

    ``ASGITransport`` does not run the lifespan, so the real driver is never created."""
    app = create_app()
    app.state.db = fake_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def neo4j(settings: Settings) -> AsyncIterator[Neo4jClient]:
    """Real database client for tests marked ``neo4j``; skips when unreachable."""
    db = Neo4jClient(settings)
    await db.connect()
    try:
        if not await db.verify():
            pytest.skip(f"Neo4j not reachable at {settings.neo4j_uri}")
        await db.ensure_schema()
        yield db
    finally:
        await db.close()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # Give every test that uses the real database the ``neo4j`` marker automatically.
    for item in items:
        if "neo4j" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.neo4j)
