"""Shared fixtures. Unit tests never touch the network or Neo4j; integration tests are
marked ``neo4j`` and skip themselves when no database is reachable."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient
from neo4j import Record

from app.collectors.registry import make_http
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
def settings(tmp_path, monkeypatch) -> Settings:
    # Each test gets its own collector cache so recorded responses never leak between tests.
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    get_settings.cache_clear()
    s = get_settings()
    yield s
    get_settings.cache_clear()


@pytest.fixture
def fake_db(settings: Settings) -> FakeNeo4jClient:
    return FakeNeo4jClient(settings)


@pytest.fixture
async def client(fake_db: FakeNeo4jClient) -> AsyncIterator[AsyncClient]:
    """HTTP client against the ASGI app with the fake database injected.

    ``ASGITransport`` does not run the lifespan, so the real driver is never created."""
    app = create_app()
    app.state.db = fake_db
    app.state.http = make_http(get_settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await app.state.http.aclose()


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


@pytest.fixture
async def live_client(neo4j: Neo4jClient) -> AsyncIterator[AsyncClient]:
    """HTTP client against the app wired to the real database (integration tests)."""
    app = create_app()
    app.state.db = neo4j
    app.state.http = make_http(get_settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    await app.state.http.aclose()


@pytest.fixture
async def project(live_client: AsyncClient) -> AsyncIterator[dict[str, Any]]:
    """A throwaway project (with an Organizacao anchor), deleted after the test."""
    res = await live_client.post(
        "/api/projects",
        json={"name": "pytest project", "org_name": "Example Org", "seed_domain": "example.test"},
    )
    assert res.status_code == 201, res.text
    proj = res.json()
    try:
        yield proj
    finally:
        await live_client.delete(f"/api/projects/{proj['id']}")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # Give every test that uses the real database the ``neo4j`` marker automatically.
    for item in items:
        names = getattr(item, "fixturenames", ())
        if "neo4j" in names or "live_client" in names or "project" in names:
            item.add_marker(pytest.mark.neo4j)


# --- recorded collector responses -------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures" / "collectors"


def fixture_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def mocked_sources():
    """Route every third-party endpoint the collectors use to recorded fixtures. No test
    may reach the network: unknown URLs fail loudly."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as mock:
        mock.get("https://crt.sh/", params__contains={"q": "%.iana.org"}).mock(
            return_value=httpx.Response(200, json=fixture_json("crtsh-iana.json"))
        )
        mock.get("https://crt.sh/", params__contains={"q": "%.nothing.test"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        mock.get("https://data.iana.org/rdap/ipv4.json").mock(
            return_value=httpx.Response(200, json=fixture_json("iana-rdap-ipv4.json"))
        )
        mock.get("https://data.iana.org/rdap/asn.json").mock(
            return_value=httpx.Response(
                200, json={"services": [[["16876-16876"], ["https://rdap.arin.net/registry/"]]]}
            )
        )
        mock.get("https://rdap.arin.net/registry/ip/192.0.43.8").mock(
            return_value=httpx.Response(200, json=fixture_json("rdap-ip-192.0.43.8.json"))
        )
        mock.get("https://rdap.arin.net/registry/autnum/16876").mock(
            return_value=httpx.Response(200, json=fixture_json("rdap-autnum-16876.json"))
        )
        mock.get(
            "https://stat.ripe.net/data/prefix-overview/data.json",
            params__contains={"resource": "192.0.43.8"},
        ).mock(
            return_value=httpx.Response(
                200, json=fixture_json("ripestat-prefix-overview-192.0.43.8.json")
            )
        )
        mock.get(
            "https://stat.ripe.net/data/as-overview/data.json",
            params__contains={"resource": "AS16876"},
        ).mock(
            return_value=httpx.Response(200, json=fixture_json("ripestat-as-overview-16876.json"))
        )
        mock.get(
            "https://stat.ripe.net/data/announced-prefixes/data.json",
            params__contains={"resource": "AS16876"},
        ).mock(
            return_value=httpx.Response(
                200, json=fixture_json("ripestat-announced-prefixes-16876.json")
            )
        )
        mock.get(
            "https://services.nvd.nist.gov/rest/json/cves/2.0",
            params__contains={"virtualMatchString": "cpe:2.3:*:fortinet:fortios:6.0.4"},
        ).mock(return_value=httpx.Response(200, json=fixture_json("nvd-cves-fortios-6.0.4.json")))
        mock.get("https://services.nvd.nist.gov/rest/json/cves/2.0").mock(
            return_value=httpx.Response(200, json=fixture_json("nvd-cves-empty.json"))
        )
        yield mock
