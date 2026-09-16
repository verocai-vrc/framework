"""Import/export against the live Neo4j."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


async def _node(client, pid, label, attrs, **extra):
    res = await client.post(
        f"/api/projects/{pid}/nodes", json={"label": label, "attrs": attrs, **extra}
    )
    assert res.status_code == 201, res.text
    return res.json()


def _shape(graph):
    """Comparable projection of a graph: everything except project-scoped ids."""
    nodes = sorted(
        (
            n["label"],
            n["title"],
            n["notes"],
            json.dumps(n["attrs"], sort_keys=True),
            json.dumps(n["metadata"], sort_keys=True),
            n["source"],
            n["reviewed"],
            n["layer"],
        )
        for n in graph["nodes"]
    )
    by_id = {n["id"]: n["title"] for n in graph["nodes"]}
    edges = sorted(
        (
            by_id[e["source_id"]],
            e["rel"],
            by_id[e["target_id"]],
            e["impact"],
            e["weight"],
            e["notes"],
        )
        for e in graph["edges"]
    )
    return nodes, edges


async def test_typed_export_import_round_trip_is_lossless(live_client, project):
    pid = project["id"]
    dom = await _node(
        live_client,
        pid,
        "Dominio",
        {"name": "hml.example.test"},
        notes="# Notes\n\n- one\n- **two**",
        metadata={"fonte": "crt.sh"},
    )
    ip = await _node(live_client, pid, "Endereco_IP", {"address": "192.0.2.77", "asn": 64500})
    sw = await _node(
        live_client, pid, "Software", {"product": "PLC firmware", "version": "1.2"}, layer="TO"
    )
    res = await live_client.post(
        f"/api/projects/{pid}/edges",
        json={
            "source_id": dom["id"],
            "target_id": ip["id"],
            "rel": "RESOLVE_PARA",
            "impact": "ALTO",
            "weight": 3.0,
            "notes": "n",
        },
    )
    assert res.status_code == 201
    await live_client.post(
        f"/api/projects/{pid}/edges",
        json={"source_id": dom["id"], "target_id": project["root_node_id"], "rel": "PERTENCE_A"},
    )

    res = await live_client.get(f"/api/projects/{pid}/export")
    assert res.status_code == 200
    assert res.headers["content-disposition"].endswith('.osintree.json"')
    export = res.json()
    assert export["format"] == "osintree/1"
    assert len(export["nodes"]) == 4 and len(export["edges"]) == 2
    original = _shape((await live_client.get(f"/api/projects/{pid}/graph")).json())

    # "reset the database": delete the project, then import the file back.
    assert (await live_client.delete(f"/api/projects/{pid}")).status_code == 204
    res = await live_client.post("/api/projects/import", json=export)
    assert res.status_code == 201, res.text
    report = res.json()
    try:
        assert report["format"] == "osintree/1" and report["ids_remapped"] is False
        assert (
            report["nodes_created"] == 4
            and report["edges_created"] == 2
            and report["warnings"] == []
        )
        new_pid = report["project"]["id"]
        assert report["project"]["name"] == project["name"]
        assert report["project"]["org_name"] == "Example Org"
        assert report["project"]["seed_domain"] == "example.test"
        assert report["project"]["root_node_id"] == project["root_node_id"]  # ids preserved
        restored = (await live_client.get(f"/api/projects/{new_pid}/graph")).json()
        assert _shape(restored) == original
        assert {n["id"] for n in restored["nodes"]} == {n["id"] for n in export["nodes"]}
        assert {e["id"] for e in restored["edges"]} == {e["id"] for e in export["edges"]}
        # provenance survived untouched
        exp_by_id = {n["id"]: n for n in export["nodes"]}
        for n in restored["nodes"]:
            assert n["collected_at"] == exp_by_id[n["id"]]["collected_at"]
            assert n["created_at"] == exp_by_id[n["id"]]["created_at"]
        sw_restored = next(n for n in restored["nodes"] if n["id"] == sw["id"])
        assert sw_restored["layer"] == "TO"

        # Importing again while the ids exist: fresh ids, same shape, with a warning.
        res = await live_client.post("/api/projects/import?name=copy", json=export)
        assert res.status_code == 201
        copy = res.json()
        assert copy["ids_remapped"] is True and copy["project"]["name"] == "copy"
        assert copy["warnings"]
        copy_graph = (await live_client.get(f"/api/projects/{copy['project']['id']}/graph")).json()
        assert _shape(copy_graph) == original
        assert not {n["id"] for n in copy_graph["nodes"]} & {n["id"] for n in export["nodes"]}
        await live_client.delete(f"/api/projects/{copy['project']['id']}")
    finally:
        await live_client.delete(f"/api/projects/{report['project']['id']}")


async def test_legacy_reference_import(live_client):
    payload = json.loads((FIXTURES / "legacy-entidade-xyz.json").read_text(encoding="utf-8"))
    res = await live_client.post("/api/projects/import", json=payload)
    assert res.status_code == 201, res.text
    report = res.json()
    pid = report["project"]["id"]
    try:
        assert report["format"] == "legacy"
        assert report["project"]["name"] == "Entidade XYZ"
        assert report["project"]["org_name"] == "Entidade XYZ"
        assert report["project"]["seed_domain"] == "xyz-energia.example"
        # 20 legacy nodes minus 5 structural (4 Esfera + Ferramentas) = 15 typed nodes
        assert report["nodes_created"] == 15
        graph = (await live_client.get(f"/api/projects/{pid}/graph")).json()
        by_title = {n["title"]: n for n in graph["nodes"]}
        labels = {t: n["label"] for t, n in by_title.items()}
        assert labels["Entidade XYZ"] == "Organizacao"
        assert labels["scada.xyz-energia.example"] == "Dominio"
        assert labels["200.0.2.20"] == "Endereco_IP"
        assert labels["Modbus :502"] == "Servico"
        assert labels["FortiOS 6.0"] == "Software"
        assert labels["CVE-2018-13379"] == "CVE"
        assert labels["CLP Siemens S7-300"] == "Dispositivo_Industrial"
        assert labels["João M. — Eng. Automação"] == "Funcionario"
        assert labels["Credencial Vazada (João)"] == "Credencial_Vazada"
        assert labels["Subestação Central"] == "Instalacao_Fisica"
        assert labels["AutomaTI Soluções"] == "Fornecedor"
        assert "Esfera" not in " ".join(labels.values())
        assert report["project"]["root_node_id"] == by_title["Entidade XYZ"]["id"]

        # attribute inference from label + metadados
        assert by_title["Modbus :502"]["attrs"] == {
            "port": 502,
            "protocol": "Modbus TCP",
            "service": "Modbus",
            "banner": "Siemens Modbus",
            "remote_auth": False,
        }
        assert (
            by_title["FortiOS 6.0"]["attrs"]["version"] == "6.0.x"
            and by_title["FortiOS 6.0"]["attrs"]["vendor"] == "Fortinet"
        )
        assert by_title["CVE-2018-13379"]["attrs"]["cvss"] == 9.8
        assert (
            by_title["200.0.2.10"]["attrs"]["asn"] == 12345
            and by_title["200.0.2.10"]["attrs"]["asn_name"] == "XYZ Energia"
        )
        assert by_title["Subestação Central"]["attrs"]["latitude"] == -23.5505
        assert (
            by_title["Credencial Vazada (João)"]["attrs"]["email"] == "joao.m@xyz-energia.example"
        )
        assert by_title["João M. — Eng. Automação"]["attrs"]["role"] == "Engenheiro de Automação"
        assert by_title["SSL VPN :443"]["attrs"]["remote_auth"] is True
        # page fields
        assert by_title["FortiOS 6.0"]["notes"] == "- Versão EOL\n- CVE-2018-13379: CVSS 9.8"
        assert by_title["FortiOS 6.0"]["description"].startswith("Sistema operacional do FortiGate")
        assert by_title["200.0.2.10"]["metadata"] == {"fonte": "Shodan", "nome": "IP Principal"}
        assert all(n["source"] == "legacy_import" and n["reviewed"] for n in graph["nodes"])

        rels = sorted(
            (
                graph["nodes"]
                and by_title
                and (
                    next(n["title"] for n in graph["nodes"] if n["id"] == e["source_id"]),
                    e["rel"],
                    next(n["title"] for n in graph["nodes"] if n["id"] == e["target_id"]),
                )
            )
            for e in graph["edges"]
        )
        rel_set = set(rels)
        # thesis edges with accents normalised
        assert ("200.0.2.20", "EXPOE", "Modbus :502") in rel_set
        assert ("AutomaTI Soluções", "MANTEM_ACESSO_A", "200.0.2.20") in rel_set
        # attack-path extension edges from the reference
        assert ("SSL VPN :443", "PIVOT_LATERAL", "Modbus :502") in rel_set
        assert ("Modbus :502", "ACESSA_DIRETAMENTE", "CLP Siemens S7-300") in rel_set
        # anchoring replaces Esfera grouping
        assert ("xyz-energia.example", "PERTENCE_A", "Entidade XYZ") in rel_set
        assert ("Subestação Central", "PERTENCE_A", "Entidade XYZ") in rel_set
        assert ("AutomaTI Soluções", "FORNECE_PARA", "Entidade XYZ") in rel_set
        assert ("João M. — Eng. Automação", "TRABALHA_EM", "Entidade XYZ") in rel_set
        assert not any(r in {"AGRUPA", "CONTEM", "CONTÉM"} for _, r, _ in rels)
        # legacy impacto preserved
        impacts = {e["rel"]: e["impact"] for e in graph["edges"] if e["impact"]}
        assert impacts["VIABILIZA_ACESSO_A"] == "CRITICO" and impacts["MANTEM_ACESSO_A"] == "ALTO"
        assert report["warnings"] == []
    finally:
        await live_client.delete(f"/api/projects/{pid}")


async def test_legacy_unknown_type_is_imported_and_retypable(live_client):
    payload = {
        "meta": {"entidade": "Mini"},
        "nodes": [
            {"id": "o", "label": "Mini Org", "tipo": "Organização", "eixo": "central", "page": {}},
            {
                "id": "x",
                "label": "Something",
                "tipo": "Gadget",
                "eixo": "digital",
                "page": {"metadados": {"k": "v"}},
            },
            {
                "id": "bad",
                "label": "not-an-ip",
                "tipo": "Endereço_IP",
                "eixo": "digital",
                "page": {},
            },
        ],
        "edges": [{"id": "e1", "from": "o", "to": "x", "rel": "ROTA_PARA", "impacto": "Alto"}],
    }
    res = await live_client.post("/api/projects/import", json=payload)
    assert res.status_code == 201, res.text
    report = res.json()
    pid = report["project"]["id"]
    try:
        assert report["nodes_created"] == 3
        assert any("unknown type 'Gadget'" in w for w in report["warnings"])
        assert any("not-an-ip" in w and "re-type" in w for w in report["warnings"])
        assert any("ROTA_PARA" in w for w in report["warnings"])
        graph = (await live_client.get(f"/api/projects/{pid}/graph")).json()
        gadget = next(n for n in graph["nodes"] if n["title"] == "Something")
        assert gadget["label"] == "Software" and gadget["metadata"] == {
            "legacy_tipo": "Gadget",
            "k": "v",
        }

        # Re-type it: label + attrs for the new label.
        res = await live_client.patch(
            f"/api/nodes/{gadget['id']}",
            json={"label": "Dispositivo_Industrial", "attrs": {"model": "Gadget X"}},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert (
            body["label"] == "Dispositivo_Industrial"
            and body["axis"] == "DIGITAL"
            and body["layer"] == "TO"
        )
        assert body["title"] == "Gadget X" and body["label_display"] == "Dispositivo Industrial"
        assert (await live_client.get(f"/api/nodes/{gadget['id']}")).json()[
            "label"
        ] == "Dispositivo_Industrial"

        # Re-typing without attrs is rejected; re-typing that breaks an edge is rejected.
        res = await live_client.patch(f"/api/nodes/{gadget['id']}", json={"label": "CVE"})
        assert res.status_code == 422
        site = (
            next(n for n in graph["nodes"] if n["label"] == "Instalacao_Fisica")
            if any(n["label"] == "Instalacao_Fisica" for n in graph["nodes"])
            else None
        )
        assert site is None
        site = (
            await live_client.post(
                f"/api/projects/{pid}/nodes",
                json={"label": "Instalacao_Fisica", "attrs": {"name": "Plant"}},
            )
        ).json()
        res = await live_client.post(
            f"/api/projects/{pid}/edges",
            json={"source_id": site["id"], "target_id": gadget["id"], "rel": "ABRIGA"},
        )
        assert res.status_code == 201
        res = await live_client.patch(
            f"/api/nodes/{gadget['id']}", json={"label": "Software", "attrs": {"product": "x"}}
        )
        assert res.status_code == 422 and "ABRIGA" in json.dumps(res.json())
    finally:
        await live_client.delete(f"/api/projects/{pid}")


async def test_import_rejects_unknown_format(live_client):
    res = await live_client.post("/api/projects/import", json={"hello": "world"})
    assert res.status_code == 422
    assert res.json()["code"] == "error.validation"


@pytest.mark.parametrize(
    "bad",
    [{"format": "osintree/1"}, {"format": "osintree/1", "project": {}, "nodes": [], "edges": []}],
)
async def test_typed_import_validates(live_client, bad):
    res = await live_client.post("/api/projects/import", json=bad)
    assert res.status_code == 422
