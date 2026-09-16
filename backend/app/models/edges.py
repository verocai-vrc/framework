"""Edge models. Validity of the (source label, rel, target label) triple is enforced in
``graph/crud.py`` against ``db.schema.ALLOWED_EDGES``."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.db.schema import NodeLabel, RelType
from app.models.common import Impact, Provenance
from app.models.nodes import NodeOut


class EdgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    target_id: str
    rel: RelType
    notes: str = ""
    # Stamped automatically by the risk engine (Sprint 4); the analyst may override.
    impact: Impact | None = None
    # Estimated attacker effort for the weighted seed-to-OT path (GDS Dijkstra).
    weight: float | None = Field(default=None, gt=0)
    provenance: Provenance = Field(default_factory=Provenance)


class EdgeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str | None = None
    impact: Impact | None = None
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
