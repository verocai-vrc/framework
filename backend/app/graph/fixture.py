"""Fixture project for ``osintree seed`` and the end-to-end tests (brief, Sprint 4).

A *fictional* utility company: ``.test`` domains (RFC 6761), documentation IP ranges
(RFC 5737), an invented PLC and HMI product, and one real, public, widely cited CVE on a
real VPN product so the CVE correlation looks like a genuine finding. Nothing here refers
to an actual organization; the graph is engineered so all three thesis criteria pass:

* 4 validation axes covered (DIGITAL, HUMANO, FISICO, ECOSSISTEMA);
* a directed seed -> OT path: Organizacao <- Dominio -> IP -> Servico -> PLC (5 hops), plus
  a cheaper weighted route through the VPN pivot that the Dijkstra variant prefers;
* every Tabela 8 row fires at least once (T8.1 .. T8.6).
"""

from __future__ import annotations

from typing import Any

from app.db.driver import Neo4jClient
from app.db.schema import Layer, NodeLabel, RelType
from app.graph import crud, projects
from app.models.edges import EdgeCreate
from app.models.nodes import NodeCreate
from app.models.projects import ProjectCreate, ProjectOut

FIXTURE_NAME = "Example Utility (fixture)"
FIXTURE_ORG = "Example Utility Co."
FIXTURE_SEED = "example-utility.test"

# (key, label, attrs, extra NodeCreate fields)
FIXTURE_NODES: tuple[tuple[str, NodeLabel, dict[str, Any], dict[str, Any]], ...] = (
    # --- DIGITAL / TI ---
    ("dom_root", NodeLabel.DOMINIO, {"name": FIXTURE_SEED}, {"notes": "Seed domain."}),
    ("dom_vpn", NodeLabel.DOMINIO, {"name": f"vpn.{FIXTURE_SEED}"}, {}),
    ("dom_scada", NodeLabel.DOMINIO, {"name": f"scada.{FIXTURE_SEED}"}, {}),
    (
        "dom_hml",
        NodeLabel.DOMINIO,
        {"name": f"hml.{FIXTURE_SEED}"},
        {"notes": "Homologation environment hosted by a third party (Tabela 8, row 6)."},
    ),
    ("ip_vpn", NodeLabel.ENDERECO_IP, {"address": "192.0.2.10", "asn": 64500}, {}),
    ("ip_scada", NodeLabel.ENDERECO_IP, {"address": "192.0.2.20", "asn": 64500}, {}),
    ("ip_web", NodeLabel.ENDERECO_IP, {"address": "198.51.100.5", "asn": 64501}, {}),
    ("svc_vpn", NodeLabel.SERVICO, {"port": 443, "service": "SSL VPN"}, {}),
    ("svc_ssh", NodeLabel.SERVICO, {"port": 22, "service": "ssh"}, {}),
    ("svc_web", NodeLabel.SERVICO, {"port": 80, "service": "http"}, {}),
    (
        "sw_fortios",
        NodeLabel.SOFTWARE,
        {"product": "FortiOS", "vendor": "Fortinet", "version": "6.0.4"},
        {"layer": Layer.TI},
    ),
    (
        "sw_hmi",
        NodeLabel.SOFTWARE,
        {"product": "Example HMI Suite", "vendor": "Example Automation", "version": "3.1"},
        {"layer": Layer.TI, "notes": "Fictional SCADA HMI server product."},
    ),
    (
        "cve_fortios",
        NodeLabel.CVE,
        {"cve_id": "CVE-2018-13379", "cvss": 9.8, "severity": "CRITICAL"},
        {"notes": "Path traversal in the FortiOS SSL VPN web portal (public, widely exploited)."},
    ),
    (
        "cve_hmi",
        NodeLabel.CVE,
        {"cve_id": "CVE-2099-0001", "cvss": 8.1, "severity": "HIGH"},
        {"notes": "Illustrative placeholder identifier for the fictional HMI product."},
    ),
    # --- DIGITAL / TO ---
    (
        "plc",
        NodeLabel.DISPOSITIVO_INDUSTRIAL,
        {
            "vendor": "Example Automation",
            "model": "PLC-1000",
            "device_type": "PLC",
            "protocol": "Modbus/TCP",
        },
        {},
    ),
    # --- HUMANO ---
    (
        "emp",
        NodeLabel.FUNCIONARIO,
        {"name": "A. Operator", "role": "SCADA operator", "email": f"a.operator@{FIXTURE_SEED}"},
        {},
    ),
    (
        "cred",
        NodeLabel.CREDENCIAL_VAZADA,
        {
            "email": f"a.operator@{FIXTURE_SEED}",
            "leak_name": "example-combolist-2024",
            "secret_type": "plaintext",
        },
        {},
    ),
    # --- FISICO ---
    (
        "site",
        NodeLabel.INSTALACAO_FISICA,
        {
            "name": "Substation North",
            "facility_type": "substation",
            "latitude": 0.0,
            "longitude": 0.0,
        },
        {},
    ),
    # --- ECOSSISTEMA ---
    (
        "sup_telecom",
        NodeLabel.FORNECEDOR,
        {
            "name": "Example Telecom S.A.",
            "service_provided": "WAN / remote maintenance",
            "asn": 64500,
        },
        {},
    ),
    (
        "sup_cloud",
        NodeLabel.FORNECEDOR,
        {"name": "Cloud Host Ltd.", "service_provided": "homologation hosting"},
        {},
    ),
)

