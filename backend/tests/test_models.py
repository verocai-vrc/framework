from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.db.schema import Axis, Layer, NodeLabel, RelType
from app.graph.crud import check_edge_allowed, cross_axis, node_props
from app.i18n import t
from app.models.nodes import NodeCreate, validate_attrs


@pytest.mark.parametrize(
    ("name", "env"),
    [
        ("www.example.test", "production"),
        ("staging.example.test", "staging"),
        ("hml.example.test", "homolog"),
        ("api-dev.example.test", "dev"),  # hyphenated tokens count
        ("example.test", "production"),  # the TLD never counts
        ("devices.example.test", "production"),  # only whole tokens match
        ("dev.api.example.test", "dev"),
        ("qa.example.test", "test"),
    ],
)
def test_dominio_environment_is_inferred_from_name(name, env):
    attrs = validate_attrs(NodeLabel.DOMINIO, {"name": name})
    assert attrs.environment == env


def test_dominio_environment_explicit_wins():
    attrs = validate_attrs(
        NodeLabel.DOMINIO, {"name": "staging.example.test", "environment": "production"}
    )
    assert attrs.environment == "production"


def test_dominio_name_is_normalised_and_validated():
    assert (
        validate_attrs(NodeLabel.DOMINIO, {"name": " WWW.Example.TEST. "}).name
        == "www.example.test"
    )
    with pytest.raises(ValidationError):
        validate_attrs(NodeLabel.DOMINIO, {"name": "not a domain"})


@pytest.mark.parametrize(
    ("attrs", "remote_auth"),
    [
        ({"port": 22}, True),
        ({"port": 443, "service": "https"}, False),
        ({"port": 443, "service": "SSL VPN"}, True),
        ({"port": 502, "service": "modbus"}, False),
        ({"port": 3389}, True),
        ({"port": 80, "remote_auth": True}, True),
    ],
)
def test_servico_remote_auth_inference(attrs, remote_auth):
    assert validate_attrs(NodeLabel.SERVICO, attrs).remote_auth is remote_auth


def test_ip_and_cve_validation():
    assert validate_attrs(NodeLabel.ENDERECO_IP, {"address": "192.0.2.10"}).address == "192.0.2.10"
    assert (
        validate_attrs(NodeLabel.ENDERECO_IP, {"address": "2001:db8::1"}).address == "2001:db8::1"
    )
    with pytest.raises(ValidationError):
        validate_attrs(NodeLabel.ENDERECO_IP, {"address": "999.1.1.1"})
    assert validate_attrs(NodeLabel.CVE, {"cve_id": "cve-2018-13379"}).cve_id == "CVE-2018-13379"
    with pytest.raises(ValidationError):
        validate_attrs(NodeLabel.CVE, {"cve_id": "2018-13379"})


def test_unknown_attr_is_rejected():
    with pytest.raises(ValidationError):
        validate_attrs(NodeLabel.FORNECEDOR, {"name": "ACME", "bogus": 1})


def test_node_props_stamp_envelope_and_manual_provenance():
    props = node_props(
        "proj-1", NodeCreate(label=NodeLabel.SERVICO, attrs={"port": 443, "service": "https"})
    )
    assert props["project_id"] == "proj-1"
    assert props["axis"] == "DIGITAL" and props["layer"] == "TI"
    assert props["label_display"] == "Serviço"
    assert props["title"] == "https :443"
    assert props["source"] == "manual" and props["reviewed"] is True
    assert props["collected_at"].endswith("Z")
    assert props["port"] == 443 and props["remote_auth"] is False


def test_layer_must_be_valid_for_label():
    NodeCreate(label=NodeLabel.SOFTWARE, attrs={"product": "FortiOS"}, layer=Layer.TO)
    with pytest.raises(ValidationError):
        NodeCreate(label=NodeLabel.DOMINIO, attrs={"name": "a.test"}, layer=Layer.TO)
    props = node_props("p", NodeCreate(label=NodeLabel.FUNCIONARIO, attrs={"name": "Ana"}))
    assert "layer" not in props


def test_cross_axis_rules():
    assert cross_axis(Axis.HUMANO, None, Axis.DIGITAL, Layer.TI)
    assert not cross_axis(Axis.DIGITAL, Layer.TI, Axis.DIGITAL, Layer.TI)
    assert cross_axis(Axis.DIGITAL, Layer.TI, Axis.DIGITAL, Layer.TO)  # TI -> TO counts
    assert not cross_axis(Axis.HUMANO, None, Axis.HUMANO, None)


def _fake_node(label: NodeLabel):
    from app.db.schema import LABEL_SPECS
    from app.models.nodes import NodeOut

    spec = LABEL_SPECS[label]
    return NodeOut(
        id="x", project_id="p", label=label, label_display=spec.display_pt, axis=spec.axis,
        layer=spec.default_layer, title="t", description="", notes="", attrs={}, metadata={},
        source="manual", collected_at="", reviewed=True, created_at="", updated_at="",
    )  # fmt: skip


def test_check_edge_allowed_gives_hint():
    from app.errors import InvalidEdge

    check_edge_allowed(
        _fake_node(NodeLabel.DOMINIO), RelType.RESOLVE_PARA, _fake_node(NodeLabel.ENDERECO_IP)
    )
    with pytest.raises(InvalidEdge) as exc:
        check_edge_allowed(
            _fake_node(NodeLabel.ENDERECO_IP), RelType.RESOLVE_PARA, _fake_node(NodeLabel.DOMINIO)
        )
    assert exc.value.extra["allowed"] == []
    assert exc.value.extra["reverse_allowed"] == ["RESOLVE_PARA"]
    msg = t(exc.value.key, "en", **exc.value.extra)
    assert msg == (
        "Endereco_IP → Dominio cannot use RESOLVE_PARA. "
        "The opposite direction allows: RESOLVE_PARA."
    )
    msg_pt = t(exc.value.key, "pt", **exc.value.extra)
    assert msg_pt.startswith("Endereco_IP → Dominio não pode usar RESOLVE_PARA.")

    with pytest.raises(InvalidEdge) as exc:
        check_edge_allowed(
            _fake_node(NodeLabel.DOMINIO), RelType.EXPOE, _fake_node(NodeLabel.ORGANIZACAO)
        )
    assert t(exc.value.key, "en", **exc.value.extra).endswith("Allowed here: PERTENCE_A.")
