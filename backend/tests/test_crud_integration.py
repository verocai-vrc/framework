"""CRUD through the HTTP layer against the live Neo4j (skips when it is down)."""

from __future__ import annotations


async def _node(client, pid, label, attrs, **extra):
    res = await client.post(
        f"/api/projects/{pid}/nodes", json={"label": label, "attrs": attrs, **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_project_has_organizacao_anchor(live_client, project):
    assert project["root_node_id"]
    assert project["node_count"] == 1
    res = await live_client.get(f"/api/nodes/{project['root_node_id']}")
    assert res.status_code == 200
    root = res.json()
    assert root["label"] == "Organizacao" and root["axis"] == "ORG" and root["layer"] is None
    assert (
        root["title"] == "Example Org" and root["source"] == "manual" and root["reviewed"] is True
    )


async def test_typed_nodes_and_valid_edges_round_trip(live_client, project):
    pid = project["id"]
    dom = await _node(
        live_client, pid, "Dominio", {"name": "vpn.example.test"}, notes="# VPN\nseed"
    )
    ip = await _node(live_client, pid, "Endereco_IP", {"address": "192.0.2.10"})
    svc = await _node(live_client, pid, "Servico", {"port": 443, "service": "SSL VPN"})
    assert dom["label_display"] == "Domínio" and dom["attrs"]["environment"] == "production"
    assert svc["attrs"]["remote_auth"] is True and svc["title"] == "SSL VPN :443"

    for src, rel, dst in (
        (dom, "RESOLVE_PARA", ip),
        (ip, "EXPOE", svc),
        (dom, "PERTENCE_A", {"id": project["root_node_id"]}),
    ):
        res = await live_client.post(
            f"/api/projects/{pid}/edges",
            json={"source_id": src["id"], "target_id": dst["id"], "rel": rel},
        )
        assert res.status_code == 201, res.text
        edge = res.json()
        assert (
            edge["source"] == "manual"
            and edge["reviewed"] is True
            and edge["collected_at"].endswith("Z")
        )

    graph = (await live_client.get(f"/api/projects/{pid}/graph")).json()
    assert {n["id"] for n in graph["nodes"]} == {
        project["root_node_id"],
        dom["id"],
        ip["id"],
        svc["id"],
    }
    assert sorted(e["rel"] for e in graph["edges"]) == ["EXPOE", "PERTENCE_A", "RESOLVE_PARA"]
    by_rel = {e["rel"]: e for e in graph["edges"]}
    # ORG is the anchor, not a validation axis: anchoring edges never cross axes.
    assert by_rel["PERTENCE_A"]["cross_axis"] is False
    assert by_rel["RESOLVE_PARA"]["cross_axis"] is False
    # A second read is identical: what the UI reloads is exactly what Neo4j holds.
    assert (await live_client.get(f"/api/projects/{pid}/graph")).json() == graph
    assert (await live_client.get(f"/api/nodes/{dom['id']}")).json()["notes"] == "# VPN\nseed"


async def test_invalid_edge_is_refused_with_hint(live_client, project):
    pid = project["id"]
    dom = await _node(live_client, pid, "Dominio", {"name": "a.example.test"})
    ip = await _node(live_client, pid, "Endereco_IP", {"address": "192.0.2.11"})
    res = await live_client.post(
        f"/api/projects/{pid}/edges",
        json={"source_id": ip["id"], "target_id": dom["id"], "rel": "RESOLVE_PARA"},
    )
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == "error.invalid_edge"
    assert body["reverse_allowed"] == ["RESOLVE_PARA"]
    assert "opposite direction" in body["detail"]
    assert (await live_client.get(f"/api/projects/{pid}/edges")).json() == []

    res = await live_client.post(
        f"/api/projects/{pid}/edges",
        json={"source_id": dom["id"], "target_id": ip["id"], "rel": "EXPOE"},
    )
    assert res.status_code == 422 and res.json()["allowed"] == ["RESOLVE_PARA"]

    res = await live_client.post(
        f"/api/projects/{pid}/edges",
        json={"source_id": dom["id"], "target_id": dom["id"], "rel": "RESOLVE_PARA"},
    )
    assert res.status_code == 422


async def test_duplicate_edge_conflicts(live_client, project):
    pid = project["id"]
    dom = await _node(live_client, pid, "Dominio", {"name": "b.example.test"})
    ip = await _node(live_client, pid, "Endereco_IP", {"address": "192.0.2.12"})
    payload = {"source_id": dom["id"], "target_id": ip["id"], "rel": "RESOLVE_PARA"}
    assert (await live_client.post(f"/api/projects/{pid}/edges", json=payload)).status_code == 201
    assert (await live_client.post(f"/api/projects/{pid}/edges", json=payload)).status_code == 409


async def test_update_and_delete(live_client, project):
    pid = project["id"]
    sw = await _node(live_client, pid, "Software", {"product": "FortiOS", "version": "6.0"})
    assert sw["title"] == "FortiOS 6.0" and sw["layer"] == "TI"
    res = await live_client.patch(
        f"/api/nodes/{sw['id']}",
        json={
            "attrs": {"product": "FortiOS", "version": "6.0.4"},
            "layer": "TO",
            "metadata": {"eol": "yes"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "FortiOS 6.0.4"  # derived title follows the attributes
    assert body["layer"] == "TO" and body["metadata"] == {"eol": "yes"}
    assert body["updated_at"] >= body["created_at"]

    res = await live_client.patch(f"/api/nodes/{sw['id']}", json={"title": "Custom"})
    assert res.json()["title"] == "Custom"
    res = await live_client.patch(
        f"/api/nodes/{sw['id']}", json={"attrs": {"product": "FortiOS", "version": "7"}}
    )
    assert res.json()["title"] == "Custom"  # explicit titles are kept

    cve = await _node(live_client, pid, "CVE", {"cve_id": "CVE-2018-13379", "cvss": 9.8})
    res = await live_client.post(
        f"/api/projects/{pid}/edges",
        json={"source_id": sw["id"], "target_id": cve["id"], "rel": "POSSUI_VULNERABILIDADE"},
    )
    edge = res.json()
    res = await live_client.patch(
        f"/api/edges/{edge['id']}", json={"impact": "CRITICO", "weight": 2.5}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["impact"] == "CRITICO" and body["impact_manual"] is True and body["weight"] == 2.5
    # Clearing the override hands the field back to the risk engine.
    res = await live_client.patch(f"/api/edges/{edge['id']}", json={"impact_manual": False})
    assert res.json()["impact"] is None and res.json()["impact_manual"] is False

    assert (await live_client.delete(f"/api/edges/{edge['id']}")).status_code == 204
    assert (await live_client.delete(f"/api/edges/{edge['id']}")).status_code == 404
    assert (await live_client.delete(f"/api/nodes/{sw['id']}")).status_code == 204
    assert (await live_client.get(f"/api/nodes/{sw['id']}")).status_code == 404

    res = await live_client.post(
        f"/api/projects/{pid}/nodes", json={"label": "CVE", "attrs": {"cve_id": "nope"}}
    )
    assert res.status_code == 422


async def test_project_delete_removes_everything(live_client):
    res = await live_client.post("/api/projects", json={"name": "tmp", "org_name": "Tmp"})
    pid = res.json()["id"]
    await _node(live_client, pid, "Fornecedor", {"name": "ACME"})
    assert (await live_client.get(f"/api/projects/{pid}")).json()["node_count"] == 2
    assert (await live_client.delete(f"/api/projects/{pid}")).status_code == 204
    assert (await live_client.get(f"/api/projects/{pid}")).status_code == 404
    assert (await live_client.get(f"/api/projects/{pid}/graph")).status_code == 404
