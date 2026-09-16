"""Shodan InternetDB collector — exposed ports, CPEs, CVEs and ICS tags for one IP address
(thesis family: Internet-wide scan index; Section 3 of the methodology lists Shodan as a
passive third-party source of exposed services).

InternetDB (``https://internetdb.shodan.io/{ip}``) is Shodan's free, keyless summary
endpoint. It answers from Shodan's own scan corpus, so the target is never contacted, but
the data is only as fresh as Shodan's last pass. Produces:

* an enrichment of the seed ``Endereco_IP`` (ports, tags, hostnames, vulnerabilities);
* one ``Servico`` per open port, attached with ``EXPOE``;
* one ``Software`` per CPE, attached with ``HOSPEDA`` to an already-approved ``Servico`` of
  this address when a well-known port matches the product (otherwise left for the analyst);
* ``CVE`` candidates for every listed vulnerability, attached with ``POSSUI_VULNERABILIDADE``
  to ``Software`` nodes already reachable from the address (``EXPOE``/``HOSPEDA``);
* a ``Dispositivo_Industrial`` (layer TO) when Shodan tags the host ``ics`` or an OT
  protocol port is open, attached with the ``ACESSA_DIRETAMENTE`` extension edge to the
  matching ``Servico`` when that service is already in the graph;
* in-scope ``Dominio`` candidates for reverse hostnames, attached with ``RESOLVE_PARA``.

Because edges can only point at nodes already in the graph, a second run after approving the
services/software wires up the ``HOSPEDA`` / ``POSSUI_VULNERABILIDADE`` edges the first run
could not express. The review queue de-duplicates what is already there.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from app.collectors.base import (
    Collector,
    CollectorInputError,
    Finding,
    FindingEdge,
    InputKind,
    RunContext,
)
from app.db.schema import Axis, Layer, NodeLabel, RelType
from app.models.nodes import NodeOut

INTERNETDB = "https://internetdb.shodan.io/{ip}"

# IANA/common service names for ports (only used to title the Servico candidate).
PORT_SERVICES: dict[int, str] = {
    21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns", 80: "http", 110: "pop3",
    111: "rpcbind", 123: "ntp", 135: "msrpc", 139: "netbios-ssn", 143: "imap", 161: "snmp",
    389: "ldap", 443: "https", 445: "smb", 465: "smtps", 500: "isakmp", 587: "submission",
    631: "ipp", 636: "ldaps", 873: "rsync", 993: "imaps", 995: "pop3s", 1194: "openvpn",
    1433: "mssql", 1521: "oracle", 1723: "pptp", 1883: "mqtt", 2049: "nfs", 2375: "docker",
    3306: "mysql", 3389: "rdp", 5432: "postgresql", 5900: "vnc", 5985: "winrm", 6379: "redis",
    8080: "http-alt", 8443: "https-alt", 8883: "mqtts", 9200: "elasticsearch", 27017: "mongodb",
}  # fmt: skip

# OT / ICS protocol ports (thesis Section 3: passive identification of industrial services).
OT_PORTS: dict[int, str] = {
    102: "S7comm (Siemens)",
    502: "Modbus/TCP",
    1911: "Niagara Fox",
    4911: "Niagara Fox (TLS)",
    2222: "EtherNet/IP (explicit)",
    44818: "EtherNet/IP",
    20000: "DNP3",
    47808: "BACnet/IP",
    4840: "OPC UA",
    5007: "Mitsubishi MELSEC",
    9600: "Omron FINS",
    18245: "GE SRTP",
    1962: "PCWorx",
    20547: "ProConOS",
    2404: "IEC 60870-5-104",
    34962: "PROFINET",
    34980: "EtherCAT",
}

# Product keyword -> ports it conventionally listens on, to attach a CPE to a service.
PRODUCT_PORTS: dict[str, tuple[int, ...]] = {
    "openssh": (22,),
    "dropbear": (22,),
    "nginx": (80, 443, 8080, 8443),
    "apache": (80, 443, 8080, 8443),
    "http_server": (80, 443, 8080, 8443),
    "iis": (80, 443),
    "lighttpd": (80, 443),
    "tomcat": (8080, 8443, 80, 443),
    "openssl": (443, 8443),
    "exim": (25, 587, 465),
    "postfix": (25, 587, 465),
    "sendmail": (25, 587),
    "dovecot": (143, 993, 110, 995),
    "bind": (53,),
    "mysql": (3306,),
    "mariadb": (3306,),
    "postgresql": (5432,),
    "redis": (6379,),
    "mongodb": (27017,),
    "elasticsearch": (9200,),
    "vsftpd": (21,),
    "proftpd": (21,),
    "pure-ftpd": (21,),
    "samba": (445, 139),
    "vnc": (5900,),
    "mosquitto": (1883, 8883),
    "php": (80, 443, 8080),
}

_CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.I)
_HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\.)+[a-z0-9-]{2,63}$")


def parse_cpe(cpe: str) -> dict[str, str] | None:
    """Split ``cpe:/a:vendor:product:version`` or ``cpe:2.3:a:vendor:product:version:*``."""
    cpe = cpe.strip()
    if cpe.startswith("cpe:2.3:"):
        parts = cpe.split(":")[2:]
    elif cpe.startswith("cpe:/"):
        parts = cpe[5:].split(":")
    else:
        return None
    if len(parts) < 3 or not parts[2]:
        return None
    vendor, product = parts[1], parts[2]
    version = parts[3] if len(parts) > 3 and parts[3] not in ("", "*", "-") else ""
    return {"part": parts[0], "vendor": vendor, "product": product, "version": version}


def parse_internetdb(data: dict[str, Any]) -> dict[str, Any]:
    ports = sorted({int(p) for p in data.get("ports") or [] if str(p).isdigit()})
    cpes = [c for c in (parse_cpe(str(x)) for x in data.get("cpes") or []) if c]
    vulns = sorted({str(v).upper() for v in data.get("vulns") or [] if _CVE_RE.match(str(v))})
    tags = sorted({str(t).lower() for t in data.get("tags") or []})
    hosts = sorted(
        {
            str(h).strip().lower().rstrip(".")
            for h in data.get("hostnames") or []
            if _HOST_RE.match(str(h).strip().lower().rstrip("."))
        }
    )
    return {
        "ip": str(data.get("ip") or ""),
        "ports": ports,
        "cpes": cpes,
        "vulns": vulns,
        "tags": tags,
        "hostnames": hosts,
        "ot_ports": {p: OT_PORTS[p] for p in ports if p in OT_PORTS},
    }


def guess_ports(cpe: dict[str, str], open_ports: list[int]) -> list[int]:
    """Ports among ``open_ports`` that a product with this CPE conventionally listens on."""
    key = f"{cpe['vendor']} {cpe['product']}".lower()
    for needle, ports in PRODUCT_PORTS.items():
        if needle in key:
            return [p for p in ports if p in open_ports]
    return []


class InternetDbCollector(Collector):
    name = "internetdb"
    description = "Exposed ports, CPEs, CVEs and ICS tags for an IP (Shodan InternetDB, keyless)"
    source_family = "Scan index (Shodan)"
    axis = Axis.DIGITAL
    input_kind = InputKind.IP
    input_label = NodeLabel.ENDERECO_IP

    async def _software_behind(self, ctx: RunContext, ip_node: NodeOut) -> list[NodeOut]:
        rows = await ctx.db.run(
            f"MATCH (ip {{id: $id}})-[:{RelType.EXPOE}]->(:{NodeLabel.SERVICO})"
            f"-[:{RelType.HOSPEDA}]->(s:{NodeLabel.SOFTWARE}) RETURN DISTINCT s.id AS id",
            {"id": ip_node.id},
            readonly=True,
        )
        ids = {r["id"] for r in rows}
        return [n for n in ctx.nodes if n.id in ids]

    async def _services_of(self, ctx: RunContext, ip_node: NodeOut) -> dict[int, NodeOut]:
        rows = await ctx.db.run(
            f"MATCH (ip {{id: $id}})-[:{RelType.EXPOE}]->(s:{NodeLabel.SERVICO}) RETURN s.id AS id",
            {"id": ip_node.id},
            readonly=True,
        )
        ids = {r["id"] for r in rows}
        out: dict[int, NodeOut] = {}
        for n in ctx.nodes:
            if n.id in ids and str(n.attrs.get("port", "")).isdigit():
                out[int(n.attrs["port"])] = n
        return out

    async def collect(self, seed: str, ctx: RunContext) -> list[Finding]:
        try:
            ip = str(ipaddress.ip_address(seed.strip()))
        except ValueError as exc:
            raise CollectorInputError(
                f"'{seed}' is not an IP address (InternetDB has no ASN lookup)"
            ) from exc
        resp = await ctx.http.get(INTERNETDB.format(ip=ip))
        if resp.status_code == 404:
            return []  # Shodan has no record of this address
        if resp.status_code != 200:
            raise RuntimeError(f"InternetDB returned HTTP {resp.status_code}")
        info = parse_internetdb(resp.json())

        ip_node = ctx.find_node(NodeLabel.ENDERECO_IP, "address", ip)
        services = await self._services_of(ctx, ip_node) if ip_node else {}
        software = await self._software_behind(ctx, ip_node) if ip_node else []
        root = ctx.root
        findings: list[Finding] = []
        src = f"internetdb:{ip}"

        if ip_node is not None:
            findings.append(
                Finding(
                    kind="node_update",
                    target_id=ip_node.id,
                    label=NodeLabel.ENDERECO_IP,
                    metadata={
                        "shodan_ports": ", ".join(map(str, info["ports"])),
                        "shodan_tags": ", ".join(info["tags"]),
                        "shodan_hostnames": ", ".join(info["hostnames"])[:500],
                        "shodan_vulns": ", ".join(info["vulns"])[:500],
                        "shodan_vulns_count": str(len(info["vulns"])),
                        **(
                            {
                                "shodan_ot_ports": ", ".join(
                                    f"{p} {n}" for p, n in info["ot_ports"].items()
                                )
                            }
                            if info["ot_ports"]
                            else {}
                        ),
                    },
                    dedupe_key=f"{src}:ip",
                    evidence=(
                        f"{len(info['ports'])} port(s) · {len(info['cpes'])} CPE(s) · "
                        f"{len(info['vulns'])} CVE(s)"
                        + (f" · tags: {', '.join(info['tags'])}" if info["tags"] else "")
                    ),
                    raw={k: info[k] for k in ("ports", "tags", "hostnames", "vulns")},
                )
            )

        for port in info["ports"]:
            if port in services:
                continue
            service = OT_PORTS.get(port, PORT_SERVICES.get(port))
            edges = (
                [FindingEdge(rel=RelType.EXPOE, other_id=ip_node.id, direction="in")]
                if ip_node
                else []
            )
            findings.append(
                Finding(
                    label=NodeLabel.SERVICO,
                    attrs={
                        "port": port,
                        "protocol": "tcp",
                        **({"service": service} if service else {}),
                    },
                    metadata={
                        "shodan_ip": ip,
                        **({"ot_protocol": OT_PORTS[port]} if port in OT_PORTS else {}),
                    },
                    layer=Layer.TO if port in OT_PORTS else Layer.TI,
                    edges=edges,
                    dedupe_key=f"{src}:port={port}",
                    evidence=f"port {port}/tcp open on {ip}"
                    + (f" — {OT_PORTS[port]} (OT protocol)" if port in OT_PORTS else ""),
                    raw={"port": port},
                )
            )

        for cpe in info["cpes"]:
            edges = [
                FindingEdge(rel=RelType.HOSPEDA, other_id=services[p].id, direction="in")
                for p in guess_ports(cpe, info["ports"])
                if p in services
            ][:1]
            existing = ctx.find_node(NodeLabel.SOFTWARE, "product", cpe["product"])
            if existing is not None and (
                not cpe["version"] or str(existing.attrs.get("version") or "") == cpe["version"]
            ):
                if edges:
                    findings.append(
                        Finding(
                            kind="edge",
                            target_id=existing.id,
                            label=NodeLabel.SOFTWARE,
                            edges=edges,
                            dedupe_key=f"{src}:edge:{edges[0].other_id}->{existing.id}",
                            evidence=f"{cpe['product']} seen on {ip} (CPE)",
                        )
                    )
                continue
            cpe23 = (
                f"cpe:2.3:{cpe['part']}:{cpe['vendor']}:{cpe['product']}:{cpe['version'] or '*'}"
            )
            findings.append(
                Finding(
                    label=NodeLabel.SOFTWARE,
                    attrs={
                        "product": cpe["product"],
                        "vendor": cpe["vendor"],
                        **({"version": cpe["version"]} if cpe["version"] else {}),
                        **({"cpe": cpe23} if cpe["version"] else {}),
                    },
                    metadata={"shodan_ip": ip, "shodan_cpe": cpe23},
                    edges=edges,
                    dedupe_key=f"{src}:cpe={cpe23}",
                    evidence=f"CPE {cpe23} on {ip}"
                    + ("" if edges else " · attach to a Servico after approval"),
                    raw=cpe,
                )
            )

        for cve_id in info["vulns"]:
            edges = [
                FindingEdge(rel=RelType.POSSUI_VULNERABILIDADE, other_id=s.id, direction="in")
                for s in software
            ]
            existing = ctx.find_node(NodeLabel.CVE, "cve_id", cve_id)
            if existing is not None:
                if edges:
                    findings.append(
                        Finding(
                            kind="edge",
                            target_id=existing.id,
                            label=NodeLabel.CVE,
                            edges=edges,
                            dedupe_key=f"{src}:edge:cve={cve_id}",
                            evidence=f"{cve_id} reported by Shodan for {ip}",
                        )
                    )
                continue
            findings.append(
                Finding(
                    label=NodeLabel.CVE,
                    attrs={"cve_id": cve_id},
                    metadata={"shodan_ip": ip, "shodan_vuln_basis": "banner/CPE match by Shodan"},
                    edges=edges,
                    dedupe_key=f"CVE:cve_id={cve_id}",
                    evidence=f"{cve_id} reported by Shodan for {ip}"
                    + ("" if edges else " · run nvd on the Software to score it"),
                    raw={"cve_id": cve_id},
                )
            )

        if "ics" in info["tags"] or info["ot_ports"]:
            protocols = ", ".join(info["ot_ports"].values())
            vendor = next(
                (
                    c["vendor"]
                    for c in info["cpes"]
                    if c["part"] in ("h", "o")
                    or any(
                        k in c["vendor"]
                        for k in ("siemens", "schneider", "rockwell", "abb", "honeywell")
                    )
                ),
                None,
            )
            edges = [
                FindingEdge(rel=RelType.ACESSA_DIRETAMENTE, other_id=services[p].id, direction="in")
                for p in info["ot_ports"]
                if p in services
            ]
            findings.append(
                Finding(
                    label=NodeLabel.DISPOSITIVO_INDUSTRIAL,
                    attrs={
                        **({"vendor": vendor} if vendor else {}),
                        "device_type": "Internet-exposed ICS host",
                        **({"protocol": protocols} if protocols else {}),
                    },
                    title=f"ICS host {ip}",
                    metadata={"shodan_ip": ip, "shodan_tags": ", ".join(info["tags"])},
                    layer=Layer.TO,
                    edges=edges,
                    dedupe_key=f"{src}:ics",
                    evidence=f"Shodan tags {ip} as ICS"
                    + (f" · OT ports: {protocols}" if protocols else ""),
                    raw={"tags": info["tags"], "ot_ports": info["ot_ports"]},
                )
            )

        seed_domain = (ctx.project.seed_domain or "").lower()
        for host in info["hostnames"]:
            if not seed_domain or not (host == seed_domain or host.endswith("." + seed_domain)):
                continue
            edges = []
            if ip_node:
                edges.append(FindingEdge(rel=RelType.RESOLVE_PARA, other_id=ip_node.id))
            if root:
                edges.append(FindingEdge(rel=RelType.PERTENCE_A, other_id=root.id))
            existing = ctx.find_node(NodeLabel.DOMINIO, "name", host)
            if existing is not None:
                if ip_node:
                    findings.append(
                        Finding(
                            kind="edge",
                            target_id=existing.id,
                            label=NodeLabel.DOMINIO,
                            edges=[FindingEdge(rel=RelType.RESOLVE_PARA, other_id=ip_node.id)],
                            dedupe_key=f"{src}:edge:{existing.id}->{ip_node.id}",
                            evidence=f"Shodan reverse hostname {host} → {ip}",
                        )
                    )
                continue
            findings.append(
                Finding(
                    label=NodeLabel.DOMINIO,
                    attrs={"name": host},
                    metadata={"shodan_ip": ip},
                    edges=edges,
                    dedupe_key=f"Dominio:name={host}",
                    evidence=f"Shodan reverse hostname for {ip}",
                    raw={"hostname": host},
                )
            )
        return findings
