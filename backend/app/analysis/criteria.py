"""The three PoC validation criteria (brief, Section 7 / Appendix 12) and the orchestrator
that produces one ``AnalysisResult`` for a project.

1. Axis coverage: >= 3 of the 4 validation axes present.
2. Seed-to-OT path: at least one directed path from the public seed to an OT asset.
3. Cross-axis high impact: >= 1 cross-axis edge classified CRITICO or ALTO.
"""

from __future__ import annotations

from collections import Counter
from typing import Final

from app.db.driver import Neo4jClient
from app.db.schema import VALIDATION_AXES, Axis
from app.graph import projects
from app.i18n import t
from app.models.analysis import (
    AnalysisOptions,
    AnalysisResult,
    Criterion,
    Inventory,
    PathResult,
    RiskEdge,
)
from app.models.common import utcnow_iso
from app.models.edges import GraphOut
from app.models.nodes import NodeOut

from . import paths, risk
from .paths import EntryPolicy

AXIS_COVERAGE_THRESHOLD: Final = 3
SEED_TO_OT_THRESHOLD: Final = 1
HIGH_IMPACT_THRESHOLD: Final = 1


def axes_present(nodes: list[NodeOut]) -> list[Axis]:
    present = {n.axis for n in nodes if n.axis in VALIDATION_AXES}
    return [a for a in Axis if a in present]


def criterion_axis_coverage(nodes: list[NodeOut], locale: str) -> Criterion:
    present = axes_present(nodes)
    counts = Counter(n.axis for n in nodes if n.axis in VALIDATION_AXES)
    evidence = [
        t("report.axis_evidence", locale, axis=a.value, n=counts[a])
        for a in Axis
        if a in VALIDATION_AXES
    ]
    return Criterion(
        number=1,
        key="axis_coverage",
        passed=len(present) >= AXIS_COVERAGE_THRESHOLD,
        value=len(present),
        threshold=AXIS_COVERAGE_THRESHOLD,
        evidence=evidence,
    )


def criterion_seed_to_ot(path: PathResult, locale: str) -> Criterion:
    if path.found:
        chain = " → ".join(h.title for h in path.nodes)
        evidence = [
            t("report.path_evidence", locale, hops=path.hops, target=path.target_title),
            chain,
        ]
    else:
        evidence = [t(f"report.path_reason.{path.reason}", locale)]
    return Criterion(
        number=2,
        key="seed_to_ot",
        passed=path.found,
        value=1 if path.found else 0,
        threshold=SEED_TO_OT_THRESHOLD,
        evidence=evidence,
    )


def criterion_high_impact(high: list[RiskEdge], locale: str) -> Criterion:
    evidence = [
        f"{r.source_title} -[{r.rel.value}]-> {r.target_title}: "
        f"{r.impact.value if r.impact else '-'} ({r.rule or t('report.manual', locale)})"
        for r in high
    ]
    return Criterion(
        number=3,
        key="high_impact",
        passed=len(high) >= HIGH_IMPACT_THRESHOLD,
        value=len(high),
        threshold=HIGH_IMPACT_THRESHOLD,
        evidence=evidence,
    )


def inventory(graph: GraphOut) -> Inventory:
    return Inventory(
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        nodes_by_label=dict(sorted(Counter(n.label.value for n in graph.nodes).items())),
        edges_by_rel=dict(sorted(Counter(e.rel.value for e in graph.edges).items())),
        nodes_by_axis=dict(sorted(Counter(n.axis.value for n in graph.nodes).items())),
    )


async def analyse(
    db: Neo4jClient,
    project_id: str,
    options: AnalysisOptions | None = None,
    *,
    entry: EntryPolicy = "digital",
    locale: str = "en",
) -> AnalysisResult:
    """Run the whole engine: stamp risk on edges, evaluate the criteria, find paths."""
    options = options or AnalysisOptions()
    project = await projects.get_project(db, project_id)
    graph, assessed = await risk.stamp_project(db, project_id)

    gds = await paths.gds_available(db)
    path = await paths.shortest_path_to_ot(db, project, graph, entry)
    weighted = (
        await paths.weighted_path_to_ot(db, project, graph, entry) if options.weighted else None
    )
    if options.centrality:
        central, method = await paths.centrality(db, project, graph, options.top_n)
    else:
        central, method = [], "none"

    high = risk.high_impact(assessed)
    criteria = [
        criterion_axis_coverage(graph.nodes, locale),
        criterion_seed_to_ot(path, locale),
        criterion_high_impact(high, locale),
    ]
    return AnalysisResult(
        project=project,
        computed_at=utcnow_iso(),
        seed_id=path.seed_id,
        axes_present=axes_present(graph.nodes),
        criteria=criteria,
        all_passed=all(c.passed for c in criteria),
        path=path,
        weighted_path=weighted,
        high_impact_edges=high,
        classified_edges=risk.rank([r for r in assessed if r.impact is not None]),
        unclassified_cross_axis=[r for r in assessed if r.cross_axis and r.impact is None],
        centrality=central,
        centrality_method=method,
        gds_available=gds,
        inventory=inventory(graph),
    )
