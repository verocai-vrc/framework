"""Cross-axis impact (thesis Tabela 8), probability heuristic and the risk matrix
(thesis Tabela 2).

Everything here is pure computation over ``NodeOut``/``EdgeOut`` so it can be unit-tested
without a database; ``stamp_project`` is the only function that touches Neo4j. Analyst
overrides (``impact_manual`` / ``probability_manual``) are never replaced by the engine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from app.db.driver import Neo4jClient
from app.db.schema import ENTITY_LABEL, Layer, NodeLabel, RelType
from app.graph import crud
from app.models.analysis import RiskEdge
from app.models.common import Impact, Probability, RiskLevel, utcnow_iso
from app.models.edges import EdgeOut, GraphOut
from app.models.nodes import NodeOut

# ---------------------------------------------------------------------------------------
# Tabela 2 — risk matrix (probability x impact -> level), exactly as agreed with the author.
# Tabela 8 grades impact on four levels (BAIXO..CRITICO) while Tabela 2 has three impact
# columns, so a CRITICO impact is looked up in the ALTO column (the matrix has no higher one).
# ---------------------------------------------------------------------------------------

RISK_MATRIX: Final[dict[tuple[Probability, Impact], RiskLevel]] = {
    (Probability.BAIXA, Impact.BAIXO): RiskLevel.MINIMO,
    (Probability.BAIXA, Impact.MEDIO): RiskLevel.BAIXO,
    (Probability.BAIXA, Impact.ALTO): RiskLevel.MEDIO,
    (Probability.MEDIA, Impact.BAIXO): RiskLevel.BAIXO,
    (Probability.MEDIA, Impact.MEDIO): RiskLevel.MEDIO,
    (Probability.MEDIA, Impact.ALTO): RiskLevel.ALTO,
    (Probability.ALTA, Impact.BAIXO): RiskLevel.MEDIO,
    (Probability.ALTA, Impact.MEDIO): RiskLevel.ALTO,
    (Probability.ALTA, Impact.ALTO): RiskLevel.CRITICO,
}

HIGH_IMPACT: Final[frozenset[Impact]] = frozenset({Impact.CRITICO, Impact.ALTO})

IMPACT_ORDER: Final[dict[Impact, int]] = {
    Impact.BAIXO: 0, Impact.MEDIO: 1, Impact.ALTO: 2, Impact.CRITICO: 3
}  # fmt: skip
RISK_ORDER: Final[dict[RiskLevel, int]] = {
    RiskLevel.MINIMO: 0, RiskLevel.BAIXO: 1, RiskLevel.MEDIO: 2, RiskLevel.ALTO: 3,
    RiskLevel.CRITICO: 4,
}  # fmt: skip
PROBABILITY_ORDER: Final[dict[Probability, int]] = {
    Probability.BAIXA: 0, Probability.MEDIA: 1, Probability.ALTA: 2
}  # fmt: skip


def risk_level(probability: Probability, impact: Impact) -> RiskLevel:
    """Tabela 2 lookup. ``CRITICO`` impact uses the ``ALTO`` column (see module note)."""
    column = Impact.ALTO if impact == Impact.CRITICO else impact
    return RISK_MATRIX[(probability, column)]


# ---------------------------------------------------------------------------------------
# Evidence gathered from the whole project graph, so rule predicates can look one hop
# beyond an edge's endpoints ("Software *with CVE*", "Servico *remote-auth*").
# ---------------------------------------------------------------------------------------

# CVSS v3 "High" starts at 7.0; used by the probability heuristic only.
CVSS_HIGH: Final[float] = 7.0

NON_PRODUCTION_ENVIRONMENTS: Final[frozenset[str]] = frozenset({"staging", "homolog"})


@dataclass
class Evidence:
    """Per-node facts derived from the graph."""

    nodes: dict[str, NodeOut]
    cvss_by_node: dict[str, list[float | None]] = field(default_factory=dict)

    @classmethod
    def from_graph(cls, graph: GraphOut) -> Evidence:
        nodes = {n.id: n for n in graph.nodes}
        ev = cls(nodes=nodes)
        # Direct: Software -[POSSUI_VULNERABILIDADE]-> CVE.
        for e in graph.edges:
            if e.rel == RelType.POSSUI_VULNERABILIDADE and e.target_id in nodes:
                cvss = nodes[e.target_id].attrs.get("cvss")
                ev.cvss_by_node.setdefault(e.source_id, []).append(
                    float(cvss) if cvss is not None else None
                )
        # One hop: a Servico hosting vulnerable Software, a device operating over it.
        for e in graph.edges:
            if e.rel in (RelType.HOSPEDA, RelType.OPERA_SOBRE) and e.target_id in ev.cvss_by_node:
                ev.cvss_by_node.setdefault(e.source_id, []).extend(ev.cvss_by_node[e.target_id])
        return ev

    def has_cve(self, node_id: str) -> bool:
        return bool(self.cvss_by_node.get(node_id))

    def max_cvss(self, node_id: str) -> float | None:
        scores = [s for s in self.cvss_by_node.get(node_id, []) if s is not None]
        return max(scores) if scores else None


def _is_remote_auth(node: NodeOut) -> bool:
    return node.label == NodeLabel.SERVICO and bool(node.attrs.get("remote_auth"))


def _is_non_production(node: NodeOut) -> bool:
    return (
        node.label == NodeLabel.DOMINIO
        and str(node.attrs.get("environment", "")) in NON_PRODUCTION_ENVIRONMENTS
    )


# ---------------------------------------------------------------------------------------
# Tabela 8 — cross-axis impact rules. Each row: (id, source label, target label, predicate,
# impact). Rows are matched on the *labels* of the endpoints, in either edge direction, so
# the rule fires on whichever relationship type connects the pair (thesis rows do not name
# relationship types). Row conditions ("with CVE", "remote-auth", "staging/homolog") are
# preconditions: when unmet, the edge is left unclassified for the analyst.
# ---------------------------------------------------------------------------------------

Predicate = Callable[[NodeOut, NodeOut, Evidence], bool]


@dataclass(frozen=True)
class ImpactRule:
    id: str
    source: NodeLabel
    target: NodeLabel
    impact: Impact
    predicate: Predicate | None = None

    def matches(self, a: NodeOut, b: NodeOut, ev: Evidence) -> bool:
        """``a``/``b`` in the rule's (source, target) order."""
        if a.label != self.source or b.label != self.target:
            return False
        return self.predicate is None or self.predicate(a, b, ev)


