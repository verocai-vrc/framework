"""Graph schema: node labels, axes, layers, relationship types, allowed endpoint
combinations, and the Neo4j constraints/indexes applied at startup.

Everything in this module that comes from the thesis is contractual (brief, Sections 5.1
and 5.2). Items marked ``EXTENSION`` go beyond the thesis list and are documented in
``METHODOLOGY_MAPPING.md``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class Axis(StrEnum):
    """Validation axes (thesis). ``ORG`` is the anchor, not an axis."""

    ORG = "ORG"
    DIGITAL = "DIGITAL"
    HUMANO = "HUMANO"
    FISICO = "FISICO"
    ECOSSISTEMA = "ECOSSISTEMA"


VALIDATION_AXES: Final[frozenset[Axis]] = frozenset(
    {Axis.DIGITAL, Axis.HUMANO, Axis.FISICO, Axis.ECOSSISTEMA}
)


class Layer(StrEnum):
    """IT vs OT layer, used by the seed-to-OT path metric."""

    TI = "TI"
    TO = "TO"


class NodeLabel(StrEnum):
    """Node labels from thesis Tabela 7. ASCII only (safe in Cypher)."""

    ORGANIZACAO = "Organizacao"
    DOMINIO = "Dominio"
    ENDERECO_IP = "Endereco_IP"
    SERVICO = "Servico"
    SOFTWARE = "Software"
    DISPOSITIVO_INDUSTRIAL = "Dispositivo_Industrial"
    CVE = "CVE"
    FUNCIONARIO = "Funcionario"
    CREDENCIAL_VAZADA = "Credencial_Vazada"
    INSTALACAO_FISICA = "Instalacao_Fisica"
    FORNECEDOR = "Fornecedor"


# Secondary label stamped on every typed node so cross-label queries (all nodes of a
# project, lookup by id) can use a single index. Implementation detail, not a thesis label.
ENTITY_LABEL: Final = "Entity"
PROJECT_LABEL: Final = "Project"
CANDIDATE_LABEL: Final = "Candidate"


class LabelSpec:
    """Static metadata for a node label: axis, allowed layers, default layer, display name."""

    __slots__ = ("axis", "default_layer", "display_en", "display_pt", "label", "layers")

    def __init__(
        self,
        label: NodeLabel,
        axis: Axis,
        layers: tuple[Layer, ...],
        default_layer: Layer | None,
        display_pt: str,
        display_en: str,
    ) -> None:
        self.label = label
        self.axis = axis
        self.layers = layers
        self.default_layer = default_layer
        self.display_pt = display_pt
        self.display_en = display_en


# Tabela 7 (thesis). Display names carry the Portuguese accents the ASCII labels drop.
LABEL_SPECS: Final[dict[NodeLabel, LabelSpec]] = {
    s.label: s
    for s in (
        LabelSpec(NodeLabel.ORGANIZACAO, Axis.ORG, (), None, "Organização", "Organization"),
        LabelSpec(NodeLabel.DOMINIO, Axis.DIGITAL, (Layer.TI,), Layer.TI, "Domínio", "Domain"),
        LabelSpec(
            NodeLabel.ENDERECO_IP, Axis.DIGITAL, (Layer.TI,), Layer.TI, "Endereço IP", "IP address"
        ),
        LabelSpec(NodeLabel.SERVICO, Axis.DIGITAL, (Layer.TI,), Layer.TI, "Serviço", "Service"),
        LabelSpec(
            NodeLabel.SOFTWARE, Axis.DIGITAL, (Layer.TI, Layer.TO), Layer.TI, "Software", "Software"
        ),
        LabelSpec(
            NodeLabel.DISPOSITIVO_INDUSTRIAL,
            Axis.DIGITAL,
            (Layer.TO,),
            Layer.TO,
            "Dispositivo Industrial",
            "Industrial device",
        ),
        LabelSpec(NodeLabel.CVE, Axis.DIGITAL, (Layer.TI, Layer.TO), Layer.TI, "CVE", "CVE"),
        LabelSpec(NodeLabel.FUNCIONARIO, Axis.HUMANO, (), None, "Funcionário", "Employee"),
        LabelSpec(
            NodeLabel.CREDENCIAL_VAZADA,
            Axis.HUMANO,
            (),
            None,
            "Credencial Vazada",
            "Leaked credential",
        ),
        LabelSpec(
            NodeLabel.INSTALACAO_FISICA,
            Axis.FISICO,
            (),
            None,
            "Instalação Física",
            "Physical facility",
        ),
        LabelSpec(NodeLabel.FORNECEDOR, Axis.ECOSSISTEMA, (), None, "Fornecedor", "Supplier"),
    )
}


class RelType(StrEnum):
    """Relationship types. The first block is the thesis list (Section 5.2, exact)."""

    TRABALHA_EM = "TRABALHA_EM"
    RESOLVE_PARA = "RESOLVE_PARA"
    EXPOE = "EXPOE"
    HOSPEDA = "HOSPEDA"
    POSSUI_VULNERABILIDADE = "POSSUI_VULNERABILIDADE"
    POSSUI_CREDENCIAL_EXPOSTA = "POSSUI_CREDENCIAL_EXPOSTA"
    VIABILIZA_ACESSO_A = "VIABILIZA_ACESSO_A"
    ABRIGA = "ABRIGA"
    MANTEM_ACESSO_A = "MANTEM_ACESSO_A"
    OPERA_SOBRE = "OPERA_SOBRE"

    # EXTENSION (brief, Section 5.2 "anchoring extensions"): make the graph traversable from
    # the project seed for the path metric.
    PERTENCE_A = "PERTENCE_A"
    FORNECE_PARA = "FORNECE_PARA"

    # EXTENSION (approved 2026-09-16): make every Tabela 8 cross-axis rule reachable by a
    # direct edge. Funcionario->Dispositivo_Industrial and Dominio->Fornecedor have no thesis
    # relationship type.
    OPERA = "OPERA"
    HOSPEDADO_POR = "HOSPEDADO_POR"

    # EXTENSION (approved 2026-09-16, from the reference OSINT.ree export): explicit attack-path
    # edges so a *directed* seed-to-OT path can exist. With thesis edges only, Organizacao is a
    # sink and OPERA_SOBRE points away from the device, so no directed path is possible.
    PIVOT_LATERAL = "PIVOT_LATERAL"
    ACESSA_DIRETAMENTE = "ACESSA_DIRETAMENTE"


THESIS_REL_TYPES: Final[frozenset[RelType]] = frozenset(
    {
        RelType.TRABALHA_EM,
        RelType.RESOLVE_PARA,
        RelType.EXPOE,
        RelType.HOSPEDA,
        RelType.POSSUI_VULNERABILIDADE,
        RelType.POSSUI_CREDENCIAL_EXPOSTA,
        RelType.VIABILIZA_ACESSO_A,
        RelType.ABRIGA,
        RelType.MANTEM_ACESSO_A,
        RelType.OPERA_SOBRE,
    }
)

EXTENSION_REL_TYPES: Final[frozenset[RelType]] = frozenset(set(RelType) - THESIS_REL_TYPES)

# Allowed (source label, relationship, target label) triples. CRUD rejects anything else.
ALLOWED_EDGES: Final[frozenset[tuple[NodeLabel, RelType, NodeLabel]]] = frozenset(
    {
        # --- thesis list (Section 5.2) ---
        (NodeLabel.FUNCIONARIO, RelType.TRABALHA_EM, NodeLabel.ORGANIZACAO),
        (NodeLabel.DOMINIO, RelType.RESOLVE_PARA, NodeLabel.ENDERECO_IP),
        (NodeLabel.ENDERECO_IP, RelType.EXPOE, NodeLabel.SERVICO),
        (NodeLabel.SERVICO, RelType.HOSPEDA, NodeLabel.SOFTWARE),
        (NodeLabel.SOFTWARE, RelType.POSSUI_VULNERABILIDADE, NodeLabel.CVE),
        (NodeLabel.FUNCIONARIO, RelType.POSSUI_CREDENCIAL_EXPOSTA, NodeLabel.CREDENCIAL_VAZADA),
        (NodeLabel.CREDENCIAL_VAZADA, RelType.VIABILIZA_ACESSO_A, NodeLabel.SERVICO),
        (NodeLabel.INSTALACAO_FISICA, RelType.ABRIGA, NodeLabel.DISPOSITIVO_INDUSTRIAL),
        (NodeLabel.FORNECEDOR, RelType.MANTEM_ACESSO_A, NodeLabel.ENDERECO_IP),
        (NodeLabel.DISPOSITIVO_INDUSTRIAL, RelType.OPERA_SOBRE, NodeLabel.SOFTWARE),
        # --- EXTENSION: anchoring (brief, Section 5.2) ---
        (NodeLabel.DOMINIO, RelType.PERTENCE_A, NodeLabel.ORGANIZACAO),
        (NodeLabel.INSTALACAO_FISICA, RelType.PERTENCE_A, NodeLabel.ORGANIZACAO),
        (NodeLabel.FORNECEDOR, RelType.FORNECE_PARA, NodeLabel.ORGANIZACAO),
        # --- EXTENSION: Tabela 8 reachability ---
        (NodeLabel.FUNCIONARIO, RelType.OPERA, NodeLabel.DISPOSITIVO_INDUSTRIAL),
        (NodeLabel.DOMINIO, RelType.HOSPEDADO_POR, NodeLabel.FORNECEDOR),
        # --- EXTENSION: attack-path edges from the reference export ---
        (NodeLabel.SERVICO, RelType.PIVOT_LATERAL, NodeLabel.SERVICO),
        (NodeLabel.SERVICO, RelType.ACESSA_DIRETAMENTE, NodeLabel.DISPOSITIVO_INDUSTRIAL),
    }
)


def allowed_rel_types(source: NodeLabel, target: NodeLabel) -> list[RelType]:
    """Relationship types permitted between two labels, in enum order."""
    return [r for r in RelType if (source, r, target) in ALLOWED_EDGES]


def is_allowed_edge(source: NodeLabel, rel: RelType, target: NodeLabel) -> bool:
    return (source, rel, target) in ALLOWED_EDGES


# ---------------------------------------------------------------------------------------
# Constraints and indexes (brief, Section 5.5). Idempotent: every statement uses IF NOT EXISTS.
# ---------------------------------------------------------------------------------------

_NODE_SCHEMA: tuple[tuple[str, str], ...] = (
    (
        "entity_id_unique",
        f"CREATE CONSTRAINT entity_id_unique IF NOT EXISTS "
        f"FOR (n:{ENTITY_LABEL}) REQUIRE n.id IS UNIQUE",
    ),
    (
        "entity_project_id",
        f"CREATE INDEX entity_project_id IF NOT EXISTS FOR (n:{ENTITY_LABEL}) ON (n.project_id)",
    ),
    (
        "dominio_name",
        f"CREATE INDEX dominio_name IF NOT EXISTS FOR (n:{NodeLabel.DOMINIO}) ON (n.name)",
    ),
    (
        "endereco_ip_address",
        f"CREATE INDEX endereco_ip_address IF NOT EXISTS "
        f"FOR (n:{NodeLabel.ENDERECO_IP}) ON (n.address)",
    ),
    (
        "cve_cve_id",
        f"CREATE INDEX cve_cve_id IF NOT EXISTS FOR (n:{NodeLabel.CVE}) ON (n.cve_id)",
    ),
    (
        "project_id_unique",
        f"CREATE CONSTRAINT project_id_unique IF NOT EXISTS "
        f"FOR (p:{PROJECT_LABEL}) REQUIRE p.id IS UNIQUE",
    ),
    (
        "candidate_id_unique",
        f"CREATE CONSTRAINT candidate_id_unique IF NOT EXISTS "
        f"FOR (c:{CANDIDATE_LABEL}) REQUIRE c.id IS UNIQUE",
    ),
    (
        "candidate_project_id",
        f"CREATE INDEX candidate_project_id IF NOT EXISTS "
        f"FOR (c:{CANDIDATE_LABEL}) ON (c.project_id)",
    ),
)

# Relationship ids are looked up on edit/delete; one index per type keeps that cheap.
_REL_SCHEMA: tuple[tuple[str, str], ...] = tuple(
    (
        f"rel_{r.lower()}_id",
        f"CREATE INDEX rel_{r.lower()}_id IF NOT EXISTS FOR ()-[e:{r}]-() ON (e.id)",
    )
    for r in RelType
)

SCHEMA_STATEMENTS: Final[tuple[tuple[str, str], ...]] = (*_NODE_SCHEMA, *_REL_SCHEMA)

SCHEMA_NAMES: Final[frozenset[str]] = frozenset(name for name, _ in SCHEMA_STATEMENTS)
