"""NVD collector — known vulnerabilities for a ``Software`` node (thesis family: NVD/CVE).

Uses the NVD CVE API 2.0 without an API key and respects the unauthenticated rate limit
(5 requests / 30 s → 6 s spacing, with back-off on 403/429). Third-party only. Produces
``CVE`` findings attached to the software with ``POSSUI_VULNERABILIDADE``.
"""

from __future__ import annotations

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
from app.db.schema import Axis, NodeLabel, RelType
from app.models.nodes import NodeOut

NVD_CVES = "https://services.nvd.nist.gov/rest/json/cves/2.0"
MAX_RESULTS = 50


def cpe_token(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "_", value.strip().lower()).strip("_") or "*"


def build_queries(sw: NodeOut) -> list[dict[str, str]]:
    """Ordered query strategies: exact CPE, virtual CPE match, then keyword search."""
    attrs = sw.attrs
    queries: list[dict[str, str]] = []
    if attrs.get("cpe"):
        queries.append({"cpeName": str(attrs["cpe"])})
    product, version, vendor = attrs.get("product", ""), attrs.get("version"), attrs.get("vendor")
    if product and version:
        clean_version = (
            re.sub(r"[^0-9a-z.]+", "", str(version).lower().split("x")[0]).rstrip(".") or "*"
        )
        vendor_token = cpe_token(vendor) if vendor else "*"
        match = f"cpe:2.3:*:{vendor_token}:{cpe_token(product)}:{clean_version}"
        queries.append({"virtualMatchString": match})
    if product:
        queries.append(
            {"keywordSearch": f"{product} {version or ''}".strip(), "keywordExactMatch": ""}
        )
    return queries


def parse_cve(item: dict[str, Any]) -> dict[str, Any]:
    cve = item.get("cve") or {}
    metrics = cve.get("metrics") or {}
    score = severity = vector = None
    # v3.x first: it is the score most tooling and the thesis scenario cite.
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV40", "cvssMetricV2"):
        entries = metrics.get(key)
        if entries:
            data = entries[0].get("cvssData") or {}
            score = data.get("baseScore")
            severity = data.get("baseSeverity") or entries[0].get("baseSeverity")
            vector = data.get("vectorString")
            break
    description = next(
        (d.get("value") for d in cve.get("descriptions") or [] if d.get("lang") == "en"), ""
    )
    cwes = sorted(
        {
            d.get("value")
            for w in cve.get("weaknesses") or []
            for d in w.get("description") or []
            if d.get("value", "").startswith("CWE-")
        }
    )
    return {
        "cve_id": cve.get("id"),
        "cvss": float(score) if score is not None else None,
        "severity": severity,
        "vector": vector,
        "published": (cve.get("published") or "")[:10] or None,
        "last_modified": (cve.get("lastModified") or "")[:10] or None,
        "description": (description or "")[:1000],
        "cwes": cwes,
        "status": cve.get("vulnStatus"),
    }


class NvdCollector(Collector):
    name = "nvd"
    description = "Known CVEs for a Software node (NVD CVE API 2.0, keyless)"
    source_family = "NVD/CVE"
    axis = Axis.DIGITAL
    input_kind = InputKind.SOFTWARE
    input_label = NodeLabel.SOFTWARE

    async def collect(self, seed: str, ctx: RunContext) -> list[Finding]:
        sw = next((n for n in ctx.nodes if n.id == seed and n.label is NodeLabel.SOFTWARE), None)
        if sw is None:
            raise CollectorInputError("the NVD collector needs a Software node of this project")
        queries = build_queries(sw)
        if not queries:
            raise CollectorInputError("the Software node needs at least a product name")

        items: list[dict[str, Any]] = []
        used: dict[str, str] = {}
        total = 0
        for q in queries:
            params = {**q, "resultsPerPage": str(MAX_RESULTS)}
            resp = await ctx.http.get(NVD_CVES, params)
            if resp.status_code == 404:
                continue  # NVD answers 404 for an unknown exact cpeName
            if resp.status_code != 200:
                raise RuntimeError(f"NVD returned HTTP {resp.status_code}")
            body = resp.json()
            items = body.get("vulnerabilities") or []
            if items:
                used = q
                total = int(body.get("totalResults") or len(items))
                break

        findings: list[Finding] = []
        for item in items:
            c = parse_cve(item)
            if not c["cve_id"]:
                continue
            existing = ctx.find_node(NodeLabel.CVE, "cve_id", c["cve_id"])
            edge = FindingEdge(rel=RelType.POSSUI_VULNERABILIDADE, other_id=sw.id, direction="in")
            score = c["cvss"] if c["cvss"] is not None else "?"
            evidence = (
                f"CVSS {score} {c['severity'] or ''} · published {c['published']} · "
                f"{c['status'] or ''}"
            ).strip()
            if existing is not None:
                findings.append(
                    Finding(
                        kind="edge",
                        target_id=existing.id,
                        label=NodeLabel.CVE,
                        edges=[edge],
                        dedupe_key=f"nvd:edge:{sw.id}->{existing.id}",
                        evidence=f"{c['cve_id']} already in graph · {evidence}",
                    )
                )
                continue
            findings.append(
                Finding(
                    label=NodeLabel.CVE,
                    attrs={
                        "cve_id": c["cve_id"],
                        **({"cvss": c["cvss"]} if c["cvss"] is not None else {}),
                        **({"severity": c["severity"]} if c["severity"] else {}),
                        **({"published": c["published"]} if c["published"] else {}),
                    },
                    description=c["description"],
                    metadata={
                        **({"cvss_vector": c["vector"]} if c["vector"] else {}),
                        **({"cwe": ", ".join(c["cwes"])} if c["cwes"] else {}),
                        **({"nvd_status": c["status"]} if c["status"] else {}),
                        "nvd_query": ", ".join(f"{k}={v}" for k, v in used.items() if v),
                        "nvd_total_results": str(total),
                    },
                    layer=sw.layer,
                    edges=[edge],
                    dedupe_key=f"CVE:cve_id={c['cve_id']}",
                    evidence=evidence,
                    raw={k: c[k] for k in ("cve_id", "cvss", "severity", "published", "status")},
                )
            )
        return findings
