"""Risk engine, criteria math and report rendering without a database."""

from __future__ import annotations

import json

from app.analysis import criteria, report, risk
from app.analysis.risk import IMPACT_RULES, RISK_MATRIX, Evidence
from app.db.schema import Axis, Layer, NodeLabel, RelType
from app.models.analysis import (
    AnalysisResult,
    Criterion,
    Inventory,
    PathHop,
    PathResult,
    PathStep,
)
from app.models.common import Impact, Probability, RiskLevel
from app.models.edges import EdgeOut, GraphOut
from app.models.nodes import NodeOut, validate_attrs
from app.models.projects import ProjectOut

# --- helpers -------------------------------------------------------------------------------

_n = 0


def node(label: NodeLabel, attrs: dict, layer: Layer | None = None, title: str = "") -> NodeOut:
    global _n
    _n += 1
    from app.db.schema import LABEL_SPECS

    spec = LABEL_SPECS[label]
    model = validate_attrs(label, attrs)
    return NodeOut(
        id=f"n{_n}",
        project_id="p",
        label=label,
        label_display=spec.display_pt,
        axis=spec.axis,
        layer=layer or spec.default_layer,
        title=title or model.default_title() or label.value,
        description="",
        notes="",
        attrs=model.model_dump(),
        metadata={},
        source="manual",
        collected_at="2026-01-01T00:00:00Z",
        reviewed=True,
        created_at="",
        updated_at="",
    )


def edge(a: NodeOut, rel: RelType, b: NodeOut, **kw) -> EdgeOut:
    global _n
    _n += 1
    from app.graph.crud import cross_axis

    return EdgeOut(
        id=f"e{_n}",
        project_id="p",
        rel=rel,
        source_id=a.id,
        target_id=b.id,
        source_label=a.label,
        target_label=b.label,
        cross_axis=cross_axis(a.axis, a.layer, b.axis, b.layer),
        notes="",
        impact=kw.get("impact"),
        impact_manual=kw.get("impact_manual", False),
        probability=kw.get("probability"),
        probability_manual=kw.get("probability_manual", False),
        risk_level=None,
        weight=kw.get("weight"),
        source="manual",
        collected_at="",
        reviewed=True,
        created_at="",
        updated_at="",
    )


def graph(nodes: list[NodeOut], edges: list[EdgeOut]) -> GraphOut:
    return GraphOut(project_id="p", nodes=nodes, edges=edges)


# --- Tabela 2 --------------------------------------------------------------------------------


def test_risk_matrix_is_the_agreed_3x3():
    assert len(RISK_MATRIX) == 9
    expected = {
        ("BAIXA", "BAIXO"): "MINIMO", ("BAIXA", "MEDIO"): "BAIXO", ("BAIXA", "ALTO"): "MEDIO",
        ("MEDIA", "BAIXO"): "BAIXO", ("MEDIA", "MEDIO"): "MEDIO", ("MEDIA", "ALTO"): "ALTO",
        ("ALTA", "BAIXO"): "MEDIO", ("ALTA", "MEDIO"): "ALTO", ("ALTA", "ALTO"): "CRITICO",
    }  # fmt: skip
    for (p, i), lvl in expected.items():
        assert risk.risk_level(Probability(p), Impact(i)) == RiskLevel(lvl)
    # CRITICO impact reads in the ALTO column
    assert risk.risk_level(Probability.ALTA, Impact.CRITICO) == RiskLevel.CRITICO
    assert risk.risk_level(Probability.BAIXA, Impact.CRITICO) == RiskLevel.MEDIO


# --- Tabela 8 --------------------------------------------------------------------------------


def test_every_tabela8_row_is_present():
    assert [r.id for r in IMPACT_RULES] == ["T8.1", "T8.2", "T8.3", "T8.4", "T8.5", "T8.6"]


def test_t81_credential_to_remote_auth_service_is_critico():
    cred = node(NodeLabel.CREDENCIAL_VAZADA, {"email": "a@x.test"})
    vpn = node(NodeLabel.SERVICO, {"port": 443, "service": "SSL VPN"})
    web = node(NodeLabel.SERVICO, {"port": 8080, "service": "http"})
    ev = Evidence.from_graph(graph([cred, vpn, web], []))
    assert risk.classify_impact(cred, vpn, ev) == (Impact.CRITICO, "T8.1")
    assert risk.classify_impact(cred, web, ev) is None  # precondition (remote-auth) unmet


