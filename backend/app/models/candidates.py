"""Review-queue models. A candidate wraps a collector finding with its review state."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.collectors.base import Finding, FindingEdge
from app.db.schema import Layer, NodeLabel

CandidateStatus = Literal["pending", "approved", "rejected"]


class CandidateOut(BaseModel):
    id: str
    project_id: str
    collector: str
    source_family: str
    seed: str
    kind: Literal["node", "node_update", "edge"]
    status: CandidateStatus
    label: NodeLabel | None
    title: str
    attrs: dict[str, Any]
    description: str
    notes: str
    metadata: dict[str, str]
    layer: Layer | None
    target_id: str | None
    edges: list[FindingEdge]
    dedupe_key: str
    evidence: str
    raw: dict[str, Any]
    source: str
    collected_at: str
    created_at: str
    decided_at: str | None
    merged_node_id: str | None
    warnings: list[str] = Field(default_factory=list)


class CandidateUpdate(BaseModel):
    """Analyst edits before approval."""

    model_config = ConfigDict(extra="forbid")

    attrs: dict[str, Any] | None = None
    title: str | None = Field(default=None, max_length=300)
    description: str | None = None
    notes: str | None = None
    metadata: dict[str, str] | None = None
    layer: Layer | None = None
    edges: list[FindingEdge] | None = None


class BulkIds(BaseModel):
    ids: list[str] = Field(min_length=1)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seed: str | None = Field(default=None, max_length=253)
    node_id: str | None = None


class RunReport(BaseModel):
    collector: str
    seed: str
    findings: int
    staged: int
    skipped_pending: int
    skipped_in_graph: int
    duration_s: float
    candidates: list[CandidateOut]


__all__ = ["BulkIds", "CandidateOut", "CandidateUpdate", "Finding", "RunReport", "RunRequest"]
