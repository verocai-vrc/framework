"""Collector discovery, the passive guard, seed resolution and the run pipeline
(collect → stage). This is the only place collectors are executed from."""

from __future__ import annotations

import ipaddress
import logging
import time

from app.collectors.active_example import ActiveProbeExample
from app.collectors.base import (
    Collector,
    CollectorInputError,
    InputKind,
    PassiveGuardViolation,
    RunContext,
)
from app.collectors.bgp import BgpCollector
from app.collectors.crtsh import CrtShCollector
from app.collectors.facilities import FacilitiesCollector
from app.collectors.http import CollectorHTTP
from app.collectors.internetdb import InternetDbCollector
from app.collectors.nvd import NvdCollector
from app.collectors.rdap import RdapCollector
from app.collectors.wayback import WaybackCollector, WaybackPeopleCollector
from app.config import Settings
from app.db.driver import Neo4jClient
from app.db.schema import NodeLabel
from app.errors import NotFound
from app.graph import crud, projects
from app.models.candidates import RunReport
from app.review import staging

log = logging.getLogger(__name__)

REGISTRY: dict[str, Collector] = {
    c.name: c
    for c in (
        CrtShCollector(),
        RdapCollector(),
        BgpCollector(),
        NvdCollector(),
        InternetDbCollector(),
        WaybackCollector(),
        WaybackPeopleCollector(),
        FacilitiesCollector(),
        ActiveProbeExample(),
    )
}

# NVD unauthenticated limit is 5 requests per rolling 30 s window; be polite elsewhere too.
RATE_LIMITS = {
    "services.nvd.nist.gov": 6.0,
    "crt.sh": 1.5,
    "stat.ripe.net": 0.5,
    "data.iana.org": 0.2,
    "internetdb.shodan.io": 1.0,
    "web.archive.org": 1.5,
    "www.wikidata.org": 1.0,
    "query.wikidata.org": 1.0,
    "overpass-api.de": 2.0,
    "default": 1.0,
}


def make_http(settings: Settings) -> CollectorHTTP:
    return CollectorHTTP(
        settings.cache_dir,
        timeout=settings.http_timeout,
        user_agent=settings.http_user_agent,
        min_interval=RATE_LIMITS,
    )


def get_collector(name: str) -> Collector:
    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise NotFound(f"unknown collector '{name}'", collector=name) from exc


def check_passive_guard(collector: Collector, settings: Settings) -> None:
    """Brief, Section 2.1: refuse target-interacting collectors while PASSIVE_ONLY is on."""
    if settings.passive_only and collector.interacts_with_target:
        raise PassiveGuardViolation(
            f"collector '{collector.name}' interacts with the target and PASSIVE_ONLY is enabled",
            collector=collector.name,
        )


async def resolve_seed(
    collector: Collector, ctx: RunContext, seed: str | None, node_id: str | None
) -> str:
    """Turn the request into the seed string the collector expects."""
    node = next((n for n in ctx.nodes if n.id == node_id), None) if node_id else None
    if node_id and node is None:
        raise CollectorInputError("node not found in this project", node_id=node_id)
    kind = collector.input_kind
    if kind is InputKind.SOFTWARE:
        if node is None or node.label is not NodeLabel.SOFTWARE:
            raise CollectorInputError("select a Software node to run this collector")
        return node.id
    if kind is InputKind.ORG:
        if node is not None and node.label is NodeLabel.ORGANIZACAO:
            return str(node.attrs["name"])
        if node is not None:
            raise CollectorInputError(
                f"a {node.label.value} node cannot seed the '{collector.name}' collector",
                expected=NodeLabel.ORGANIZACAO.value,
            )
        if seed and seed.strip():
            return seed.strip()
        if ctx.project.org_name:
            return ctx.project.org_name
        if ctx.root is not None:
            return str(ctx.root.attrs["name"])
        raise CollectorInputError(
            f"the '{collector.name}' collector needs an organization name (project org name)"
        )
    if node is not None:
        if kind is InputKind.DOMAIN and node.label is NodeLabel.DOMINIO:
            return str(node.attrs["name"])
        if kind is InputKind.IP and node.label is NodeLabel.ENDERECO_IP:
            return str(node.attrs["address"])
        if kind is InputKind.IP and node.label is NodeLabel.FORNECEDOR and node.attrs.get("asn"):
            return f"AS{node.attrs['asn']}"
        if kind is InputKind.ASN and node.attrs.get("asn"):
            return f"AS{node.attrs['asn']}"
        raise CollectorInputError(
            f"a {node.label.value} node cannot seed the '{collector.name}' collector",
            expected=collector.input_label.value if collector.input_label else kind.value,
        )
    if seed:
        seed = seed.strip()
        if kind is InputKind.DOMAIN:
            return seed.lower().rstrip(".")
        if kind is InputKind.IP:
            if seed.upper().startswith("AS") or seed.isdigit():
                return seed.upper()
            try:
                return str(ipaddress.ip_address(seed))
            except ValueError as exc:
                raise CollectorInputError(f"'{seed}' is not an IP address or ASN") from exc
        return seed
    if kind is InputKind.DOMAIN and ctx.project.seed_domain:
        return ctx.project.seed_domain
    raise CollectorInputError(
        f"the '{collector.name}' collector needs a {kind.value} seed or a matching selected node"
    )


async def run(
    name: str,
    project_id: str,
    db: Neo4jClient,
    settings: Settings,
    http: CollectorHTTP,
    *,
    seed: str | None = None,
    node_id: str | None = None,
) -> RunReport:
    collector = get_collector(name)
    check_passive_guard(collector, settings)  # before anything else, including seed lookup
    project = await projects.get_project(db, project_id)
    ctx = RunContext(
        project=project,
        db=db,
        settings=settings,
        http=http,
        nodes=await crud.list_nodes(db, project_id),
    )
    resolved = await resolve_seed(collector, ctx, seed, node_id)

    started = time.monotonic()
    log.info("collector %s: seed=%s project=%s", name, resolved, project_id)
    findings = await collector.collect(resolved, ctx)
    staged, skipped_pending, skipped_in_graph = await staging.stage(
        db,
        project_id,
        collector.name,
        collector.source_family,
        resolved,
        findings,
        ctx.collected_at,
    )
    return RunReport(
        collector=name,
        seed=resolved,
        findings=len(findings),
        staged=len(staged),
        skipped_pending=skipped_pending,
        skipped_in_graph=skipped_in_graph,
        duration_s=round(time.monotonic() - started, 2),
        candidates=staged,
    )