IMPACT_RULES: Final[tuple[ImpactRule, ...]] = (
    # T8.1 Credencial_Vazada (HUMANO) -> Servico remote-auth (DIGITAL/TI): CRITICO
    ImpactRule(
        "T8.1",
        NodeLabel.CREDENCIAL_VAZADA,
        NodeLabel.SERVICO,
        Impact.CRITICO,
        lambda _a, b, _ev: _is_remote_auth(b),
    ),
    # T8.2 Software with CVE (DIGITAL/TI) -> Dispositivo_Industrial (DIGITAL/TO): CRITICO.
    # The thesis relationship runs Dispositivo_Industrial -[OPERA_SOBRE]-> Software, so this
    # row is matched with the endpoints reversed (see ``classify_impact``).
    ImpactRule(
        "T8.2",
        NodeLabel.SOFTWARE,
        NodeLabel.DISPOSITIVO_INDUSTRIAL,
        Impact.CRITICO,
        lambda a, _b, ev: ev.has_cve(a.id) and a.layer == Layer.TI,
    ),
    # T8.3 Instalacao_Fisica (FISICO) -> Dispositivo_Industrial (DIGITAL/TO): CRITICO
    ImpactRule(
        "T8.3", NodeLabel.INSTALACAO_FISICA, NodeLabel.DISPOSITIVO_INDUSTRIAL, Impact.CRITICO
    ),
    # T8.4 Funcionario (HUMANO) -> Dispositivo_Industrial (DIGITAL/TO): ALTO
    ImpactRule("T8.4", NodeLabel.FUNCIONARIO, NodeLabel.DISPOSITIVO_INDUSTRIAL, Impact.ALTO),
    # T8.5 Fornecedor (ECOSSISTEMA) -> Endereco_IP (DIGITAL/TI): ALTO
    ImpactRule("T8.5", NodeLabel.FORNECEDOR, NodeLabel.ENDERECO_IP, Impact.ALTO),
    # T8.6 Dominio staging/homolog (DIGITAL/TI) -> Fornecedor (ECOSSISTEMA): MEDIO
    ImpactRule(
        "T8.6",
        NodeLabel.DOMINIO,
        NodeLabel.FORNECEDOR,
        Impact.MEDIO,
        lambda a, _b, _ev: _is_non_production(a),
    ),
)


def classify_impact(source: NodeOut, target: NodeOut, ev: Evidence) -> tuple[Impact, str] | None:
    """The Tabela 8 row that applies to an edge between ``source`` and ``target`` (in edge
    direction), or ``None``. Rows are tried in both orientations."""
    for rule in IMPACT_RULES:
        if rule.matches(source, target, ev) or rule.matches(target, source, ev):
            return rule.impact, rule.id
    return None


# ---------------------------------------------------------------------------------------
# Probability heuristic (brief, Section 5.4: "may be heuristic ... must be overridable").
# Evidence keys are translated by the report; the strongest signal sets the level.
# ---------------------------------------------------------------------------------------


