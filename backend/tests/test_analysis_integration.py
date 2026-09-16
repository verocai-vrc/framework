"""Sprint 4 acceptance test against the live Neo4j: the fixture project satisfies all three
criteria, the path variants agree with the engineered graph, overrides are respected, and
the report renders in all three formats."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from app.analysis.paths import gds_available
from app.graph.fixture import FIXTURE_EDGES, FIXTURE_NODES, seed_fixture


@pytest.fixture
async def fixture_project(neo4j, live_client) -> AsyncIterator[dict]:
    project = await seed_fixture(neo4j, "pytest fixture")
    try:
        yield project.model_dump()
    finally:
        await live_client.delete(f"/api/projects/{project.id}")


async def test_fixture_meets_all_three_criteria(live_client, fixture_project):
    pid = fixture_project["id"]
    assert fixture_project["node_count"] == len(FIXTURE_NODES) + 1  # + Organizacao anchor
    assert fixture_project["edge_count"] == len(FIXTURE_EDGES)

    res = await live_client.post(f"/api/projects/{pid}/analysis", json={"weighted": False})
    assert res.status_code == 200, res.text
    r = res.json()
    assert r["all_passed"] is True
    c1, c2, c3 = r["criteria"]
    assert c1["value"] == 4 and c1["passed"] and c1["threshold"] == 3
    assert set(r["axes_present"]) == {"DIGITAL", "HUMANO", "FISICO", "ECOSSISTEMA"}
    assert c2["passed"] and r["path"]["found"] and r["path"]["method"] == "shortestPath"
    # Org <- scada domain -> IP -> ssh -> PLC
    assert r["path"]["hops"] == 4 and len(r["path"]["edges"]) == 4
    titles = [h["title"] for h in r["path"]["nodes"]]
    assert titles[0] == "Example Utility Co." and titles[-1] == "Example Automation PLC-1000"
    assert r["path"]["nodes"][1]["label"] == "Dominio"  # digital entry policy
    assert c3["passed"] and c3["value"] == 5
    rules = {e["rule"] for e in r["high_impact_edges"]}
    assert rules == {"T8.1", "T8.2", "T8.3", "T8.4", "T8.5"}
    assert {e["rule"] for e in r["classified_edges"]} == rules | {"T8.6"}
    assert r["high_impact_edges"][0]["risk_level"] == "CRITICO"
    assert [e["rel"] for e in r["unclassified_cross_axis"]] == ["ACESSA_DIRETAMENTE"]
    assert r["weighted_path"] is None and r["centrality"]

    # The engine stamped the edges: the graph now carries impact/probability/risk_level.
    graph = (await live_client.get(f"/api/projects/{pid}/graph")).json()
    stamped = {e["rel"]: e for e in graph["edges"] if e["impact"]}
    assert stamped["VIABILIZA_ACESSO_A"]["impact"] == "CRITICO"
    assert stamped["VIABILIZA_ACESSO_A"]["risk_level"] == "CRITICO"
    assert stamped["VIABILIZA_ACESSO_A"]["impact_manual"] is False
    assert stamped["MANTEM_ACESSO_A"]["probability"] == "MEDIA"


async def test_entry_policy_any_allows_human_and_physical_entry(live_client, fixture_project):
    pid = fixture_project["id"]
    r = (
        await live_client.post(
            f"/api/projects/{pid}/analysis?entry=any", json={"weighted": False, "centrality": False}
        )
    ).json()
    assert r["path"]["hops"] == 2 and r["centrality_method"] == "none"
    assert r["path"]["nodes"][1]["axis"] in {"HUMANO", "FISICO"}


async def test_weighted_path_prefers_cheaper_route(neo4j, live_client, fixture_project):
    if not await gds_available(neo4j):
        pytest.skip("GDS plugin not installed")
    pid = fixture_project["id"]
    r = (await live_client.post(f"/api/projects/{pid}/analysis", json={"top_n": 3})).json()
    assert r["gds_available"] is True
    w = r["weighted_path"]
    assert w["found"] and w["method"] == "gds.dijkstra"
    # 5 hops through the VPN pivot at effort 5 beats the 4-hop route with the weight-5 hop.
    assert w["hops"] == 5 and w["cost"] == 5.0 and r["path"]["cost"] == 8.0
    assert [s["rel"] for s in w["edges"]] == [
        "PERTENCE_A", "RESOLVE_PARA", "EXPOE", "PIVOT_LATERAL", "ACESSA_DIRETAMENTE",
    ]  # fmt: skip
    assert r["centrality_method"] == "gds" and len(r["centrality"]) == 3
    assert r["centrality"][0]["betweenness"] is not None
    # No in-memory graph left behind.
    left = await neo4j.run("CALL gds.graph.list() YIELD graphName RETURN graphName")
    assert not [g["graphName"] for g in left if g["graphName"].startswith("osintree_")]


async def test_analyst_override_is_respected_and_reversible(live_client, fixture_project):
    pid = fixture_project["id"]
    graph = (await live_client.get(f"/api/projects/{pid}/graph")).json()
    supplier_edge = next(e for e in graph["edges"] if e["rel"] == "MANTEM_ACESSO_A")

    res = await live_client.patch(
        f"/api/edges/{supplier_edge['id']}", json={"impact": "BAIXO", "probability": "BAIXA"}
    )
    assert res.status_code == 200 and res.json()["impact_manual"] is True
    r = (await live_client.post(f"/api/projects/{pid}/analysis", json={"weighted": False})).json()
    assert r["criteria"][2]["value"] == 4  # T8.5 no longer counts
    mine = next(e for e in r["classified_edges"] if e["id"] == supplier_edge["id"])
    assert mine["impact"] == "BAIXO" and mine["rule"] == "T8.5" and mine["risk_level"] == "MINIMO"

    res = await live_client.patch(
        f"/api/edges/{supplier_edge['id']}",
        json={"impact_manual": False, "probability_manual": False},
    )
    assert res.json()["impact"] is None and res.json()["risk_level"] is None
    r = (await live_client.post(f"/api/projects/{pid}/analysis", json={"weighted": False})).json()
    assert r["criteria"][2]["value"] == 5


async def test_report_renders_in_three_formats(live_client, fixture_project):
    pid = fixture_project["id"]
    res = await live_client.get(f"/api/projects/{pid}/report?format=md")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/markdown")
    assert 'filename="pytest-fixture-report.md"' in res.headers["content-disposition"]
    md = res.text
    assert md.startswith("# Relatório de superfície de ataque passiva")  # report locale = pt
    assert "Os três critérios de validação foram atendidos." in md
    assert "T8.1" in md and "CVE-2018-13379" not in md.split("## Inventário")[0]

    res = await live_client.get(f"/api/projects/{pid}/report?format=html&locale=en&inline=true")
    assert res.headers["content-type"].startswith("text/html")
    assert res.headers["content-disposition"].startswith("inline")
    assert "<title>Passive attack-surface report</title>" in res.text
    assert "All three validation criteria are met." in res.text

    res = await live_client.get(f"/api/projects/{pid}/report?format=json")
    data = json.loads(res.text)
    assert data["format"] == "osintree-report/1" and data["analysis"]["all_passed"] is True
    assert len(data["graph"]["nodes"]) == fixture_project["node_count"]

    assert (await live_client.get(f"/api/projects/{pid}/report?format=pdf")).status_code == 422
    assert (await live_client.get("/api/projects/nope/report")).status_code == 404


async def test_project_without_ot_fails_criterion_two(live_client, project):
    pid = project["id"]
    r = (await live_client.post(f"/api/projects/{pid}/analysis", json={"weighted": False})).json()
    assert r["all_passed"] is False
    assert r["path"]["found"] is False and r["path"]["reason"] == "no_ot"
    assert r["criteria"][0]["value"] == 0  # only the ORG anchor: no validation axis
