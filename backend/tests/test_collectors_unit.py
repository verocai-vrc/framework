"""Collector parsers against recorded responses, the HTTP helper, and the passive guard."""

from __future__ import annotations

import asyncio
import sys
import time

import httpx
import pytest

from app.collectors import registry
from app.collectors.active_example import ActiveProbeExample
from app.collectors.base import Collector, Finding, InputKind, PassiveGuardViolation, RunContext
from app.collectors.bgp import parse_announced_prefixes, parse_as_overview, parse_prefix_overview
from app.collectors.crtsh import parse_crtsh
from app.collectors.http import CollectorHTTP
from app.collectors.nvd import build_queries, parse_cve
from app.collectors.rdap import parse_autnum, parse_ip_network, pick_service
from app.config import Settings
from app.db.schema import Axis, NodeLabel
from app.models.nodes import NodeOut
from tests.conftest import fixture_json


def test_all_builtin_collectors_are_passive_and_documented():
    for c in registry.REGISTRY.values():
        if c.name == "active_probe_example":
            continue
        assert c.interacts_with_target is False, c.name
        assert c.source_family in {
            "CT logs",
            "RDAP/WHOIS",
            "ASN/BGP",
            "NVD/CVE",
            "Scan index (Shodan)",
            "Web archives",
            "Geographic registries",
        }
        module_doc = sys.modules[type(c).__module__].__doc__ or ""
        assert "thesis" in module_doc.lower(), f"{c.name} must cite its thesis source family"


def test_passive_guard_refuses_active_collectors(settings: Settings):
    assert settings.passive_only is True
    with pytest.raises(PassiveGuardViolation) as exc:
        registry.check_passive_guard(ActiveProbeExample(), settings)
    assert exc.value.status_code == 403 and exc.value.extra["collector"] == "active_probe_example"

    class HypotheticalDnsCollector(Collector):
        name = "dns_resolve"
        description = "resolves the target's DNS directly"
        source_family = "active"
        axis = Axis.DIGITAL
        input_kind = InputKind.DOMAIN
        interacts_with_target = True

        async def collect(self, seed: str, ctx: RunContext) -> list[Finding]:
            return []

    with pytest.raises(PassiveGuardViolation):
        registry.check_passive_guard(HypotheticalDnsCollector(), settings)
    # every built-in passes
    for c in registry.REGISTRY.values():
        if not c.interacts_with_target:
            registry.check_passive_guard(c, settings)
    # only an explicit opt-out lets an active collector through
    relaxed = settings.model_copy(update={"passive_only": False})
    registry.check_passive_guard(HypotheticalDnsCollector(), relaxed)
    assert ActiveProbeExample().describe(True)["allowed"] is False
    assert ActiveProbeExample().describe(False)["allowed"] is True


# --- crt.sh -----------------------------------------------------------------------------


def test_parse_crtsh_aggregates_by_host_within_seed():
    hosts = parse_crtsh(fixture_json("crtsh-iana.json"), "iana.org")
    assert "unrelated.example.net" not in hosts
    assert "www.iana.org" in hosts and "WWW.IANA.ORG" not in hosts  # lower-cased
    assert hosts["www.iana.org"]["certs"] >= 2
    assert hosts["www.iana.org"]["first_seen"].startswith("2019-05-05")
    assert hosts["iana.org"]["wildcard"] is True  # from "*.iana.org"
    assert "Let's Encrypt" in hosts["iana.org"]["issuers"]
    assert all(h == "iana.org" or h.endswith(".iana.org") for h in hosts)


# --- RDAP -------------------------------------------------------------------------------


def test_rdap_bootstrap_and_parsers():
    boot = fixture_json("iana-rdap-ipv4.json")
    assert pick_service(boot, "192.0.43.8", "ipv4") == "https://rdap.arin.net/registry/"
    assert pick_service(boot, "41.1.1.1", "ipv4") == "https://rdap.afrinic.net/rdap/"
    assert (
        pick_service({"services": [[["1-100"], ["https://x.example/"]]]}, "42", "asn")
        == "https://x.example/"
    )
    assert pick_service({"services": []}, "10.0.0.1", "ipv4") is None

    net = parse_ip_network(fixture_json("rdap-ip-192.0.43.8.json"))
    assert net["handle"] == "NET-192-0-32-0-1" and net["name"] == "ICANN"
    assert net["range"] == "192.0.32.0 - 192.0.47.255" and net["cidrs"] == ["192.0.32.0/20"]
    assert net["registrant"] == {"name": "ICANN", "handle": "ICANN", "kind": "org"}

    asn = parse_autnum(fixture_json("rdap-autnum-16876.json"))
    assert (
        asn["asn"] == 16876 and asn["name"] == "ICANN-DC" and asn["registrant"]["name"] == "ICANN"
    )


