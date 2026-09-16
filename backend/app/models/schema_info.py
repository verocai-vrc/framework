"""Read-only description of the schema for the UI palette (``GET /api/schema``)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.db.schema import (
    ALLOWED_EDGES,
    EXTENSION_REL_TYPES,
    LABEL_SPECS,
    VALIDATION_AXES,
    Axis,
    Layer,
    NodeLabel,
    RelType,
)
from app.models.common import Impact, Probability, RiskLevel
from app.models.nodes import ATTR_MODELS


class FieldInfo(BaseModel):
    name: str
    type: str
    required: bool
    default: Any = None
    choices: list[str] | None = None


class LabelInfo(BaseModel):
    label: NodeLabel
    display: dict[str, str]
    axis: Axis
    layers: list[Layer]
    default_layer: Layer | None
    fields: list[FieldInfo]


class RelInfo(BaseModel):
    rel: RelType
    extension: bool


class SchemaInfo(BaseModel):
    labels: list[LabelInfo]
    rel_types: list[RelInfo]
    allowed_edges: list[tuple[NodeLabel, RelType, NodeLabel]]
    axes: list[Axis]
    validation_axes: list[Axis]
    impacts: list[Impact]
    probabilities: list[Probability]
    risk_levels: list[RiskLevel]


def _field_type(schema: dict[str, Any], defs: dict[str, Any]) -> tuple[str, list[str] | None]:
    if "$ref" in schema:
        schema = defs[schema["$ref"].rsplit("/", 1)[-1]]
    if "enum" in schema:
        return "string", [str(c) for c in schema["enum"]]
    if "anyOf" in schema:
        for alt in schema["anyOf"]:
            if alt.get("type") != "null":
                return _field_type(alt, defs)
    return schema.get("type", "string"), None


def build_schema_info() -> SchemaInfo:
    labels: list[LabelInfo] = []
    for label, spec in LABEL_SPECS.items():
        model = ATTR_MODELS[label]
        json_schema = model.model_json_schema()
        defs = json_schema.get("$defs", {})
        required = set(json_schema.get("required", []))
        fields = []
        for name, prop in json_schema["properties"].items():
            ftype, choices = _field_type(prop, defs)
            fields.append(
                FieldInfo(
                    name=name,
                    type=ftype,
                    required=name in required,
                    default=prop.get("default"),
                    choices=choices,
                )
            )
        labels.append(
            LabelInfo(
                label=label,
                display={"pt": spec.display_pt, "en": spec.display_en},
                axis=spec.axis,
                layers=list(spec.layers),
                default_layer=spec.default_layer,
                fields=fields,
            )
        )
    return SchemaInfo(
        labels=labels,
        rel_types=[RelInfo(rel=r, extension=r in EXTENSION_REL_TYPES) for r in RelType],
        allowed_edges=sorted(ALLOWED_EDGES, key=lambda t: (t[0], t[1], t[2])),
        axes=list(Axis),
        validation_axes=sorted(VALIDATION_AXES),
        impacts=list(Impact),
        probabilities=list(Probability),
        risk_levels=list(RiskLevel),
    )
