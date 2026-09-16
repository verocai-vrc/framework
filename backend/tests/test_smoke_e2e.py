"""One end-to-end smoke run over the live Neo4j (brief, Section 10): seed the fixture
project, collect with recorded responses, review and merge, run the analysis, assert the
three thesis criteria, render the report, and prove the export/import round trip keeps
the analysis result. Third-party HTTP is mocked; the target is never contacted."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from app.graph.fixture import seed_fixture


@pytest.fixture
async def smoke_project(neo4j, live_client) -> AsyncIterator[dict]:
    project = await seed_fixture(neo4j, "pytest smoke")
    created = [project.id]
    try:
        yield {"project": project.model_dump(), "created": created}
    finally:
        for pid in created:
            await live_client.delete(f"/api/projects/{pid}")


async def test_smoke_end_to_end(live_client, smoke_project, mocked_sources):
    pid = smoke_project["project"]["id"]

    # 1. Passive guard: an active collector is refused before it runs; the passive one runs
    #    against the seed and only stages candidates (graph untouched).
    res = await live_client.post(
        f"/api/projects/{pid}/collectors/active_probe_example/run", json={}
    )
    assert res.status_code == 403, res.text
    before = (await live_client.get(f"/api/projects/{pid}/graph")).json()
    res = await live_client.post(
        f"/api/projects/{pid}/collectors/crtsh/run", json={"seed": "iana.org"}
    )
    assert res.status_code == 200, res.text
    run = res.json()
    assert run["staged"] >= 1 and run["candidates"][0]["status"] == "pending"
    after = (await live_client.get(f"/api/projects/{pid}/graph")).json()
    assert len(after["nodes"]) == len(before["nodes"])

    # 2. Review gate: approve one candidate, reject the rest; only the approved one merges,
    #    stamped with the collector as source and reviewed = true.
    approved_id = run["candidates"][0]["id"]
    res = await live_client.post(f"/api/candidates/{approved_id}/approve")
    assert res.status_code == 200, res.text
    merged_node_id = res.json()["merged_node_id"]
    rest = [c["id"] for c in run["candidates"][1:]]
    if rest:
        res = await live_client.post(f"/api/projects/{pid}/candidates/reject", json={"ids": rest})
        assert res.status_code == 200, res.text
    node = (await live_client.get(f"/api/nodes/{merged_node_id}")).json()
    assert node["source"] == "crtsh" and node["reviewed"] is True
    graph = (await live_client.get(f"/api/projects/{pid}/graph")).json()
    assert len(graph["nodes"]) == len(before["nodes"]) + 1
    assert (await live_client.get(f"/api/projects/{pid}/candidates/count")).json() == {"pending": 0}

    # 3. Analysis: the three validation criteria hold on the fixture.
    res = await live_client.post(f"/api/projects/{pid}/analysis", json={"weighted": True})
    assert res.status_code == 200, res.text
    result = res.json()
    assert result["all_passed"] is True
    by_key = {c["key"]: c for c in result["criteria"]}
    assert by_key["axis_coverage"]["value"] >= 3
    assert result["path"]["found"] and result["path"]["hops"] >= 1
    assert any(e["impact"] in {"CRITICO", "ALTO"} for e in result["high_impact_edges"])

    # 4. Report in the three formats and both languages.
    for fmt, needle in (("md", "# "), ("html", "<!doctype html>"), ("json", '"format"')):
        for locale in ("pt", "en"):
            res = await live_client.get(f"/api/projects/{pid}/report?format={fmt}&locale={locale}")
            assert res.status_code == 200, res.text
            assert needle.lower() in res.text[:400].lower(), (fmt, locale)
    report = json.loads((await live_client.get(f"/api/projects/{pid}/report?format=json")).text)
    assert report["analysis"]["all_passed"] is True

    # 5. Export -> import as a new project -> same graph size and same verdict.
    res = await live_client.get(f"/api/projects/{pid}/export")
    assert res.status_code == 200
    payload = res.json()
    res = await live_client.post("/api/projects/import?name=smoke%20copy", json=payload)
    assert res.status_code == 201, res.text
    imported = res.json()
    smoke_project["created"].append(imported["project"]["id"])
    assert imported["nodes_created"] == len(graph["nodes"])
    assert imported["edges_created"] == len(graph["edges"])
    res = await live_client.post(
        f"/api/projects/{imported['project']['id']}/analysis", json={"weighted": False}
    )
    assert res.status_code == 200, res.text
    copy = res.json()
    assert [c["passed"] for c in copy["criteria"]] == [c["passed"] for c in result["criteria"]]
    assert copy["path"]["hops"] == result["path"]["hops"]
