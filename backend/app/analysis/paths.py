"""Seed-to-OT path (thesis criterion 2) and centrality.

The seed is the project's ``Organizacao`` anchor. Thesis relationships all point *towards*
the anchor (``PERTENCE_A``, ``FORNECE_PARA``, ``TRABALHA_EM``), so the anchoring edge is
traversed in reverse to reach an entry point, and every other hop follows edge direction
(the attacker's direction of movement). Two entry policies:

* ``digital`` (default) - only ``Dominio`` nodes anchored to the organization: the public
  seed footprint the thesis means by "public seed";
* ``any`` - every anchored node (employees, facilities, suppliers) may be an entry point.

Two implementations: Cypher ``shortestPath`` (hop count) and, when the GDS plugin is
installed, Dijkstra over ``weight`` (estimated attacker effort, default 1 per hop).
"""

from __future__ import annotations

import contextlib
import logging
from itertools import pairwise
from typing import Final, Literal

from neo4j.exceptions import Neo4jError

from app.db.driver import Neo4jClient
from app.db.schema import ENTITY_LABEL, NodeLabel, RelType
from app.models.analysis import CentralityEntry, PathHop, PathResult, PathStep
from app.models.edges import EdgeOut, GraphOut
from app.models.nodes import NodeOut
from app.models.projects import ProjectOut

log = logging.getLogger(__name__)

EntryPolicy = Literal["digital", "any"]

ANCHOR_RELS: Final[tuple[RelType, ...]] = (
    RelType.PERTENCE_A,
    RelType.FORNECE_PARA,
    RelType.TRABALHA_EM,
)
MAX_HOPS: Final = 20
DEFAULT_WEIGHT: Final = 1.0

_ANCHOR_UNION = "|".join(r.value for r in ANCHOR_RELS)


# --- seed ---------------------------------------------------------------------------------


def find_seed(project: ProjectOut, graph: GraphOut) -> NodeOut | None:
    """The anchor node, or the seed ``Dominio`` when the project has no anchor."""
    by_id = {n.id: n for n in graph.nodes}
    if project.root_node_id and project.root_node_id in by_id:
        return by_id[project.root_node_id]
    if project.seed_domain:
        for n in graph.nodes:
            if n.label == NodeLabel.DOMINIO and n.attrs.get("name") == project.seed_domain:
                return n
    return None


def _entry_filter(policy: EntryPolicy) -> str:
    return f"s:{NodeLabel.DOMINIO.value}" if policy == "digital" else "true"


def _hop(n: NodeOut) -> PathHop:
    return PathHop(node_id=n.id, title=n.title, label=n.label, axis=n.axis, layer=n.layer)


def _step(e: EdgeOut) -> PathStep:
    return PathStep(
        edge_id=e.id,
        rel=e.rel,
        source_id=e.source_id,
        target_id=e.target_id,
        weight=e.weight if e.weight is not None else DEFAULT_WEIGHT,
    )


# --- Cypher shortestPath (hops) -------------------------------------------------------------

# Anchored seed: reverse the anchoring hop, then shortestPath forward to a TO node.
# Devices are preferred over TO software; ties broken by length.
_SP_ANCHORED = f"""
MATCH (seed:{ENTITY_LABEL} {{id: $seed}})
MATCH (s:{ENTITY_LABEL})-[anchor:{_ANCHOR_UNION}]->(seed)
WHERE {{entry}}
MATCH (t:{ENTITY_LABEL} {{project_id: $pid}})
WHERE t.layer = 'TO' AND t.id <> s.id
MATCH p = shortestPath((s)-[*..{MAX_HOPS}]->(t))
RETURN anchor.id AS anchor_id,
       [n IN nodes(p) | n.id] AS node_ids,
       [r IN relationships(p) | r.id] AS edge_ids,
       length(p) AS len,
       t:{NodeLabel.DISPOSITIVO_INDUSTRIAL.value} AS is_device
ORDER BY is_device DESC, len ASC
LIMIT 1
"""

# Seed is itself an entry point (project without an Organizacao anchor).
_SP_DIRECT = f"""
MATCH (s:{ENTITY_LABEL} {{id: $seed}})
MATCH (t:{ENTITY_LABEL} {{project_id: $pid}})
WHERE t.layer = 'TO' AND t.id <> s.id
MATCH p = shortestPath((s)-[*..{MAX_HOPS}]->(t))
RETURN null AS anchor_id,
       [n IN nodes(p) | n.id] AS node_ids,
       [r IN relationships(p) | r.id] AS edge_ids,
       length(p) AS len,
       t:{NodeLabel.DISPOSITIVO_INDUSTRIAL.value} AS is_device
ORDER BY is_device DESC, len ASC
LIMIT 1
"""


def _not_found(
    method: Literal["shortestPath", "gds.dijkstra"], reason: str, seed: NodeOut | None
) -> PathResult:
    return PathResult(
        method=method,
        found=False,
        reason=reason,
        seed_id=seed.id if seed else None,
        seed_title=seed.title if seed else None,
    )


