"""``GET /api/schema``: labels, fields, relationship types and allowed combinations, so the
UI palette is driven by the backend's single source of truth."""

from __future__ import annotations

from fastapi import APIRouter

from app.models.schema_info import SchemaInfo, build_schema_info

router = APIRouter(prefix="/api", tags=["schema"])

_SCHEMA_INFO = build_schema_info()


@router.get("/schema", response_model=SchemaInfo)
async def get_schema() -> SchemaInfo:
    return _SCHEMA_INFO
