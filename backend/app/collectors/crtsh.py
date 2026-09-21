"""crt.sh collector — Certificate Transparency logs (thesis source family: CT logs).

Queries the public crt.sh JSON endpoint for certificates issued to the seed domain and its
subdomains. Purely passive: crt.sh is a third-party index of CT logs; the target is never
contacted. Produces ``Dominio`` findings anchored to the project's ``Organizacao`` with
``PERTENCE_A``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.collectors.base import (
    Collector,
    CollectorUpstreamError,
    Finding,
    FindingEdge,
    InputKind,
    RunContext,
)
from app.collectors.http import SLOW_SOURCE_TIMEOUT_S
from app.db.schema import Axis, NodeLabel, RelType

CRTSH_URL = "https://crt.sh/"
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def parse_crtsh(entries: list[dict[str, Any]], seed: str) -> dict[str, dict[str, Any]]:
    """Aggregate crt.sh rows by hostname (lower-cased, wildcard prefix stripped), keeping
    only names within the seed domain. Returns {hostname: summary}."""
    seed = seed.lower().strip(".")
    hosts: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "certs": 0,
            "first_seen": None,
            "last_seen": None,
            "issuers": set(),
            "wildcard": False,
        }
    )
    for e in entries:
        for raw in str(e.get("name_value", "")).split("\n"):
            name = raw.strip().lower().rstrip(".")
            wildcard = name.startswith("*.")
            if wildcard:
                name = name[2:]
            if not (name == seed or name.endswith("." + seed)) or not _HOST_RE.match(name):
                continue
            h = hosts[name]
            h["certs"] += 1
            h["wildcard"] = h["wildcard"] or wildcard
            nb, na = e.get("not_before"), e.get("not_after")
            if nb and (h["first_seen"] is None or nb < h["first_seen"]):
                h["first_seen"] = nb
            if na and (h["last_seen"] is None or na > h["last_seen"]):
                h["last_seen"] = na
            issuer = str(e.get("issuer_name", ""))
            org = re.search(r"O=([^,]+)", issuer)
            h["issuers"].add(org.group(1).strip() if org else issuer[:40])
    return dict(hosts)


class CrtShCollector(Collector):
    name = "crtsh"
    description = "Subdomains from Certificate Transparency logs (crt.sh)"
    source_family = "CT logs"
    axis = Axis.DIGITAL
    input_kind = InputKind.DOMAIN
    input_label = NodeLabel.DOMINIO

    async def collect(self, seed: str, ctx: RunContext) -> list[Finding]:
        # crt.sh routinely takes 30-60 s for wildcard queries; give it more than the default.
        resp = await ctx.http.get(
            CRTSH_URL,
            {"q": f"%.{seed}", "output": "json"},
            timeout_s=SLOW_SOURCE_TIMEOUT_S,
            retries=2,  # one retry covers a transient 502; a third 90 s wait rarely helps
        )
        if resp.status_code != 200:
            raise CollectorUpstreamError(f"crt.sh returned HTTP {resp.status_code}")
        entries = resp.json() if resp.text.strip() else []
        hosts = parse_crtsh(entries, seed)

        root = ctx.root
        findings: list[Finding] = []
        for name in sorted(hosts):
            h = hosts[name]
            issuers = ", ".join(sorted(h["issuers"]))[:120]
            first = (h["first_seen"] or "")[:10]
            last = (h["last_seen"] or "")[:10]
            edges = [FindingEdge(rel=RelType.PERTENCE_A, other_id=root.id)] if root else []
            findings.append(
                Finding(
                    label=NodeLabel.DOMINIO,
                    attrs={"name": name},
                    metadata={
                        "ct_certificates": str(h["certs"]),
                        "ct_first_seen": first,
                        "ct_last_seen": last,
                        "ct_issuers": issuers,
                        **({"ct_wildcard": "true"} if h["wildcard"] else {}),
                    },
                    edges=edges,
                    dedupe_key=f"Dominio:name={name}",
                    evidence=f"{h['certs']} cert(s) · {first} → {last} · {issuers}",
                    raw={
                        "certs": h["certs"],
                        "first_seen": h["first_seen"],
                        "last_seen": h["last_seen"],
                    },
                )
            )
        return findings