async def shortest_path_to_ot(
    db: Neo4jClient, project: ProjectOut, graph: GraphOut, entry: EntryPolicy = "digital"
) -> PathResult:
    """Cypher ``shortestPath`` from the seed to the nearest OT node; hops include the
    reversed anchoring hop when the seed is the ``Organizacao``."""
    seed = find_seed(project, graph)
    if seed is None:
        return _not_found("shortestPath", "no_seed", None)
    if not any(n.layer is not None and n.layer.value == "TO" for n in graph.nodes):
        return _not_found("shortestPath", "no_ot", seed)

    anchored = seed.label == NodeLabel.ORGANIZACAO
    query = _SP_ANCHORED.replace("{entry}", _entry_filter(entry)) if anchored else _SP_DIRECT
    rec = await db.run_one(query, {"seed": seed.id, "pid": project.id}, readonly=True)
    if rec is None:
        return _not_found("shortestPath", "unreachable", seed)

    nodes = {n.id: n for n in graph.nodes}
    edges = {e.id: e for e in graph.edges}
    node_ids: list[str] = list(rec["node_ids"])
    edge_ids: list[str] = list(rec["edge_ids"])
    if rec["anchor_id"]:
        node_ids.insert(0, seed.id)
        edge_ids.insert(0, rec["anchor_id"])
    steps = [_step(edges[i]) for i in edge_ids if i in edges]
    return PathResult(
        method="shortestPath",
        found=True,
        seed_id=seed.id,
        seed_title=seed.title,
        target_id=node_ids[-1],
        target_title=nodes[node_ids[-1]].title,
        hops=len(edge_ids),
        cost=sum(s.weight for s in steps),
        nodes=[_hop(nodes[i]) for i in node_ids if i in nodes],
        edges=steps,
    )


# --- GDS ------------------------------------------------------------------------------------

_GDS_VERSION = "RETURN gds.version() AS v"


async def gds_available(db: Neo4jClient) -> bool:
    try:
        rec = await db.run_one(_GDS_VERSION, readonly=True)
    except Neo4jError as exc:
        log.debug("GDS not available: %s", exc)
        return False
    return rec is not None


_GDS_DROP = "CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName"

# Cypher projection: anchoring edges are collapsed into one virtual ``ANCHOR`` type projected
# UNDIRECTED (so the seed can leave the anchor); all others keep their direction. In the
# ``digital`` policy, anchoring edges that do not start at a Dominio are left out entirely.
# GDS refuses an undirected type that ends up empty, hence the ``$undirected`` parameter.
_GDS_PROJECT_PATH = f"""
MATCH (s:{ENTITY_LABEL} {{project_id: $pid}})-[r]->(t:{ENTITY_LABEL})
WHERE NOT type(r) IN $anchors OR {{entry}}
RETURN gds.graph.project(
  $name, s, t,
  {{
    relationshipType: CASE WHEN type(r) IN $anchors THEN 'ANCHOR' ELSE type(r) END,
    relationshipProperties: {{weight: coalesce(r.weight, $default)}}
  }},
  {{undirectedRelationshipTypes: $undirected}}
) AS g
"""

_GDS_DIJKSTRA = f"""
MATCH (seed:{ENTITY_LABEL} {{id: $seed}})
CALL gds.allShortestPaths.dijkstra.stream($name, {{
  sourceNode: seed, relationshipWeightProperty: 'weight'
}})
YIELD targetNode, totalCost, nodeIds
WITH gds.util.asNode(targetNode) AS t, totalCost, nodeIds
WHERE t.layer = 'TO' AND t.id <> $seed
RETURN t.id AS target_id, totalCost AS cost,
       [id IN nodeIds | gds.util.asNode(id).id] AS node_ids,
       t:{NodeLabel.DISPOSITIVO_INDUSTRIAL.value} AS is_device
ORDER BY is_device DESC, cost ASC, size(nodeIds) ASC
LIMIT 1
"""

# Centrality wants a single orientation; the whole project graph is projected undirected.
_GDS_PROJECT_UNDIRECTED = f"""
MATCH (s:{ENTITY_LABEL} {{project_id: $pid}})-[r]->(t:{ENTITY_LABEL})
RETURN gds.graph.project($name, s, t, {{}}, {{undirectedRelationshipTypes: ['*']}}) AS g
"""

_GDS_DEGREE = """
CALL gds.degree.stream($name) YIELD nodeId, score
RETURN gds.util.asNode(nodeId).id AS id, score
"""
_GDS_BETWEENNESS = """
CALL gds.betweenness.stream($name) YIELD nodeId, score
RETURN gds.util.asNode(nodeId).id AS id, score
"""


def _graph_name(project_id: str, suffix: str) -> str:
    return f"osintree_{project_id.replace('-', '')}_{suffix}"


