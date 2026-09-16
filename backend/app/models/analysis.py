"""Analysis result models (brief, Section 7): the three validation criteria, the seed-to-OT
path, ranked cross-axis risk edges, centrality and an inventory. This is the payload of
``POST /api/projects/{id}/analysis`` and the data behind every report format."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.db.schema import Axis, Layer, NodeLabel, RelType
from app.models.common import Impact, Probability, RiskLevel
from app.models.projects import ProjectOut


class RiskEdge(BaseModel):
    """An edge as the risk engine sees it: endpoints resolved to titles, the Tabela 8 rule
    that fired (if any) and the evidence behind the probability estimate."""

    id: str
    rel: RelType
    source_id: str
    source_title: str
    source_label: NodeLabel
    target_id: str
    target_title: str
    target_label: NodeLabel
    cross_axis: bool
    impact: Impact | None
    impact_manual: bool
    rule: str | None = None  # e.g. "T8.1"; None when no Tabela 8 row matched
    probability: Probability | None
    probability_manual: bool
    probability_evidence: list[str] = Field(default_factory=list)  # evidence keys (i18n)
    risk_level: RiskLevel | None
    weight: float | None = None


class Criterion(BaseModel):
    number: Literal[1, 2, 3]
    key: Literal["axis_coverage", "seed_to_ot", "high_impact"]
    passed: bool
    value: int
    threshold: int
    evidence: list[str] = Field(default_factory=list)  # human-readable, already localised


class PathHop(BaseModel):
    node_id: str
    title: str
    label: NodeLabel
    axis: Axis
    layer: Layer | None


class PathStep(BaseModel):
    edge_id: str
    rel: RelType
    source_id: str
    target_id: str
    weight: float


class PathResult(BaseModel):
    method: Literal["shortestPath", "gds.dijkstra"]
    found: bool
    reason: str | None = None  # why not found: "no_seed", "no_ot", "unreachable", "gds_unavailable"
    seed_id: str | None = None
    seed_title: str | None = None
    target_id: str | None = None
    target_title: str | None = None
    hops: int | None = None
    cost: float | None = None  # weighted variant only (sum of edge weights)
    nodes: list[PathHop] = Field(default_factory=list)
    edges: list[PathStep] = Field(default_factory=list)


class CentralityEntry(BaseModel):
    node_id: str
    title: str
    label: NodeLabel
    axis: Axis
    degree: float
    betweenness: float | None = None


class Inventory(BaseModel):
    node_count: int
    edge_count: int
    nodes_by_label: dict[str, int]
    edges_by_rel: dict[str, int]
    nodes_by_axis: dict[str, int]


class AnalysisResult(BaseModel):
    project: ProjectOut
    computed_at: str
    seed_id: str | None
    axes_present: list[Axis]
    criteria: list[Criterion]
    all_passed: bool
    path: PathResult
    weighted_path: PathResult | None = None
    high_impact_edges: list[RiskEdge]  # cross-axis, impact in {CRITICO, ALTO}; ranked
    classified_edges: list[RiskEdge]  # every edge carrying an impact, ranked
    unclassified_cross_axis: list[RiskEdge]  # crossings no Tabela 8 rule covers
    centrality: list[CentralityEntry]
    centrality_method: Literal["gds", "cypher", "none"]
    gds_available: bool
    inventory: Inventory


class AnalysisOptions(BaseModel):
    weighted: bool = True  # also run GDS Dijkstra when GDS is installed
    centrality: bool = True
    top_n: int = Field(default=10, ge=1, le=100)