# (source key, rel, target key, extra EdgeCreate fields). "org" is the project anchor.
FIXTURE_EDGES: tuple[tuple[str, RelType, str, dict[str, Any]], ...] = (
    # anchoring (extensions)
    ("dom_root", RelType.PERTENCE_A, "org", {}),
    ("dom_vpn", RelType.PERTENCE_A, "org", {}),
    ("dom_scada", RelType.PERTENCE_A, "org", {}),
    ("dom_hml", RelType.PERTENCE_A, "org", {}),
    ("site", RelType.PERTENCE_A, "org", {}),
    ("sup_telecom", RelType.FORNECE_PARA, "org", {}),
    ("sup_cloud", RelType.FORNECE_PARA, "org", {}),
    ("emp", RelType.TRABALHA_EM, "org", {}),
    # digital chain
    ("dom_root", RelType.RESOLVE_PARA, "ip_web", {}),
    ("dom_vpn", RelType.RESOLVE_PARA, "ip_vpn", {}),
    ("dom_scada", RelType.RESOLVE_PARA, "ip_scada", {}),
    ("ip_web", RelType.EXPOE, "svc_web", {}),
    ("ip_vpn", RelType.EXPOE, "svc_vpn", {}),
    # Hardened bastion: reaching the gateway shell from the outside is expensive.
    ("ip_scada", RelType.EXPOE, "svc_ssh", {"weight": 5.0}),
    ("svc_vpn", RelType.HOSPEDA, "sw_fortios", {}),
    ("svc_ssh", RelType.HOSPEDA, "sw_hmi", {}),
    ("sw_fortios", RelType.POSSUI_VULNERABILIDADE, "cve_fortios", {}),
    ("sw_hmi", RelType.POSSUI_VULNERABILIDADE, "cve_hmi", {}),
    # attack-path extensions: VPN pivot is cheap thanks to the CVE + leaked credential
    ("svc_vpn", RelType.PIVOT_LATERAL, "svc_ssh", {"weight": 1.0}),
    ("svc_ssh", RelType.ACESSA_DIRETAMENTE, "plc", {}),
    # OT
    ("plc", RelType.OPERA_SOBRE, "sw_hmi", {}),  # T8.2
    ("site", RelType.ABRIGA, "plc", {}),  # T8.3
    # human
    ("emp", RelType.POSSUI_CREDENCIAL_EXPOSTA, "cred", {}),
    ("cred", RelType.VIABILIZA_ACESSO_A, "svc_vpn", {}),  # T8.1
    ("emp", RelType.OPERA, "plc", {}),  # T8.4
    # ecosystem
    ("sup_telecom", RelType.MANTEM_ACESSO_A, "ip_scada", {}),  # T8.5
    ("dom_hml", RelType.HOSPEDADO_POR, "sup_cloud", {}),  # T8.6
)


async def seed_fixture(db: Neo4jClient, name: str = FIXTURE_NAME) -> ProjectOut:
    """Create the fixture project through the same CRUD path the UI uses, so every node
    and edge is validated by the schema rules. Returns the project."""
    project = await projects.create_project(
        db, ProjectCreate(name=name, org_name=FIXTURE_ORG, seed_domain=FIXTURE_SEED)
    )
    assert project.root_node_id is not None
    ids: dict[str, str] = {"org": project.root_node_id}
    for key, label, attrs, extra in FIXTURE_NODES:
        node = await crud.create_node(db, project.id, NodeCreate(label=label, attrs=attrs, **extra))
        ids[key] = node.id
    for src, rel, dst, extra in FIXTURE_EDGES:
        await crud.create_edge(
            db, project.id, EdgeCreate(source_id=ids[src], target_id=ids[dst], rel=rel, **extra)
        )
    return await projects.get_project(db, project.id)