def estimate_probability(
    source: NodeOut, target: NodeOut, ev: Evidence
) -> tuple[Probability, list[str]]:
    evidence: list[str] = []
    level = Probability.BAIXA

    def raise_to(p: Probability, key: str) -> None:
        nonlocal level
        if key not in evidence:
            evidence.append(key)
        if PROBABILITY_ORDER[p] > PROBABILITY_ORDER[level]:
            level = p

    for node in (source, target):
        cvss = ev.max_cvss(node.id)
        if cvss is not None and cvss >= CVSS_HIGH:
            raise_to(Probability.ALTA, "cve_high")
        elif ev.has_cve(node.id):
            raise_to(Probability.MEDIA, "cve_known")
        if _is_remote_auth(node):
            raise_to(Probability.MEDIA, "remote_auth")
        if _is_non_production(node):
            raise_to(Probability.MEDIA, "non_production")

    if source.label == NodeLabel.CREDENCIAL_VAZADA:
        # A documented leak against a remote-auth service is the textbook initial access.
        strong = _is_remote_auth(target)
        raise_to(Probability.ALTA if strong else Probability.MEDIA, "leaked_credential")
    if source.label == NodeLabel.FORNECEDOR and target.label == NodeLabel.ENDERECO_IP:
        raise_to(Probability.MEDIA, "supplier_access")
    if target.label == NodeLabel.DISPOSITIVO_INDUSTRIAL and source.label in (
        NodeLabel.FUNCIONARIO,
        NodeLabel.SERVICO,
    ):
        raise_to(Probability.MEDIA, "direct_ot_access")

    return level, evidence


# ---------------------------------------------------------------------------------------
# Whole-project classification
# ---------------------------------------------------------------------------------------


def assess_edge(edge: EdgeOut, ev: Evidence) -> RiskEdge:
    """Compute (or keep, when manual) impact and probability, derive the risk level."""
    a, b = ev.nodes[edge.source_id], ev.nodes[edge.target_id]
    rule: str | None = None
    impact = edge.impact if edge.impact_manual else None
    if not edge.impact_manual:
        classified = classify_impact(a, b, ev)
        if classified is not None:
            impact, rule = classified
    elif (classified := classify_impact(a, b, ev)) is not None:
        rule = classified[1]  # report which row the analyst overrode

    probability, evidence = estimate_probability(a, b, ev)
    if edge.probability_manual and edge.probability is not None:
        probability = edge.probability

    return RiskEdge(
        id=edge.id,
        rel=edge.rel,
        source_id=a.id,
        source_title=a.title,
        source_label=a.label,
        target_id=b.id,
        target_title=b.title,
        target_label=b.label,
        cross_axis=edge.cross_axis,
        impact=impact,
        impact_manual=edge.impact_manual,
        rule=rule,
        probability=probability,
        probability_manual=edge.probability_manual,
        probability_evidence=evidence,
        risk_level=risk_level(probability, impact) if impact is not None else None,
        weight=edge.weight,
    )


def assess_graph(graph: GraphOut) -> list[RiskEdge]:
    ev = Evidence.from_graph(graph)
    return [
        assess_edge(e, ev)
        for e in graph.edges
        if e.source_id in ev.nodes and e.target_id in ev.nodes
    ]


def rank(edges: list[RiskEdge]) -> list[RiskEdge]:
    """Most severe first: risk level, then impact, then probability, then title."""
    return sorted(
        edges,
        key=lambda r: (
            -(RISK_ORDER[r.risk_level] if r.risk_level else -1),
            -(IMPACT_ORDER[r.impact] if r.impact else -1),
            -(PROBABILITY_ORDER[r.probability] if r.probability else -1),
            r.source_title,
            r.target_title,
        ),
    )


def high_impact(edges: list[RiskEdge]) -> list[RiskEdge]:
    """Criterion 3 candidates: cross-axis edges whose impact is CRITICO or ALTO."""
    return rank([r for r in edges if r.cross_axis and r.impact in HIGH_IMPACT])


_STAMP = f"""
MATCH (a:{ENTITY_LABEL} {{project_id: $pid}})-[r]->(:{ENTITY_LABEL})
WITH r, $rows[r.id] AS row
WHERE row IS NOT NULL
SET r.impact = row.impact,
    r.probability = row.probability,
    r.risk_level = row.risk_level,
    r.analysed_at = $now
RETURN count(r) AS stamped
"""


async def stamp_project(db: Neo4jClient, project_id: str) -> tuple[GraphOut, list[RiskEdge]]:
    """Classify every edge of the project and write ``impact``/``probability``/``risk_level``
    back to Neo4j (``SET`` to null removes a property, so a lost rule clears the value)."""
    graph = await crud.get_graph(db, project_id)
    assessed = assess_graph(graph)
    rows = {
        r.id: {
            "impact": r.impact.value if r.impact else None,
            "probability": r.probability.value if r.probability else None,
            "risk_level": r.risk_level.value if r.risk_level else None,
        }
        for r in assessed
    }
    if rows:
        await db.run(_STAMP, {"pid": project_id, "rows": rows, "now": utcnow_iso()})
    # Reflect the stamped values on the returned graph without a second round trip.
    by_id = {r.id: r for r in assessed}
    for e in graph.edges:
        if e.id in by_id:
            r = by_id[e.id]
            e.impact, e.probability, e.risk_level = r.impact, r.probability, r.risk_level
    return graph, assessed
