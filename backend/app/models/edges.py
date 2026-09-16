"""Edge models. Validity of the (source label, rel, target label) triple is enforced in
``graph/crud.py`` against ``db.schema.ALLOWED_EDGES``.

Risk fields: ``impact`` (Tabela 8), ``probability`` (heuristic) and ``risk_level`` (Tabela 2)
are stamped by ``analysis/risk.py``. A value the analyst sets by hand is flagged
``*_manual`` and the engine never replaces it until the flag is cleared."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.db.schema import NodeLabel, RelType
from app.models.common import Impact, Probability, Provenance, RiskLevel
from app.models.nodes import NodeOut


class EdgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    target_id: str
    rel: RelType
    notes: str = ""
    # Given here = analyst-provided (flagged manual); otherwise classified by the engine.
    impact: Impact | None = None
    probability: Probability | None = None
    # Estimated attacker effort for the weighted seed-to-OT path (GDS Dijkstra).
    weight: float | None = Field(default=None, gt=0)
    provenance: Provenance = Field(default_factory=Provenance)


class EdgeUpdate(BaseModel):
    """Partial update. Setting ``impact``/``probability`` marks them manual; sending
    ``impact_manual: false`` / ``probability_manual: false`` returns them to the engine."""

    model_config = ConfigDict(extra="forbid")

    notes: str | None = None
    impact: Impact | None = None
    impact_manual: bool | None = None
    probability: Probability | None = None
    probability_manual: bool | None = None
    weight: float | None = Field(default=None, gt=0)


class EdgeOut(BaseModel):
    id: str
    project_id: str
    rel: RelType
    source_id: str
    target_id: str
    source_label: NodeLabel
    target_label: NodeLabel
    cross_axis: bool
    notes: str
    impact: Impact | None
    impact_manual: bool = False
    probability: Probability | None = None
    probability_manual: bool = False
    risk_level: RiskLevel | None = None
    weight: float | None
    source: str
    collected_at: str
    reviewed: bool
    created_at: str
    updated_at: str


class GraphOut(BaseModel):
    project_id: str
    nodes: list[NodeOut]
    edges: list[EdgeOut]
