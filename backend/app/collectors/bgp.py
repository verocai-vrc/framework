"""BGP/ASN collector — routing view via the RIPEstat Data API (thesis family: ASN/BGP).

RIPEstat is a free, keyless RIR data service that reports which ASN announces a prefix and
which prefixes an ASN announces. Third-party only; the target is never contacted.
Produces an enrichment of ``Endereco_IP`` (origin ASN, holder, prefix) and ``Fornecedor``
findings for ASN holders, linked with ``MANTEM_ACESSO_A`` to the addresses they announce.
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

RIPESTAT = "https://stat.ripe.net/data/{call}/data.json"


def parse_prefix_overview(data: dict[str, Any]) -> dict[str, Any]:
    d = data.get("data") or {}
    return {
        "prefix": d.get("resource"),
        "announced": bool(d.get("announced")),
        "asns": [
            {"asn": int(a["asn"]), "holder": str(a.get("holder") or "")}
            for a in d.get("asns") or []
        ],
    }


def parse_as_overview(data: dict[str, Any]) -> dict[str, Any]:
    d = data.get("data") or {}
    return {
        "asn": d.get("resource"),
        "holder": str(d.get("holder") or ""),
        "announced": bool(d.get("announced")),
    }


def parse_announced_prefixes(data: dict[str, Any]) -> list[str]:
    d = data.get("data") or {}
    return [str(p["prefix"]) for p in d.get("prefixes") or []]


class BgpCollector(Collector):
    name = "bgp"
    description = "Origin ASN, holder and announced prefixes via RIPEstat"
    source_family = "ASN/BGP"
    axis = Axis.ECOSSISTEMA
    input_kind = InputKind.IP
    input_label = NodeLabel.ENDERECO_IP

    async def _call(self, ctx: RunContext, call: str, resource: str) -> dict[str, Any]:
        resp = await ctx.http.get(
            RIPESTAT.format(call=call), {"resource": resource, "sourceapp": "osintree"}
        )
        if resp.status_code != 200:
            raise RuntimeError(f"RIPEstat {call} returned HTTP {resp.status_code}")
        body = resp.json()
        if body.get("status") != "ok":
            raise RuntimeError(f"RIPEstat {call}: {body.get('status')} {body.get('messages')}")
        return body

    async def collect(self, seed: str, ctx: RunContext) -> list[Finding]:
        seed = seed.strip()
        if seed.upper().startswith("AS") and seed[2:].isdigit():
            return await self._collect_asn(int(seed[2:]), ctx)
        if seed.isdigit():
            return await self._collect_asn(int(seed), ctx)
        try:
            ip = str(ipaddress.ip_address(seed))
        except ValueError as exc:
            raise CollectorInputError(f"'{seed}' is neither an IP address nor an ASN") from exc

        overview = parse_prefix_overview(await self._call(ctx, "prefix-overview", ip))
        node = ctx.find_node(NodeLabel.ENDERECO_IP, "address", ip)
        findings: list[Finding] = []
        if not overview["asns"]:
            return findings
        primary = overview["asns"][0]

        if node is not None:
            attrs: dict[str, Any] = {}
            if not node.attrs.get("asn"):
                attrs["asn"] = primary["asn"]
            if not node.attrs.get("asn_name") and primary["holder"]:
                attrs["asn_name"] = primary["holder"]
            findings.append(
                Finding(
                    kind="node_update",
                    target_id=node.id,
                    label=NodeLabel.ENDERECO_IP,
                    attrs=attrs,
                    metadata={
                        "bgp_prefix": str(overview["prefix"] or ""),
                        "bgp_origin_asns": ", ".join(f"AS{a['asn']}" for a in overview["asns"]),
                        "bgp_announced": "true" if overview["announced"] else "false",
                    },
                    dedupe_key=f"bgp:ip={ip}",
                    evidence=f"{overview['prefix']} announced by "
                    + ", ".join(f"AS{a['asn']} ({a['holder']})" for a in overview["asns"]),
                    raw=overview,
                )
            )

        for a in overview["asns"]:
            holder = a["holder"] or f"AS{a['asn']}"
            edges = [FindingEdge(rel=RelType.MANTEM_ACESSO_A, other_id=node.id)] if node else []
            existing = ctx.find_node(NodeLabel.FORNECEDOR, "name", holder)
            if existing is not None:
                if edges:
                    findings.append(
                        Finding(
                            kind="edge",
                            target_id=existing.id,
                            label=NodeLabel.FORNECEDOR,
                            edges=edges,
                            dedupe_key=f"bgp:edge:{existing.id}->{node.id}",  # type: ignore[union-attr]
                            evidence=(
                                f"AS{a['asn']} ({holder}) announces "
                                f"{overview['prefix']} containing {ip}"
                            ),
                        )
                    )
                continue
            findings.append(
                Finding(
                    label=NodeLabel.FORNECEDOR,
                    attrs={
                        "name": holder,
                        "asn": a["asn"],
                        "service_provided": "network transit / hosting (BGP origin)",
                    },
                    metadata={"bgp_prefix": str(overview["prefix"] or "")},
                    edges=edges,
                    dedupe_key=f"Fornecedor:name={holder}",
                    evidence=f"AS{a['asn']} announces {overview['prefix']} containing {ip}",
                    raw={"asn": a["asn"], "holder": holder, "prefix": overview["prefix"]},
                )
            )
        return findings

    async def _collect_asn(self, asn: int, ctx: RunContext) -> list[Finding]:
        info = parse_as_overview(await self._call(ctx, "as-overview", f"AS{asn}"))
        prefixes = parse_announced_prefixes(await self._call(ctx, "announced-prefixes", f"AS{asn}"))
        holder = info["holder"] or f"AS{asn}"
        ips = [n for n in ctx.nodes_with(NodeLabel.ENDERECO_IP) if n.attrs.get("asn") == asn]
        nets = [ipaddress.ip_network(p, strict=False) for p in prefixes]
        for n in ctx.nodes_with(NodeLabel.ENDERECO_IP):
            if n in ips:
                continue
            try:
                if any(ipaddress.ip_address(n.attrs["address"]) in net for net in nets):
                    ips.append(n)
            except (KeyError, ValueError):
                continue
        edges = [FindingEdge(rel=RelType.MANTEM_ACESSO_A, other_id=n.id) for n in ips]
        metadata = {
            "bgp_announced_prefixes": str(len(prefixes)),
            "bgp_prefix_sample": ", ".join(prefixes[:10]),
            "bgp_announced": "true" if info["announced"] else "false",
        }
        existing = ctx.find_node(NodeLabel.FORNECEDOR, "name", holder)
        if existing is not None:
            return [
                Finding(
                    kind="node_update",
                    target_id=existing.id,
                    label=NodeLabel.FORNECEDOR,
                    attrs={"asn": asn} if not existing.attrs.get("asn") else {},
                    metadata=metadata,
                    edges=edges,
                    dedupe_key=f"bgp:asn={asn}",
                    evidence=f"AS{asn} ({holder}) announces {len(prefixes)} prefix(es)",
                    raw={"asn": asn, "holder": holder, "prefixes": prefixes[:20]},
                )
            ]
        return [
            Finding(
                label=NodeLabel.FORNECEDOR,
                attrs={
                    "name": holder,
                    "asn": asn,
                    "service_provided": "network transit / hosting (BGP origin)",
                },
                metadata=metadata,
                edges=edges,
                dedupe_key=f"Fornecedor:name={holder}",
                evidence=f"AS{asn} ({holder}) announces {len(prefixes)} prefix(es)",
                raw={"asn": asn, "holder": holder, "prefixes": prefixes[:20]},
            )
        ]