def _edge_between(graph: GraphOut, a: str, b: str) -> EdgeOut | None:
    """The cheapest edge connecting two consecutive path nodes (either direction, since
    anchoring edges are projected undirected)."""
    best: EdgeOut | None = None
    for e in graph.edges:
        if {e.source_id, e.target_id} == {a, b}:
            w = e.weight if e.weight is not None else DEFAULT_WEIGHT
            if best is None or w < (best.weight if best.weight is not None else DEFAULT_WEIGHT):
                best = e
    return best


async def weighted_path_to_ot(
    db: Neo4jClient, project: ProjectOut, graph: GraphOut, entry: EntryPolicy = "digital"
) -> PathResult:
    """GDS Dijkstra from the seed to the cheapest OT node, ``weight`` = attacker effort."""
    seed = find_seed(project, graph)
    if seed is None:
        return _not_found("gds.dijkstra", "no_seed", None)
    if not await gds_available(db):
        return _not_found("gds.dijkstra", "gds_unavailable", seed)

    name = _graph_name(project.id, "path")
    anchors = [r.value for r in ANCHOR_RELS]
    anchored = seed.label == NodeLabel.ORGANIZACAO
    entry_filter = _entry_filter(entry) if anchored else "true"
    by_id = {n.id: n for n in graph.nodes}
    has_anchor = any(
        e.rel in ANCHOR_RELS
        and (entry == "any" or not anchored or by_id[e.source_id].label == NodeLabel.DOMINIO)
        for e in graph.edges
        if e.source_id in by_id
    )
    try:
        await db.run(_GDS_DROP, {"name": name})
        rec = await db.run_one(
            _GDS_PROJECT_PATH.replace("{entry}", entry_filter),
            {
                "pid": project.id,
                "name": name,
                "anchors": anchors,
                "undirected": ["ANCHOR"] if has_anchor else [],
                "default": DEFAULT_WEIGHT,
            },
        )
        if rec is None or rec["g"] is None or rec["g"]["relationshipCount"] == 0:
            return _not_found("gds.dijkstra", "unreachable", seed)
        rec = await db.run_one(_GDS_DIJKSTRA, {"name": name, "seed": seed.id})
    finally:
        with contextlib.suppress(Neo4jError):  # best-effort cleanup
            await db.run(_GDS_DROP, {"name": name})
    if rec is None:
        return _not_found("gds.dijkstra", "unreachable", seed)

    nodes = {n.id: n for n in graph.nodes}
    node_ids: list[str] = list(rec["node_ids"])
    steps: list[PathStep] = []
    for a, b in pairwise(node_ids):
        e = _edge_between(graph, a, b)
        if e is not None:
            steps.append(_step(e))
    return PathResult(
        method="gds.dijkstra",
        found=True,
        seed_id=seed.id,
        seed_title=seed.title,
        target_id=rec["target_id"],
        target_title=nodes[rec["target_id"]].title,
        hops=len(node_ids) - 1,
        cost=float(rec["cost"]),
        nodes=[_hop(nodes[i]) for i in node_ids if i in nodes],
        edges=steps,
    )


async def centrality(
    db: Neo4jClient, project: ProjectOut, graph: GraphOut, top_n: int = 10
) -> tuple[list[CentralityEntry], Literal["gds", "cypher", "none"]]:
    """Degree and betweenness (GDS) or plain degree (Cypher fallback), highest first."""
    nodes = {n.id: n for n in graph.nodes}
    if not nodes:
        return [], "none"
    degree: dict[str, float] = dict.fromkeys(nodes, 0.0)
    betweenness: dict[str, float] | None = None
    method: Literal["gds", "cypher", "none"] = "cypher"

    if await gds_available(db):
        name = _graph_name(project.id, "central")
        try:
            await db.run(_GDS_DROP, {"name": name})
            # A project without relationships projects nothing: ``g`` comes back null.
            rec = await db.run_one(_GDS_PROJECT_UNDIRECTED, {"pid": project.id, "name": name})
            if rec is not None and rec["g"] is not None and rec["g"]["nodeCount"] > 0:
                for r in await db.run(_GDS_DEGREE, {"name": name}):
                    degree[r["id"]] = float(r["score"])
                betweenness = {
                    r["id"]: float(r["score"])
                    for r in await db.run(_GDS_BETWEENNESS, {"name": name})
                }
                method = "gds"
        except Neo4jError as exc:  # pragma: no cover - depends on the installed plugin
            log.warning("GDS centrality failed, falling back to Cypher degree: %s", exc)
        finally:
            with contextlib.suppress(Neo4jError):
                await db.run(_GDS_DROP, {"name": name})

    if method == "cypher":
        for e in graph.edges:
            degree[e.source_id] = degree.get(e.source_id, 0.0) + 1
            degree[e.target_id] = degree.get(e.target_id, 0.0) + 1

    entries = [
        CentralityEntry(
            node_id=nid,
            title=n.title,
            label=n.label,
            axis=n.axis,
            degree=degree.get(nid, 0.0),
            betweenness=betweenness.get(nid, 0.0) if betweenness is not None else None,
        )
        for nid, n in nodes.items()
    ]
    entries.sort(key=lambda c: (-(c.betweenness or 0.0), -c.degree, c.title))
    return entries[:top_n], method
