"""Node models: common envelope plus one typed attribute model per thesis label.

Label-specific attributes (``attrs``) are validated by the model in ``ATTR_MODELS`` and
stored flat as node properties in Neo4j (so the ``Dominio.name`` style indexes apply).
Everything else is the common envelope from the brief (Section 5).
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.schema import LABEL_SPECS, Axis, Layer, NodeLabel
from app.models.common import Provenance

# --- per-label attribute models --------------------------------------------------------

Environment = Literal["production", "staging", "homolog", "dev", "test", "unknown"]

# Name fragments that mark non-production environments (Tabela 8: "Dominio, staging/homolog").
_ENV_HINTS: tuple[tuple[str, Environment], ...] = (
    ("staging", "staging"),
    ("stg", "staging"),
    ("homolog", "homolog"),
    ("hml", "homolog"),
    ("homologacao", "homolog"),
    ("dev", "dev"),
    ("test", "test"),
    ("qa", "test"),
)

# Services whose exposure implies remote authentication (Tabela 8: "Servico, remote-auth").
REMOTE_AUTH_SERVICES: frozenset[str] = frozenset(
    {"ssh", "rdp", "telnet", "vpn", "sslvpn", "ipsec", "ftp", "vnc", "smb", "winrm", "citrix"}
)
REMOTE_AUTH_PORTS: frozenset[int] = frozenset(
    {21, 22, 23, 445, 500, 1194, 3389, 4500, 5900, 5985, 5986}
)


class AttrModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    def default_title(self) -> str:  # pragma: no cover - overridden
        return ""


class OrganizacaoAttrs(AttrModel):
    name: str = Field(min_length=1, max_length=200)
    sector: str | None = None
    country: str | None = None

    def default_title(self) -> str:
        return self.name


class DominioAttrs(AttrModel):
    name: str = Field(min_length=1, max_length=253)
    environment: Environment = "unknown"

    @field_validator("name")
    @classmethod
    def _normalise(cls, v: str) -> str:
        v = v.strip().lower().rstrip(".")
        if not re.fullmatch(r"[a-z0-9*][a-z0-9.\-*_]*", v):
            raise ValueError("not a valid domain name")
        return v

    @model_validator(mode="after")
    def _infer_environment(self) -> DominioAttrs:
        """Infer from subdomain labels only (never the registrable domain or TLD, so
        ``example.test`` is production); hyphenated tokens count (``api-dev``)."""
        if self.environment == "unknown":
            sub_labels = self.name.split(".")[:-2]
            tokens = {tok for part in sub_labels for tok in part.split("-")}
            for hint, env in _ENV_HINTS:
                if hint in tokens:
                    self.environment = env
                    break
            else:
                self.environment = "production"
        return self

    def default_title(self) -> str:
        return self.name


class EnderecoIPAttrs(AttrModel):
    address: str
    asn: int | None = Field(default=None, ge=0)
    asn_name: str | None = None
    country: str | None = None

    @field_validator("address")
    @classmethod
    def _valid_ip(cls, v: str) -> str:
        return str(ipaddress.ip_address(v.strip()))

    def default_title(self) -> str:
        return self.address


class ServicoAttrs(AttrModel):
    port: int = Field(ge=0, le=65535)
    protocol: str = Field(default="tcp", max_length=16)
    service: str | None = Field(default=None, max_length=64)
    banner: str | None = None
    remote_auth: bool | None = None

    @model_validator(mode="after")
    def _infer_remote_auth(self) -> ServicoAttrs:
        if self.remote_auth is None:
            svc = (self.service or "").lower().replace(" ", "")
            self.remote_auth = (
                any(k in svc for k in REMOTE_AUTH_SERVICES) or self.port in REMOTE_AUTH_PORTS
            )
        return self

    def default_title(self) -> str:
        return f"{self.service or self.protocol} :{self.port}"


class SoftwareAttrs(AttrModel):
    product: str = Field(min_length=1, max_length=200)
    vendor: str | None = None
    version: str | None = None
    cpe: str | None = None

    def default_title(self) -> str:
        return f"{self.product} {self.version}".strip()


class DispositivoIndustrialAttrs(AttrModel):
    vendor: str | None = None
    model: str | None = None
    device_type: str | None = None  # PLC, RTU, HMI, IIoT gateway, ...
    protocol: str | None = None  # Modbus, S7comm, DNP3, ...

    def default_title(self) -> str:
        return " ".join(p for p in (self.vendor, self.model) if p) or (self.device_type or "")


class CVEAttrs(AttrModel):
    cve_id: str
    cvss: float | None = Field(default=None, ge=0, le=10)
    severity: str | None = None
    published: str | None = None

    @field_validator("cve_id")
    @classmethod
    def _valid_cve(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.fullmatch(r"CVE-\d{4}-\d{4,}", v):
            raise ValueError("expected CVE-YYYY-NNNN")
        return v

    def default_title(self) -> str:
        return self.cve_id


class FuncionarioAttrs(AttrModel):
    name: str = Field(min_length=1, max_length=200)
    role: str | None = None
    email: str | None = None
    profile_url: str | None = None

    def default_title(self) -> str:
        return self.name


class CredencialVazadaAttrs(AttrModel):
    email: str = Field(min_length=3, max_length=254)
    leak_name: str | None = None
    leak_date: str | None = None
    secret_type: str | None = None  # plaintext, md5, bcrypt, ...

    def default_title(self) -> str:
        return self.email


class InstalacaoFisicaAttrs(AttrModel):
    name: str = Field(min_length=1, max_length=200)
    address: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    facility_type: str | None = None

    def default_title(self) -> str:
        return self.name


class FornecedorAttrs(AttrModel):
    name: str = Field(min_length=1, max_length=200)
    service_provided: str | None = None
    asn: int | None = Field(default=None, ge=0)
    contract_ref: str | None = None

    def default_title(self) -> str:
        return self.name


ATTR_MODELS: dict[NodeLabel, type[AttrModel]] = {
    NodeLabel.ORGANIZACAO: OrganizacaoAttrs,
    NodeLabel.DOMINIO: DominioAttrs,
    NodeLabel.ENDERECO_IP: EnderecoIPAttrs,
    NodeLabel.SERVICO: ServicoAttrs,
    NodeLabel.SOFTWARE: SoftwareAttrs,
    NodeLabel.DISPOSITIVO_INDUSTRIAL: DispositivoIndustrialAttrs,
    NodeLabel.CVE: CVEAttrs,
    NodeLabel.FUNCIONARIO: FuncionarioAttrs,
    NodeLabel.CREDENCIAL_VAZADA: CredencialVazadaAttrs,
    NodeLabel.INSTALACAO_FISICA: InstalacaoFisicaAttrs,
    NodeLabel.FORNECEDOR: FornecedorAttrs,
}


def validate_attrs(label: NodeLabel, attrs: dict[str, Any]) -> AttrModel:
    return ATTR_MODELS[label].model_validate(attrs)


# --- envelope ---------------------------------------------------------------------------

# Properties owned by the envelope; attribute models must not reuse these names.
RESERVED_PROPS: frozenset[str] = frozenset(
    {
        "id", "project_id", "label_display", "title", "description", "notes", "axis", "layer",
        "source", "collected_at", "reviewed", "metadata_json", "created_at", "updated_at",
    }
)  # fmt: skip


class NodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: NodeLabel
    attrs: dict[str, Any] = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=300)
    description: str = Field(default="", max_length=5000)
    notes: str = ""  # Markdown
    metadata: dict[str, str] = Field(default_factory=dict)
    layer: Layer | None = None
    provenance: Provenance = Field(default_factory=Provenance)

    @model_validator(mode="after")
    def _check(self) -> NodeCreate:
        validate_attrs(self.label, self.attrs)
        spec = LABEL_SPECS[self.label]
        if self.layer is not None and self.layer not in spec.layers:
            raise ValueError(f"{self.label} cannot be on layer {self.layer}")
        return self


class NodeUpdate(BaseModel):
    """Partial update; ``attrs`` replaces the whole attribute set when given.

    ``label`` re-types the node (used after a best-effort import); it requires ``attrs``
    valid for the new label and is refused when an existing edge would become invalid."""

    model_config = ConfigDict(extra="forbid")

    label: NodeLabel | None = None
    attrs: dict[str, Any] | None = None
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    notes: str | None = None
    metadata: dict[str, str] | None = None
    layer: Layer | None = None

    @model_validator(mode="after")
    def _retype_needs_attrs(self) -> NodeUpdate:
        if self.label is not None and self.attrs is None:
            raise ValueError("re-typing a node requires attrs for the new label")
        return self


class NodeOut(BaseModel):
    id: str
    project_id: str
    label: NodeLabel
    label_display: str
    axis: Axis
    layer: Layer | None
    title: str
    description: str
    notes: str
    attrs: dict[str, Any]
    metadata: dict[str, str]
    source: str
    collected_at: str
    reviewed: bool
    created_at: str
    updated_at: str


def resolve_layer(label: NodeLabel, layer: Layer | None) -> Layer | None:
    spec = LABEL_SPECS[label]
    if layer is not None and layer in spec.layers:
        return layer
    return spec.default_layer
