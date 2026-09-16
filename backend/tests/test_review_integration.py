"""collect -> stage -> review -> merge, over recorded HTTP responses and the live Neo4j."""

from __future__ import annotations


async def _node(client, pid, label, attrs, **extra):
    res = await client.post(
        f"/api/projects/{pid}/nodes", json={"label": label, "attrs": attrs, **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _run(client, pid, name, **body):
    res = await client.post(f"/api/projects/{pid}/collectors/{name}/run", json=body)
    assert res.status_code == 200, res.text
    return res.json()


async def test_collectors_listing_reports_guard_state(client):
    res = await client.get("/api/collectors")
    assert res.status_code == 200
    by_name = {c["name"]: c for c in res.json()}
    assert set(by_name) == {"crtsh", "rdap", "bgp", "nvd", "active_probe_example"}
    for name in ("crtsh", "rdap", "bgp", "nvd"):
        assert by_name[name]["interacts_with_target"] is False and by_name[name]["allowed"] is True
    assert by_name["active_probe_example"]["interacts_with_target"] is True
    assert by_name["active_probe_example"]["allowed"] is False
    assert (
        by_name["crtsh"]["source_family"] == "CT logs"
        and by_name["nvd"]["input_label"] == "Software"
    )


async def test_active_collector_is_refused_by_guard_before_running(
    live_client, project, mocked_sources
):
    res = await live_client.post(
        f"/api/projects/{project['id']}/collectors/active_probe_example/run",
        json={"seed": "example.test"},
    )
    assert res.status_code == 403
    body = res.json()
    assert body["code"] == "error.passive_guard" and body["collector"] == "active_probe_example"
    assert "PASSIVE_ONLY" in body["detail"]
    assert (await live_client.get(f"/api/projects/{project['id']}/candidates")).json() == []
    assert not mocked_sources.calls  # nothing left the machine


async def test_crtsh_stages_candidates_and_merge_on_approve(live_client, mocked_sources):
    res = await live_client.post(
        "/api/projects", json={"name": "ct", "org_name": "IANA (test)", "seed_domain": "iana.org"}
    )
    proj = res.json()
    pid = proj["id"]
    try:
        report = await _run(live_client, pid, "crtsh")  # seed defaults to the project seed domain
        assert report["seed"] == "iana.org" and report["findings"] == report["staged"] >= 8
        assert report["skipped_pending"] == 0 and report["skipped_in_graph"] == 0
        # Nothing touched the live graph.
        assert (await live_client.get(f"/api/projects/{pid}/graph")).json()["nodes"][0][
            "id"
        ] == proj["root_node_id"]
        assert len((await live_client.get(f"/api/projects/{pid}/graph")).json()["nodes"]) == 1

        pending = (await live_client.get(f"/api/projects/{pid}/candidates?status=pending")).json()
        assert len(pending) == report["staged"]
        assert (await live_client.get(f"/api/projects/{pid}/candidates/count")).json() == {
            "pending": len(pending)
        }
        c = next(x for x in pending if x["title"] == "www.iana.org")
        assert (
            c["collector"] == "crtsh" and c["source"] == "crtsh" and c["source_family"] == "CT logs"
        )
        assert (
            c["collected_at"].endswith("Z") and c["status"] == "pending" and c["label"] == "Dominio"
        )
        assert c["attrs"] == {"name": "www.iana.org"}
        assert c["metadata"]["ct_certificates"].isdigit() and "cert(s)" in c["evidence"]
        assert c["edges"] == [
            {"rel": "PERTENCE_A", "other_id": proj["root_node_id"], "direction": "out"}
        ]

        # Re-running dedupes against pending candidates (and uses the response cache).
        again = await _run(live_client, pid, "crtsh")
        assert again["staged"] == 0 and again["skipped_pending"] == report["staged"]

        # Edit one candidate before approving it.
        res = await live_client.patch(
            f"/api/candidates/{c['id']}",
            json={"notes": "checked by analyst", "metadata": {**c["metadata"], "note": "x"}},
        )
        assert res.status_code == 200 and res.json()["notes"] == "checked by analyst"

        # Approve a subset, reject one, leave the rest pending.
        subset = [x["id"] for x in pending if x["title"] in {"www.iana.org", "data.iana.org"}]
        rejected = next(x["id"] for x in pending if x["title"] == "ftp.iana.org")
        res = await live_client.post(
            f"/api/projects/{pid}/candidates/approve", json={"ids": subset}
        )
        assert res.status_code == 200
        approved = res.json()
        assert all(
            a["status"] == "approved" and a["merged_node_id"] and a["warnings"] == []
            for a in approved
        )
        res = await live_client.post(f"/api/candidates/{rejected}/reject")
        assert res.status_code == 200 and res.json()["status"] == "rejected"
        assert (await live_client.post(f"/api/candidates/{rejected}/approve")).status_code == 409

        graph = (await live_client.get(f"/api/projects/{pid}/graph")).json()
        merged = {n["title"]: n for n in graph["nodes"] if n["label"] == "Dominio"}
        assert set(merged) == {"www.iana.org", "data.iana.org"}  # only the approved subset
        www = merged["www.iana.org"]
        assert (
            www["reviewed"] is True
            and www["source"] == "crtsh"
            and www["collected_at"] == c["collected_at"]
        )
        assert www["notes"] == "checked by analyst" and www["metadata"]["note"] == "x"
        assert www["attrs"]["environment"] == "production"
        edges = [
            (e["source_id"], e["rel"], e["target_id"], e["source"], e["reviewed"])
            for e in graph["edges"]
        ]
        assert (www["id"], "PERTENCE_A", proj["root_node_id"], "crtsh", True) in edges
        assert len(graph["edges"]) == 2

        counts = {
            s: len((await live_client.get(f"/api/projects/{pid}/candidates?status={s}")).json())
            for s in ("pending", "approved", "rejected")
        }
        assert counts == {"pending": report["staged"] - 3, "approved": 2, "rejected": 1}
        # A later run skips what is already in the graph.
        (await live_client.delete(f"/api/projects/{pid}/candidates?status=rejected"))
        await live_client.post(
            f"/api/projects/{pid}/candidates/reject",
            json={
                "ids": [
                    x["id"]
                    for x in pending
                    if x["status"] == "pending" and x["id"] not in subset and x["id"] != rejected
                ]
            },
        )
        await live_client.delete(f"/api/projects/{pid}/candidates?status=rejected")
        third = await _run(live_client, pid, "crtsh")
        assert third["skipped_in_graph"] == 2 and third["skipped_pending"] == 0
    finally:
        await live_client.delete(f"/api/projects/{pid}")


async def test_nvd_rdap_bgp_findings(live_client, project, mocked_sources):
    pid = project["id"]
    sw = await _node(
        live_client,
        pid,
        "Software",
        {"product": "FortiOS", "version": "6.0.4", "vendor": "Fortinet"},
        layer="TO",
    )
    ip = await _node(live_client, pid, "Endereco_IP", {"address": "192.0.43.8"})

    # NVD: needs a Software node; CVEs attach with POSSUI_VULNERABILIDADE (Software -> CVE).
    res = await live_client.post(
        f"/api/projects/{pid}/collectors/nvd/run", json={"seed": "FortiOS"}
    )
    assert res.status_code == 422 and res.json()["code"] == "error.collector_input"
    report = await _run(live_client, pid, "nvd", node_id=sw["id"])
    assert report["staged"] == 3
    cves = {c["title"]: c for c in report["candidates"]}
    c = cves["CVE-2018-13379"]
    assert c["attrs"]["cvss"] == 9.1 and c["attrs"]["severity"] == "CRITICAL" and c["layer"] == "TO"
    assert c["edges"] == [
        {"rel": "POSSUI_VULNERABILIDADE", "other_id": sw["id"], "direction": "in"}
    ]
    assert c["metadata"]["nvd_query"].startswith("virtualMatchString=")
    res = await live_client.post(f"/api/candidates/{c['id']}/approve")
    assert res.status_code == 200
    graph = (await live_client.get(f"/api/projects/{pid}/graph")).json()
    cve = next(n for n in graph["nodes"] if n["label"] == "CVE")
    assert (
        cve["attrs"]["cve_id"] == "CVE-2018-13379"
        and cve["layer"] == "TO"
        and cve["source"] == "nvd"
    )
    assert any(
        e["source_id"] == sw["id"]
        and e["target_id"] == cve["id"]
        and e["rel"] == "POSSUI_VULNERABILIDADE"
        for e in graph["edges"]
    )

    # RDAP on the IP node: enrichment + registrant as Fornecedor with MANTEM_ACESSO_A -> IP.
    report = await _run(live_client, pid, "rdap", node_id=ip["id"])
    kinds = {c["kind"]: c for c in report["candidates"]}
    assert set(kinds) == {"node_update", "node"}
    assert (
        kinds["node_update"]["target_id"] == ip["id"]
        and kinds["node_update"]["metadata"]["rdap_handle"] == "NET-192-0-32-0-1"
    )
    assert kinds["node"]["label"] == "Fornecedor" and kinds["node"]["attrs"]["name"] == "ICANN"
    assert kinds["node"]["edges"] == [
        {"rel": "MANTEM_ACESSO_A", "other_id": ip["id"], "direction": "out"}
    ]
    for c in report["candidates"]:
        assert (await live_client.post(f"/api/candidates/{c['id']}/approve")).status_code == 200
    ip_now = (await live_client.get(f"/api/nodes/{ip['id']}")).json()
    assert (
        ip_now["metadata"]["rdap_network"] == "ICANN"
        and ip_now["metadata"]["rdap_range"] == "192.0.32.0 - 192.0.47.255"
    )
    assert ip_now["source"] == "manual"  # enrichment keeps the node's own provenance
    graph = (await live_client.get(f"/api/projects/{pid}/graph")).json()
    icann = next(n for n in graph["nodes"] if n["label"] == "Fornecedor")
    assert icann["source"] == "rdap" and icann["reviewed"] is True
    assert any(
        e["source_id"] == icann["id"]
        and e["target_id"] == ip["id"]
        and e["rel"] == "MANTEM_ACESSO_A"
        for e in graph["edges"]
    )

    # BGP on the same IP: ASN enrichment; holders become Fornecedor findings (ICANN-LAX, ICANN-DC).
    report = await _run(live_client, pid, "bgp", node_id=ip["id"])
    upd = next(c for c in report["candidates"] if c["kind"] == "node_update")
    assert (
        upd["attrs"] == {"asn": 40528, "asn_name": "ICANN-LAX - ICANN"}
        and upd["metadata"]["bgp_prefix"] == "192.0.43.0/24"
    )
    holders_candidates = [c for c in report["candidates"] if c["kind"] == "node"]
    assert sorted(c["attrs"]["name"] for c in holders_candidates) == [
        "ICANN-DC - ICANN",
        "ICANN-LAX - ICANN",
    ]
    assert (await live_client.post(f"/api/candidates/{upd['id']}/approve")).status_code == 200
    ip_now = (await live_client.get(f"/api/nodes/{ip['id']}")).json()
    assert ip_now["attrs"]["asn"] == 40528 and ip_now["attrs"]["asn_name"] == "ICANN-LAX - ICANN"

    # BGP by ASN seed: the holder is still a pending candidate, so the finding is deduped.
    report = await _run(live_client, pid, "bgp", seed="AS16876")
    assert report["staged"] == 0 and report["skipped_pending"] == 1
    # Approve the holder, then the ASN run enriches it with the announced prefixes and links
    # every graph address inside those prefixes (192.0.43.8 is in 192.0.43.0/24).
    dc = next(c for c in holders_candidates if c["attrs"]["name"] == "ICANN-DC - ICANN")
    assert (await live_client.post(f"/api/candidates/{dc['id']}/approve")).status_code == 200
    report = await _run(live_client, pid, "bgp", seed="AS16876")
    assert report["staged"] == 1
    c = report["candidates"][0]
    assert c["kind"] == "node_update" and c["metadata"]["bgp_announced_prefixes"] == "9"
    assert c["edges"] == [{"rel": "MANTEM_ACESSO_A", "other_id": ip["id"], "direction": "out"}]
    res = await live_client.post(f"/api/candidates/{c['id']}/approve")
    assert res.status_code == 200
    assert "already existed" in " ".join(res.json()["warnings"])  # edge came with the holder
    dc_node = (
        await live_client.get(f"/api/nodes/{dc['id'] and res.json()['merged_node_id']}")
    ).json()
    assert dc_node["metadata"]["bgp_announced_prefixes"] == "9" and dc_node["attrs"]["asn"] == 16876

    # Guard is applied per run, unaffected by earlier passive runs.
    assert (
        await live_client.post(f"/api/projects/{pid}/collectors/active_probe_example/run", json={})
    ).status_code == 403


async def test_candidate_edit_validates_attrs(live_client, mocked_sources):
    res = await live_client.post(
        "/api/projects", json={"name": "ct2", "org_name": "IANA", "seed_domain": "iana.org"}
    )
    pid = res.json()["id"]
    try:
        report = await _run(live_client, pid, "crtsh")
        c = report["candidates"][0]
        res = await live_client.patch(
            f"/api/candidates/{c['id']}", json={"attrs": {"name": "not a domain"}}
        )
        assert res.status_code == 422
        res = await live_client.patch(
            f"/api/candidates/{c['id']}",
            json={"attrs": {"name": "renamed.iana.org"}, "title": "Renamed"},
        )
        assert res.status_code == 200 and res.json()["title"] == "Renamed"
        res = await live_client.post(f"/api/candidates/{c['id']}/approve")
        assert res.status_code == 200
        node = (await live_client.get(f"/api/nodes/{res.json()['merged_node_id']}")).json()
        assert node["attrs"]["name"] == "renamed.iana.org" and node["title"] == "Renamed"
        assert (
            await live_client.patch(f"/api/candidates/{c['id']}", json={"title": "x"})
        ).status_code == 409
    finally:
        await live_client.delete(f"/api/projects/{pid}")


async def test_empty_result_and_missing_seed(live_client, project, mocked_sources):
    pid = project["id"]
    report = await _run(live_client, pid, "crtsh", seed="nothing.test")
    assert report["findings"] == 0 and report["staged"] == 0
    res = await live_client.post("/api/projects", json={"name": "no seed"})
    npid = res.json()["id"]
    try:
        res = await live_client.post(f"/api/projects/{npid}/collectors/crtsh/run", json={})
        assert res.status_code == 422 and res.json()["code"] == "error.collector_input"
        res = await live_client.post(f"/api/projects/{npid}/collectors/nope/run", json={})
        assert res.status_code == 404
    finally:
        await live_client.delete(f"/api/projects/{npid}")