# --- RIPEstat ---------------------------------------------------------------------------


def test_ripestat_parsers():
    pov = parse_prefix_overview(fixture_json("ripestat-prefix-overview-192.0.43.8.json"))
    assert pov["prefix"] == "192.0.43.0/24" and pov["announced"] is True
    assert pov["asns"][0] == {"asn": 40528, "holder": "ICANN-LAX - ICANN"}
    aso = parse_as_overview(fixture_json("ripestat-as-overview-16876.json"))
    assert aso["holder"] == "ICANN-DC - ICANN"
    prefixes = parse_announced_prefixes(fixture_json("ripestat-announced-prefixes-16876.json"))
    assert len(prefixes) == 9 and "208.77.191.0/24" in prefixes


# --- NVD --------------------------------------------------------------------------------


def _sw(attrs):
    return NodeOut(
        id="sw", project_id="p", label=NodeLabel.SOFTWARE, label_display="Software",
        axis=Axis.DIGITAL, layer=None, title="t", description="", notes="", attrs=attrs,
        metadata={}, source="manual", collected_at="", reviewed=True, created_at="", updated_at="",
    )  # fmt: skip


def test_nvd_query_strategy_and_parser():
    q = build_queries(_sw({"product": "FortiOS", "version": "6.0.4", "vendor": "Fortinet"}))
    assert q[0] == {"virtualMatchString": "cpe:2.3:*:fortinet:fortios:6.0.4"}
    assert q[1]["keywordSearch"] == "FortiOS 6.0.4"
    q = build_queries(
        _sw(
            {
                "product": "FortiOS",
                "version": "6.0.x",
                "cpe": "cpe:2.3:o:fortinet:fortios:6.0.4:*:*:*:*:*:*:*",
            }
        )
    )
    assert q[0] == {"cpeName": "cpe:2.3:o:fortinet:fortios:6.0.4:*:*:*:*:*:*:*"}
    assert q[1]["virtualMatchString"] == "cpe:2.3:*:*:fortios:6.0"  # ".x" wildcard trimmed
    assert build_queries(_sw({"product": "Thing"})) == [
        {"keywordSearch": "Thing", "keywordExactMatch": ""}
    ]

    items = fixture_json("nvd-cves-fortios-6.0.4.json")["vulnerabilities"]
    parsed = {c["cve_id"]: c for c in map(parse_cve, items)}
    c = parsed["CVE-2018-13379"]
    assert c["cvss"] == 9.1 and c["severity"] == "CRITICAL" and c["published"] == "2019-06-04"
    assert c["vector"].startswith("CVSS:3") and "CWE-22" in c["cwes"]
    assert c["description"].startswith("An Improper Limitation of a Pathname")


# --- HTTP helper ------------------------------------------------------------------------


async def test_http_cache_rate_limit_and_retry(tmp_path):
    calls = {"n": 0, "times": []}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        calls["times"].append(time.monotonic())
        if request.url.path == "/flaky" and calls["n"] == 1:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"n": calls["n"], "q": dict(request.url.params)})

    http = CollectorHTTP(
        tmp_path,
        transport=httpx.MockTransport(handler),
        min_interval={"default": 0.0, "slow.test": 0.2},
    )
    try:
        a = await http.get("https://fast.test/x", {"q": "1"})
        b = await http.get("https://fast.test/x", {"q": "1"})
        c = await http.get("https://fast.test/x", {"q": "2"})
        assert a.from_cache is False and b.from_cache is True and c.from_cache is False
        assert a.json()["n"] == 1 and b.json()["n"] == 1 and c.json()["n"] == 2
        assert list((tmp_path / "collectors" / "fast.test").glob("*.json"))

        calls["n"] = 0
        original_sleep = asyncio.sleep
        slept: list[float] = []

        async def fake_sleep(s: float) -> None:
            slept.append(s)
            await original_sleep(0)

        import app.collectors.http as mod

        mod.asyncio.sleep = fake_sleep  # type: ignore[assignment]
        try:
            r = await http.get("https://fast.test/flaky")
        finally:
            mod.asyncio.sleep = original_sleep  # type: ignore[assignment]
        assert r.status_code == 200 and calls["n"] == 2 and slept  # retried after 503

        calls["times"].clear()
        await http.get("https://slow.test/a", use_cache=False)
        await http.get("https://slow.test/b", use_cache=False)
        assert calls["times"][1] - calls["times"][0] >= 0.19  # per-host spacing honoured
    finally:
        await http.aclose()