def test_t82_software_with_cve_operated_by_device_is_critico():
    plc = node(NodeLabel.DISPOSITIVO_INDUSTRIAL, {"model": "PLC"})
    sw = node(NodeLabel.SOFTWARE, {"product": "HMI"}, layer=Layer.TI)
    clean = node(NodeLabel.SOFTWARE, {"product": "Other"}, layer=Layer.TI)
    cve = node(NodeLabel.CVE, {"cve_id": "CVE-2020-0001", "cvss": 5.0})
    g = graph([plc, sw, clean, cve], [edge(sw, RelType.POSSUI_VULNERABILIDADE, cve)])
    ev = Evidence.from_graph(g)
    # thesis direction is device -> software; the rule is matched in reverse
    assert risk.classify_impact(plc, sw, ev) == (Impact.CRITICO, "T8.2")
    assert risk.classify_impact(plc, clean, ev) is None
    # software on the OT layer is not the TI -> TO crossing the row describes
    firmware = node(NodeLabel.SOFTWARE, {"product": "FW"}, layer=Layer.TO)
    g2 = graph([plc, firmware, cve], [edge(firmware, RelType.POSSUI_VULNERABILIDADE, cve)])
    assert risk.classify_impact(plc, firmware, Evidence.from_graph(g2)) is None


def test_t83_to_t86():
    site = node(NodeLabel.INSTALACAO_FISICA, {"name": "Site"})
    plc = node(NodeLabel.DISPOSITIVO_INDUSTRIAL, {"model": "PLC"})
    emp = node(NodeLabel.FUNCIONARIO, {"name": "E"})
    sup = node(NodeLabel.FORNECEDOR, {"name": "S"})
    ip = node(NodeLabel.ENDERECO_IP, {"address": "192.0.2.1"})
    hml = node(NodeLabel.DOMINIO, {"name": "hml.example.test"})
    prod = node(NodeLabel.DOMINIO, {"name": "www.example.test"})
    ev = Evidence.from_graph(graph([site, plc, emp, sup, ip, hml, prod], []))
    assert risk.classify_impact(site, plc, ev) == (Impact.CRITICO, "T8.3")
    assert risk.classify_impact(emp, plc, ev) == (Impact.ALTO, "T8.4")
    assert risk.classify_impact(sup, ip, ev) == (Impact.ALTO, "T8.5")
    assert risk.classify_impact(hml, sup, ev) == (Impact.MEDIO, "T8.6")
    assert risk.classify_impact(prod, sup, ev) is None  # production domain: no row


def test_probability_heuristic_signals():
    cred = node(NodeLabel.CREDENCIAL_VAZADA, {"email": "a@x.test"})
    vpn = node(NodeLabel.SERVICO, {"port": 443, "service": "SSL VPN"})
    sw = node(NodeLabel.SOFTWARE, {"product": "FortiOS"})
    cve = node(NodeLabel.CVE, {"cve_id": "CVE-2018-13379", "cvss": 9.8})
    low = node(NodeLabel.CVE, {"cve_id": "CVE-2018-0001", "cvss": 3.1})
    dom = node(NodeLabel.DOMINIO, {"name": "www.example.test"})
    ip = node(NodeLabel.ENDERECO_IP, {"address": "192.0.2.1"})
    g = graph(
        [cred, vpn, sw, cve, low, dom, ip],
        [edge(vpn, RelType.HOSPEDA, sw), edge(sw, RelType.POSSUI_VULNERABILIDADE, cve)],
    )
    ev = Evidence.from_graph(g)
    p, why = risk.estimate_probability(cred, vpn, ev)
    assert p == Probability.ALTA and {"cve_high", "remote_auth", "leaked_credential"} <= set(why)
    assert risk.estimate_probability(dom, ip, ev) == (Probability.BAIXA, [])
    # a low CVSS still counts as a known CVE (MEDIA), not ALTA
    g2 = graph([sw, low], [edge(sw, RelType.POSSUI_VULNERABILIDADE, low)])
    assert risk.estimate_probability(sw, low, Evidence.from_graph(g2)) == (
        Probability.MEDIA,
        ["cve_known"],
    )


def test_manual_overrides_survive_assessment_and_rank_orders_by_severity():
    sup = node(NodeLabel.FORNECEDOR, {"name": "S"})
    ip = node(NodeLabel.ENDERECO_IP, {"address": "192.0.2.1"})
    dom = node(NodeLabel.DOMINIO, {"name": "www.example.test"})
    auto = edge(sup, RelType.MANTEM_ACESSO_A, ip)
    overridden = edge(
        dom, RelType.RESOLVE_PARA, ip, impact=Impact.BAIXO, impact_manual=True,
        probability=Probability.ALTA, probability_manual=True,
    )  # fmt: skip
    assessed = risk.assess_graph(graph([sup, ip, dom], [auto, overridden]))
    by_id = {r.id: r for r in assessed}
    a = by_id[auto.id]
    assert (a.impact, a.rule, a.probability, a.risk_level) == (
        Impact.ALTO, "T8.5", Probability.MEDIA, RiskLevel.ALTO,
    )  # fmt: skip
    o = by_id[overridden.id]
    assert o.impact == Impact.BAIXO and o.impact_manual and o.rule is None
    assert o.probability == Probability.ALTA and o.risk_level == RiskLevel.MEDIO
    assert [r.id for r in risk.rank(assessed)] == [auto.id, overridden.id]
    assert [r.id for r in risk.high_impact(assessed)] == [auto.id]  # BAIXO is not high


