"""Project (investigation) models. Every node and edge is scoped by ``project_id``."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    # The runtime target (brief, Section 2.4): supplied here, never hardcoded.
    org_name: str | None = Field(default=None, max_length=200)
    seed_domain: str | None = Field(default=None, max_length=253)


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    org_name: str | None = Field(default=None, max_length=200)
    seed_domain: str | None = Field(default=None, max_length=253)


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    org_name: str | None
    seed_domain: str | None
    root_node_id: str | None  # the project's Organizacao anchor, when one exists
    created_at: str
    updated_at: str
    node_count: int = 0
    edge_count: int = 0
