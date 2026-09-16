"""Shared model pieces: provenance, timestamps, ids."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

MANUAL_SOURCE = "manual"


def utcnow_iso() -> str:
    """ISO-8601 UTC timestamp with second precision (brief, Section 2.3)."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


class Provenance(BaseModel):
    """Stamped on every node and edge. Manual entries are reviewed by definition."""

    source: str = Field(default=MANUAL_SOURCE, min_length=1, max_length=64)
    collected_at: str = Field(default_factory=utcnow_iso)
    reviewed: bool = True


class Impact(StrEnum):
    """Impact levels from thesis Tabela 8 (edge property ``impact``)."""

    BAIXO = "BAIXO"
    MEDIO = "MEDIO"
    ALTO = "ALTO"
    CRITICO = "CRITICO"
