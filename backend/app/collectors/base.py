"""Collector interface, run context and the passive-only guard (brief, Section 2.1).

A collector turns a seed (domain, IP, ASN or a Software node) into *findings*: candidate
nodes, or enrichments of existing nodes, each with the edges that attach it to nodes already
in the graph. Findings go to the staging area (``review/staging.py``), never to the live graph.

Every built-in collector queries third-party repositories only and declares
``interacts_with_target = False``. Any collector that would contact the target's own
infrastructure must declare ``interacts_with_target = True``; the registry then refuses it
while ``PASSIVE_ONLY`` is on.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import Settings
from app.db.driver import Neo4jClient
from app.db.schema import Axis, Layer, NodeLabel, RelType
from app.errors import DomainError
from app.models.common import utcnow_iso
from app.models.nodes import NodeOut
from app.models.projects import ProjectOut


class InputKind(StrEnum):
    DOMAIN = "domain"
    IP = "ip"
    ASN = "asn"
    SOFTWARE = "software"
    ORG = "org"  # organization name (project org_name / root node), for FISICO lookups


class PassiveGuardViolation(DomainError):
    status_code = 403
    key = "error.passive_guard"


class CollectorInputError(DomainError):
    status_code = 422
    key = "error.collector_input"


class FindingEdge(BaseModel):
    """An edge between the finding's node and an existing graph node."""

    rel: RelType
    other_id: str
    direction: Literal["out", "in"] = "out"  # out: finding -> other; in: other -> finding


class Finding(BaseModel):
    """``node``: a new node; ``node_update``: enrich ``target_id``; ``edge``: only attach
    ``edges`` to the existing ``target_id`` (the node itself is already in the graph)."""

    kind: Literal["node", "node_update", "edge"] = "node"
    label: NodeLabel | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    title: str | None = None
    description: str = ""
    notes: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)
    layer: Layer | None = None
    target_id: str | None = None  # node_update: the existing node to enrich
    edges: list[FindingEdge] = Field(default_factory=list)
    dedupe_key: str
    evidence: str = ""  # one human-readable line shown in the review queue
    raw: dict[str, Any] = Field(default_factory=dict)  # trimmed source excerpt


@dataclass
class RunContext:
    project: ProjectOut
    db: Neo4jClient
    settings: Settings
    http: Any  # CollectorHTTP
    nodes: list[NodeOut] = field(default_factory=list)
    collected_at: str = field(default_factory=utcnow_iso)

    def nodes_with(self, label: NodeLabel) -> list[NodeOut]:
        return [n for n in self.nodes if n.label is label]

    def find_node(self, label: NodeLabel, attr: str, value: str) -> NodeOut | None:
        for n in self.nodes:
            if n.label is label and str(n.attrs.get(attr, "")).lower() == value.lower():
                return n
        return None

    @property
    def root(self) -> NodeOut | None:
        rid = self.project.root_node_id
        return next((n for n in self.nodes if n.id == rid), None) if rid else None


class Collector(ABC):
    name: str
    description: str
    source_family: str  # thesis source family: "CT logs", "RDAP/WHOIS", "ASN/BGP", "NVD/CVE"
    axis: Axis
    input_kind: InputKind
    interacts_with_target: bool = False
    input_label: NodeLabel | None = None  # node type that can seed this collector, if any

    @abstractmethod
    async def collect(self, seed: str, ctx: RunContext) -> list[Finding]: ...

    def describe(self, passive_only: bool) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source_family": self.source_family,
            "axis": self.axis.value,
            "input_kind": self.input_kind.value,
            "input_label": self.input_label.value if self.input_label else None,
            "interacts_with_target": self.interacts_with_target,
            "allowed": not (passive_only and self.interacts_with_target),
        }
