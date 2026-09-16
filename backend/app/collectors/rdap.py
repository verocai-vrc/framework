"""RDAP collector — registration data for IP networks and ASNs (thesis family: RDAP/WHOIS).

Resolves the authoritative RDAP server through the IANA bootstrap files (cached), then
queries ``/ip/{address}`` or ``/autnum/{asn}``. Third-party registries only; the target is
never contacted. Produces an enrichment of the ``Endereco_IP`` node (range, registrant,
country, origin ASN) and a ``Fornecedor`` finding for the registrant organisation, linked
with ``MANTEM_ACESSO_A`` to the address.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from app.collectors.base import (
    Collector,
    CollectorInputError,
    Finding,
    FindingEdge,
    InputKind,
    RunContext,
)
from app.db.schema import Axis, NodeLabel, RelType

IANA_BOOTSTRAP = {
    "ipv4": "https://data.iana.org/rdap/ipv4.json",
    "ipv6": "https://data.iana.org/rdap/ipv6.json",
    "asn": "https://data.iana.org/rdap/asn.json",
}
RDAP_ORG_FALLBACK = "https://rdap.org/"


def pick_service(bootstrap: dict[str, Any], resource: str, kind: str) -> str | None:
    """Base URL of the RDAP service responsible for ``resource`` (an IP or an ASN number)."""
    for entry, urls in bootstrap.get("services", []):
        for pattern in entry:
            if kind == "asn":
                lo, _, hi = pattern.partition("-")
                if int(lo) <= int(resource) <= int(hi or lo):
                    return _https_first(urls)
            elif ipaddress.ip_address(resource) in ipaddress.ip_network(pattern, strict=False):
                return _https_first(urls)
    return None


def _https_first(urls: list[str]) -> str:
    for u in urls:
        if u.startswith("https://"):
            return u if u.endswith("/") else u + "/"
    return urls[0] if urls[0].endswith("/") else urls[0] + "/"


def vcard_fn(entity: dict[str, Any]) -> str | None:
    for item in (entity.get("vcardArray") or [None, []])[1]:
        if item and item[0] == "fn" and len(item) > 3 and item[3]:
            return str(item[3]).strip()
    return None


def registrant(data: dict[str, Any]) -> dict[str, str | None]:
    """Best registrant/holder entity of an RDAP object: name, handle, kind."""
    entities = data.get("entities") or []
    ranked = sorted(
        entities,
        key=lambda e: 0 if "registrant" in (e.get("roles") or []) else 1,
    )
    for e in ranked:
        name = vcard_fn(e) or e.get("handle")
        if name:
            kind = next(
                (str(i[3]) for i in (e.get("vcardArray") or [None, []])[1] if i and i[0] == "kind"),
                None,
            )
            return {"name": name, "handle": e.get("handle"), "kind": kind}
    return {"name": None, "handle": None, "kind": None}


def parse_ip_network(data: dict[str, Any]) -> dict[str, Any]:
    cidrs = [
        f"{c.get('v4prefix') or c.get('v6prefix')}/{c.get('length')}"
        for c in data.get("cidr0_cidrs") or []
    ]
    asns = [str(a) for a in data.get("arin_originas0_originautnums") or []]
    reg = registrant(data)
    return {
        "handle": data.get("handle"),
        "name": data.get("name"),
        "type": data.get("type"),
        "country": data.get("country"),
        "range": f"{data.get('startAddress')} - {data.get('endAddress')}",
        "cidrs": cidrs,
        "origin_asns": asns,
        "registrant": reg,
        "port43": data.get("port43"),
    }


def parse_autnum(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "handle": data.get("handle"),
        "name": data.get("name"),
        "asn": data.get("startAutnum"),
        "country": data.get("country"),
        "registrant": registrant(data),
    }


class RdapCollector(Collector):
    name = "rdap"
    description = "IP network / ASN registration data via RDAP (IANA bootstrap)"
    source_family = "RDAP/WHOIS"
    axis = Axis.ECOSSISTEMA
    input_kind = InputKind.IP
    input_label = NodeLabel.ENDERECO_IP

    async def _bootstrap(self, ctx: RunContext, family: str) -> dict[str, Any]:
        resp = await ctx.http.get(IANA_BOOTSTRAP[family])
        return resp.json() if resp.status_code == 200 else {"services": []}

    async def _rdap(self, ctx: RunContext, base: str | None, path: str) -> dict[str, Any] | None:
        headers = {"Accept": "application/rdap+json, application/json"}
        for candidate in [b for b in (base, RDAP_ORG_FALLBACK) if b]:
            resp = await ctx.http.get(candidate + path, headers=headers)
            if resp.status_code == 200:
                return resp.json()
        return None

    async def collect(self, seed: str, ctx: RunContext) -> list[Finding]:
        seed = seed.strip()
        if seed.upper().startswith("AS") and seed[2:].isdigit():
            return await self._collect_asn(int(seed[2:]), ctx)
        if seed.isdigit():
            return await self._collect_asn(int(seed), ctx)
        try:
            ip = ipaddress.ip_address(seed)
        except ValueError as exc:
            raise CollectorInputError(f"'{seed}' is neither an IP address nor an ASN") from exc
        return await self._collect_ip(str(ip), "ipv6" if ip.version == 6 else "ipv4", ctx)

    async def _collect_ip(self, ip: str, family: str, ctx: RunContext) -> list[Finding]:
        base = pick_service(await self._bootstrap(ctx, family), ip, family)
        data = await self._rdap(ctx, base, f"ip/{ip}")
        if data is None:
            raise RuntimeError(f"no RDAP answer for {ip}")
        net = parse_ip_network(data)
        node = ctx.find_node(NodeLabel.ENDERECO_IP, "address", ip)
        findings: list[Finding] = []

        if node is not None:
            attrs: dict[str, Any] = {}
            if net["country"] and not node.attrs.get("country"):
                attrs["country"] = net["country"]
            if net["origin_asns"] and not node.attrs.get("asn"):
                attrs["asn"] = int(net["origin_asns"][0])
            findings.append(
                Finding(
                    kind="node_update",
                    target_id=node.id,
                    label=NodeLabel.ENDERECO_IP,
                    attrs=attrs,
                    metadata={
                        "rdap_handle": str(net["handle"] or ""),
                        "rdap_network": str(net["name"] or ""),
                        "rdap_range": net["range"],
                        "rdap_cidr": ", ".join(net["cidrs"]),
                        "rdap_type": str(net["type"] or ""),
                        "rdap_registrant": str(net["registrant"]["name"] or ""),
                        "rdap_server": str(base or RDAP_ORG_FALLBACK),
                    },
                    dedupe_key=f"rdap:ip={ip}",
                    evidence=(
                        f"{net['name']} ({net['handle']}) · {net['range']} · "
                        f"registrant {net['registrant']['name']}"
                    ),
                    raw={k: net[k] for k in ("handle", "name", "range", "cidrs", "origin_asns")},
                )
            )

        holder = net["registrant"]["name"]
        if holder:
            existing = ctx.find_node(NodeLabel.FORNECEDOR, "name", holder)
            edges = (
                [FindingEdge(rel=RelType.MANTEM_ACESSO_A, other_id=node.id)]
                if node is not None
                else []
            )
            if existing is not None:
                if edges:
                    findings.append(
                        Finding(
                            kind="edge",
                            target_id=existing.id,
                            label=NodeLabel.FORNECEDOR,
                            edges=edges,
                            dedupe_key=f"rdap:edge:{existing.id}->{node.id}",  # type: ignore[union-attr]
                            evidence=f"{holder} holds the network containing {ip}",
                        )
                    )
            else:
                findings.append(
                    Finding(
                        label=NodeLabel.FORNECEDOR,
                        attrs={
                            "name": holder,
                            "service_provided": "IP network holder (RDAP registrant)",
                            **({"asn": int(net["origin_asns"][0])} if net["origin_asns"] else {}),
                        },
                        metadata={
                            "rdap_handle": str(net["registrant"]["handle"] or ""),
                            "rdap_network": str(net["name"] or ""),
                            "rdap_range": net["range"],
                        },
                        edges=edges,
                        dedupe_key=f"Fornecedor:name={holder}",
                        evidence=f"registrant of {net['name']} ({net['range']}) containing {ip}",
                        raw={"registrant": net["registrant"], "network": net["name"]},
                    )
                )
        return findings

    async def _collect_asn(self, asn: int, ctx: RunContext) -> list[Finding]:
        base = pick_service(await self._bootstrap(ctx, "asn"), str(asn), "asn")
        data = await self._rdap(ctx, base, f"autnum/{asn}")
        if data is None:
            raise RuntimeError(f"no RDAP answer for AS{asn}")
        info = parse_autnum(data)
        holder = info["registrant"]["name"] or info["name"] or f"AS{asn}"
        ips = [n for n in ctx.nodes_with(NodeLabel.ENDERECO_IP) if n.attrs.get("asn") == asn]
        edges = [FindingEdge(rel=RelType.MANTEM_ACESSO_A, other_id=n.id) for n in ips]
        existing = ctx.find_node(NodeLabel.FORNECEDOR, "name", holder)
        if existing is not None:
            return (
                [
                    Finding(
                        kind="edge",
                        target_id=existing.id,
                        label=NodeLabel.FORNECEDOR,
                        edges=edges,
                        dedupe_key=f"rdap:asn-edges:{existing.id}",
                        evidence=(
                            f"AS{asn} ({info['name']}) announces {len(ips)} address(es) "
                            "in the graph"
                        ),
                    )
                ]
                if edges
                else []
            )
        return [
            Finding(
                label=NodeLabel.FORNECEDOR,
                attrs={
                    "name": holder,
                    "asn": asn,
                    "service_provided": f"AS{asn} {info['name'] or ''}".strip(),
                },
                metadata={
                    "rdap_handle": str(info["handle"] or ""),
                    "rdap_as_name": str(info["name"] or ""),
                },
                edges=edges,
                dedupe_key=f"Fornecedor:name={holder}",
                evidence=f"AS{asn} · {info['name']} · registrant {holder}",
                raw={
                    "handle": info["handle"],
                    "name": info["name"],
                    "registrant": info["registrant"],
                },
            )
        ]