# --- criteria ---------------------------------------------------------------------------------


def test_axis_coverage_ignores_org_and_counts_distinct_axes():
    org = node(NodeLabel.ORGANIZACAO, {"name": "O"})
    dom = node(NodeLabel.DOMINIO, {"name": "a.test"})
    dom2 = node(NodeLabel.DOMINIO, {"name": "b.test"})
    emp = node(NodeLabel.FUNCIONARIO, {"name": "E"})
    c = criteria.criterion_axis_coverage([org, dom, dom2, emp], "en")
    assert c.value == 2 and not c.passed and c.threshold == 3
    assert criteria.axes_present([org, dom, emp]) == [Axis.DIGITAL, Axis.HUMANO]
    site = node(NodeLabel.INSTALACAO_FISICA, {"name": "S"})
    assert criteria.criterion_axis_coverage([dom, emp, site], "pt").passed


def test_seed_to_ot_and_high_impact_criteria():
    missing = PathResult(method="shortestPath", found=False, reason="no_ot")
    c2 = criteria.criterion_seed_to_ot(missing, "en")
    assert not c2.passed and "No OT asset" in c2.evidence[0]
    assert criteria.criterion_high_impact([], "en").passed is False


# --- report -------------------------------------------------------------------------------------


def _result() -> AnalysisResult:
    project = ProjectOut(
        id="p", name="Demo | project", description="", org_name="Org", seed_domain="org.test",
        root_node_id="n1", created_at="", updated_at="", node_count=2, edge_count=1,
    )  # fmt: skip
    hops = [
        PathHop(node_id="n1", title="Org", label=NodeLabel.ORGANIZACAO, axis=Axis.ORG, layer=None),
        PathHop(
            node_id="n2",
            title="PLC",
            label=NodeLabel.DISPOSITIVO_INDUSTRIAL,
            axis=Axis.DIGITAL,
            layer=Layer.TO,
        ),
    ]
    path = PathResult(
        method="shortestPath", found=True, seed_id="n1", seed_title="Org", target_id="n2",
        target_title="PLC", hops=1, cost=1.0, nodes=hops,
        edges=[PathStep(edge_id="e1", rel=RelType.ACESSA_DIRETAMENTE, source_id="n1", target_id="n2", weight=1.0)],  # noqa: E501
    )  # fmt: skip
    return AnalysisResult(
        project=project,
        computed_at="2026-09-16T00:00:00Z",
        seed_id="n1",
        axes_present=[Axis.DIGITAL],
        criteria=[
            Criterion(
                number=1,
                key="axis_coverage",
                passed=False,
                value=1,
                threshold=3,
                evidence=["DIGITAL: 2"],
            ),
            Criterion(
                number=2, key="seed_to_ot", passed=True, value=1, threshold=1, evidence=["1 hop"]
            ),
            Criterion(number=3, key="high_impact", passed=False, value=0, threshold=1),
        ],
        all_passed=False,
        path=path,
        weighted_path=PathResult(method="gds.dijkstra", found=False, reason="gds_unavailable"),
        high_impact_edges=[],
        classified_edges=[],
        unclassified_cross_axis=[],
        centrality=[],
        centrality_method="none",
        gds_available=False,
        inventory=Inventory(
            node_count=2,
            edge_count=1,
            nodes_by_label={"Organizacao": 1, "Dispositivo_Industrial": 1},
            edges_by_rel={"ACESSA_DIRETAMENTE": 1},
            nodes_by_axis={"ORG": 1, "DIGITAL": 1},
        ),
    )


def test_report_renders_three_formats_in_both_locales():
    result = _result()
    md, mt = report.render(result, None, "md", locale="pt", app_name="OSINTree", entry="digital")
    assert mt.startswith("text/markdown")
    assert md.startswith("# Relatório de superfície de ataque passiva")
    assert "| 2 | Pelo menos um caminho" in md and "ATENDIDO" in md and "NÃO ATENDIDO" in md
    assert "Demo \\| project" in md  # pipe escaped inside a table cell
    assert "Plugin GDS não instalado" in md
    assert "ACESSA_DIRETAMENTE (extensão)" in md

    html, mt = report.render(result, None, "html", locale="en", app_name="OSINTree", entry="any")
    assert mt.startswith("text/html")
    assert (
        html.startswith("<!DOCTYPE html>")
        and "<script" not in html
        and "http" not in html.split("<body>")[0].replace("http-equiv", "")
    )  # self-contained
    assert '<td class="res-pass">PASS</td>' in html and '<td class="res-fail">FAIL</td>' in html
    assert "any node anchored to the organization" in html
    assert "Demo | project" in html

    js, mt = report.render(result, None, "json", locale="pt", app_name="OSINTree", entry="digital")
    data = json.loads(js)
    assert mt == "application/json" and data["format"] == "osintree-report/1"
    assert data["analysis"]["criteria"][1]["passed"] is True and "graph" not in data
