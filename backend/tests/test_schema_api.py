from __future__ import annotations


async def test_schema_endpoint_describes_palette(client):
    res = await client.get("/api/schema")
    assert res.status_code == 200
    body = res.json()
    labels = {item["label"]: item for item in body["labels"]}
    assert len(labels) == 11
    assert labels["Endereco_IP"]["display"] == {"pt": "Endereço IP", "en": "IP address"}
    fields = {f["name"]: f for f in labels["Servico"]["fields"]}
    assert fields["port"]["required"] is True and fields["port"]["type"] == "integer"
    assert fields["remote_auth"]["required"] is False
    env = {f["name"]: f for f in labels["Dominio"]["fields"]}["environment"]
    assert "staging" in env["choices"]
    rels = {r["rel"]: r["extension"] for r in body["rel_types"]}
    assert rels["RESOLVE_PARA"] is False and rels["PIVOT_LATERAL"] is True
    assert ["Dominio", "RESOLVE_PARA", "Endereco_IP"] in body["allowed_edges"]
    assert body["validation_axes"] == ["DIGITAL", "ECOSSISTEMA", "FISICO", "HUMANO"]
