from __future__ import annotations

from app import __version__
from app.db.schema import SCHEMA_STATEMENTS


async def test_health_reports_connected_and_applies_schema(client, fake_db):
    res = await client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["neo4j"] == "connected"
    assert body["schema_applied"] is True
    assert body["passive_only"] is True
    assert body["version"] == __version__
    # Lazy schema application ran every constraint/index statement exactly once.
    ran = [q for q, _ in fake_db.queries]
    assert ran == [stmt for _, stmt in SCHEMA_STATEMENTS]


async def test_health_degraded_when_neo4j_down(client, fake_db):
    fake_db.connected = False
    res = await client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "degraded"
    assert body["neo4j"] == "unavailable"
    assert body["schema_applied"] is False
    assert fake_db.queries == []


async def test_frontend_shell_is_served(client):
    res = await client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert 'id="network"' in res.text
    assert "cdn" not in res.text.lower()  # offline-capable: no runtime CDN references
