"""Facilities collector — physical sites of an organization from Wikidata and OpenStreetMap
(thesis family: geographic / public records; the FISICO axis of Tabela 7 is populated from
open geographic registries, never from visiting the target).

Two keyless third-party sources are chained:

1. **Wikidata** (``wbsearchentities`` + SPARQL): resolves the organization to an item —
   preferring the item whose official website (P856) matches the project seed domain — and
   reads its headquarters (P159), coordinates (P625), country (P17 → ISO code P297), parent
   (P749), industry (P452) and every item that lists the organization as *operator* (P137)
   or *owner* (P127): power stations, dams, substations, plants, ports, offices...
2. **OpenStreetMap Overpass**: every node/way/relation whose ``operator`` or ``owner`` tag
   matches the organization name, restricted to the organization's country (from the
   ``Organizacao.country`` attribute or the Wikidata country) so the query stays cheap.
   Overpass regex queries without an area are refused by the public instance for large
   names, so without a country only Wikidata runs.

Produces ``Instalacao_Fisica`` candidates (name, address, coordinates, facility type)
anchored to the ``Organizacao`` with ``PERTENCE_A``, plus an enrichment of the root node
(Wikidata id, parent, industry, employees). OSM tags are crowd-sourced: every candidate
must be reviewed before it enters the graph.
"""

from __future__ import annotations

import re
from typing import Any

from app.collectors.base import (
    Collector,
    CollectorInputError,
    CollectorUpstreamError,
    Finding,
    FindingEdge,
    InputKind,
    RunContext,
)
from app.db.schema import Axis, NodeLabel, RelType

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
OVERPASS = "https://overpass-api.de/api/interpreter"
MAX_OSM_RESULTS = 300

_COORD_RE = re.compile(r"Point\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)", re.I)
_QID_RE = re.compile(r"Q\d+$")

# OSM tag keys that describe what kind of site this is, in priority order.
FACILITY_TAG_KEYS = (
    "power",
    "man_made",
    "industrial",
    "pipeline",
    "telecom",
    "utility",
    "railway",
    "aeroway",
    "harbour",
    "water",
    "waterway",
    "route",
    "landuse",
    "leisure",
    "boundary",
    "amenity",
    "office",
    "building",
)

# Tag values that are *components* of a site (one generator, one line segment, one pylon),
# not sites. Named components are merged by name; unnamed ones are summarised per type so a
# hydro plant with 20 generator nodes yields one candidate, not twenty.
COMPONENT_VALUES: dict[str, frozenset[str]] = {
    "power": frozenset(
        {
            "generator",
            "line",
            "minor_line",
            "cable",
            "tower",
            "pole",
            "portal",
            "switch",
            "transformer",
            "insulator",
            "terminal",
            "catenary_mast",
            "compensator",
            "converter",
            "busbar",
            "bay",
        }
    ),
    "man_made": frozenset({"pipeline", "utility_pole", "street_cabinet", "mast"}),
    "pipeline": frozenset({"*"}),
    "route": frozenset({"power", "pipeline"}),
}


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def parse_coord(literal: str | None) -> tuple[float, float] | None:
    """WKT ``Point(lon lat)`` → (lat, lon)."""
    if not literal:
        return None
    m = _COORD_RE.search(literal)
    if not m:
        return None
    lon, lat = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _val(row: dict[str, Any], key: str) -> str:
    v = row.get(key)
    return str(v.get("value", "")).strip() if isinstance(v, dict) else ""


def parse_search(data: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "id": str(e["id"]),
            "label": str(e.get("label") or ""),
            "desc": str(e.get("description") or ""),
        }
        for e in data.get("search") or []
        if _QID_RE.match(str(e.get("id", "")))
    ]


def parse_org_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """One dict per organization item from the org SPARQL query (rows merged by item)."""
    merged: dict[str, dict[str, Any]] = {}
    for row in data.get("results", {}).get("bindings", []):
        item = qid(_val(row, "item"))
        if not item:
            continue
        o = merged.setdefault(
            item,
            {
                "qid": item,
                "label": _val(row, "itemLabel"),
                "websites": set(),
                "hq": _val(row, "hqLabel"),
                "hq_coord": parse_coord(_val(row, "hqCoord")),
                "coord": parse_coord(_val(row, "coord")),
                "country": _val(row, "countryLabel"),
                "country_code": _val(row, "countryCode").upper(),
                "industry": set(),
                "parent": set(),
                "employees": _val(row, "employees"),
                "inception": _val(row, "inception")[:10],
            },
        )
        if w := _val(row, "web"):
            o["websites"].add(w.lower())
        if i := _val(row, "industryLabel"):
            o["industry"].add(i)
        if p := _val(row, "parentLabel"):
            o["parent"].add(p)
    return list(merged.values())


def pick_org(
    orgs: list[dict[str, Any]], seed_domain: str | None
) -> tuple[dict[str, Any], str] | None:
    """Prefer the item whose official website matches the seed domain; otherwise trust the
    search ranking. Returns (item, how) so the evidence line says which rule matched."""
    if not orgs:
        return None
    if seed_domain:
        d = seed_domain.lower()
        for o in orgs:
            if any(d in w for w in o["websites"]):
                return o, f"website matches {d}"
    return orgs[0], "top search hit (verify)"


def parse_facility_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in data.get("results", {}).get("bindings", []):
        f = qid(_val(row, "f"))
        if not f:
            continue
        o = merged.setdefault(
            f,
            {
                "qid": f,
                "name": _val(row, "fLabel"),
                "coord": parse_coord(_val(row, "coord")),
                "types": set(),
                "admin": _val(row, "adminLabel"),
                "relation": _val(row, "rel"),
            },
        )
        if t := _val(row, "typeLabel"):
            o["types"].add(t)
    # Only georeferenced items are physical sites; ICANN "operates" .int and the root zone,
    # which are Wikidata operator relations but not facilities.
    return [o for o in merged.values() if o["name"] and o["coord"] and not _QID_RE.match(o["name"])]


def osm_url(osm_id: str) -> str:
    kind = {"n": "node", "w": "way", "r": "relation"}[osm_id[0]]
    return f"https://www.openstreetmap.org/{kind}/{osm_id[1:]}"


def osm_facility_type(tags: dict[str, str]) -> str | None:
    for key in FACILITY_TAG_KEYS:
        if v := tags.get(key):
            if v in ("yes", "industrial") and key == "building":
                continue
            return f"{key}={v}"
    return None


def osm_address(tags: dict[str, str]) -> str | None:
    street = " ".join(p for p in (tags.get("addr:street"), tags.get("addr:housenumber")) if p)
    parts = [
        street,
        tags.get("addr:suburb"),
        tags.get("addr:city"),
        tags.get("addr:state"),
        tags.get("addr:postcode"),
        tags.get("addr:country"),
    ]
    joined = ", ".join(p for p in parts if p)
    if joined:
        return joined
    return tags.get("addr:full") or None


def _is_component(ftype: str | None) -> bool:
    if not ftype:
        return False
    key, _, value = ftype.partition("=")
    values = COMPONENT_VALUES.get(key)
    return bool(values) and ("*" in values or value in values)


def _element_coords(el: dict[str, Any]) -> tuple[float, float] | None:
    lat, lon = el.get("lat"), el.get("lon")
    if lat is None and isinstance(el.get("center"), dict):
        lat, lon = el["center"].get("lat"), el["center"].get("lon")
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def parse_overpass(data: dict[str, Any], org_name: str) -> list[dict[str, Any]]:
    """Overpass elements → site-level facility records (see ``COMPONENT_VALUES``)."""
    groups: dict[str, dict[str, Any]] = {}
    for el in data.get("elements") or []:
        tags = {str(k): str(v) for k, v in (el.get("tags") or {}).items()}
        ftype = osm_facility_type(tags)
        name = tags.get("name") or tags.get("official_name")
        if not name and not ftype:
            continue  # an unnamed, untyped feature is noise
        osm_id = f"{el.get('type', 'n')[0]}{el.get('id')}"
        component = _is_component(ftype)
        if name:
            key = f"name:{name.lower()}"
        elif component:
            key = f"type:{ftype}"
        else:
            key = f"id:{osm_id}"
        g = groups.get(key)
        if g is None:
            who = tags.get("operator") or tags.get("owner") or org_name
            g = groups[key] = {
                "osm_id": osm_id,
                "name": (name or f"{ftype} ({who})")[:200],
                "facility_type": ftype,
                "address": osm_address(tags),
                "coords": [],
                "operator": tags.get("operator"),
                "owner": tags.get("owner"),
                "parts": 0,
                "tags": {k: v for k, v in tags.items() if not k.startswith("addr:")},
            }
        g["parts"] += 1
        g["facility_type"] = g["facility_type"] or ftype
        g["address"] = g["address"] or osm_address(tags)
        if c := _element_coords(el):
            g["coords"].append(c)
    out: list[dict[str, Any]] = []
    for g in groups.values():
        coords = g.pop("coords")
        if coords:
            g["lat"] = round(sum(c[0] for c in coords) / len(coords), 6)
            g["lon"] = round(sum(c[1] for c in coords) / len(coords), 6)
        else:
            g["lat"] = g["lon"] = None
        if g["parts"] > 1 and not g["tags"].get("name"):
            g["name"] = f"{g['parts']}x {g['name']}"[:200]
        out.append(g)
    return out


def overpass_query(name: str, country_code: str | None) -> str:
    pattern = re.escape(name).replace("/", r"\/")
    filters = f'["operator"~"{pattern}",i];' + f'\n  nwr{{area}}["owner"~"{pattern}",i];'
    if country_code:
        area = f'area["ISO3166-1"="{country_code.upper()}"][admin_level=2]->.a;\n'
        scope = "(area.a)"
    else:
        area, scope = "", ""
    body = f"nwr{scope}" + filters.replace("{area}", scope)
    return f"[out:json][timeout:90];\n{area}(\n  {body}\n);\nout center tags {MAX_OSM_RESULTS};"


ORG_SPARQL = """
SELECT ?item ?itemLabel ?web ?hqLabel ?hqCoord ?coord ?countryLabel ?countryCode
       ?industryLabel ?parentLabel ?employees ?inception WHERE {
  VALUES ?item { %(values)s }
  OPTIONAL { ?item wdt:P856 ?web . }
  OPTIONAL { ?item wdt:P159 ?hq . OPTIONAL { ?hq wdt:P625 ?hqCoord . } }
  OPTIONAL { ?item wdt:P625 ?coord . }
  OPTIONAL { ?item wdt:P17 ?country . OPTIONAL { ?country wdt:P297 ?countryCode . } }
  OPTIONAL { ?item wdt:P452 ?industry . }
  OPTIONAL { ?item wdt:P749 ?parent . }
  OPTIONAL { ?item wdt:P1128 ?employees . }
  OPTIONAL { ?item wdt:P571 ?inception . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "%(lang)s". }
}
"""

FACILITIES_SPARQL = """
SELECT ?f ?fLabel ?coord ?typeLabel ?adminLabel ?rel WHERE {
  { ?f wdt:P137 wd:%(qid)s . BIND("operator" AS ?rel) }
  UNION { ?f wdt:P127 wd:%(qid)s . BIND("owner" AS ?rel) }
  UNION { ?f wdt:P1830 wd:%(qid)s . BIND("owned" AS ?rel) }
  OPTIONAL { ?f wdt:P625 ?coord . }
  OPTIONAL { ?f wdt:P31 ?type . }
  OPTIONAL { ?f wdt:P131 ?admin . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "%(lang)s". }
} LIMIT 200
"""


class FacilitiesCollector(Collector):
    name = "facilities"
    description = "Physical sites of the organization from Wikidata and OpenStreetMap (keyless)"
    source_family = "Geographic registries"
    axis = Axis.FISICO
    input_kind = InputKind.ORG
    input_label = NodeLabel.ORGANIZACAO

    async def _sparql(self, ctx: RunContext, query: str) -> dict[str, Any]:
        resp = await ctx.http.get(
            WIKIDATA_SPARQL,
            {"query": query, "format": "json"},
            headers={"Accept": "application/sparql-results+json"},
        )
        if resp.status_code != 200:
            raise CollectorUpstreamError(f"Wikidata SPARQL returned HTTP {resp.status_code}")
        return resp.json()

    async def _wikidata(
        self, ctx: RunContext, org_name: str, lang: str
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        resp = await ctx.http.get(
            WIKIDATA_API,
            {
                "action": "wbsearchentities",
                "search": org_name,
                "language": lang.split(",")[0],
                "uselang": lang.split(",")[0],
                "type": "item",
                "limit": "8",
                "format": "json",
            },
        )
        if resp.status_code != 200:
            raise CollectorUpstreamError(f"Wikidata search returned HTTP {resp.status_code}")
        hits = parse_search(resp.json())
        if not hits:
            return None, []
        values = " ".join(f"wd:{h['id']}" for h in hits)
        orgs = parse_org_rows(
            await self._sparql(ctx, ORG_SPARQL % {"values": values, "lang": lang})
        )
        picked = pick_org(orgs, ctx.project.seed_domain)
        if picked is None:
            return None, []
        org, how = picked
        org["matched_by"] = how
        facilities = parse_facility_rows(
            await self._sparql(ctx, FACILITIES_SPARQL % {"qid": org["qid"], "lang": lang})
        )
        return org, facilities

    async def _overpass(
        self, ctx: RunContext, org_name: str, country_code: str | None
    ) -> list[dict[str, Any]]:
        resp = await ctx.http.get(OVERPASS, {"data": overpass_query(org_name, country_code)})
        if resp.status_code != 200:
            raise CollectorUpstreamError(f"Overpass returned HTTP {resp.status_code}")
        return parse_overpass(resp.json(), org_name)

    async def collect(self, seed: str, ctx: RunContext) -> list[Finding]:
        org_name = seed.strip()
        if len(org_name) < 3:
            raise CollectorInputError("the facilities collector needs an organization name")
        root = ctx.root
        lang = "pt,en" if ctx.settings.report_locale.startswith("pt") else "en,pt"
        anchor = [FindingEdge(rel=RelType.PERTENCE_A, other_id=root.id)] if root else []
        findings: list[Finding] = []

        org, wd_facilities = await self._wikidata(ctx, org_name, lang)
        country_code = None
        if root and isinstance(root.attrs.get("country"), str):
            c = root.attrs["country"].strip()
            if len(c) == 2 and c.isalpha():
                country_code = c.upper()
        if org is not None:
            country_code = country_code or (org["country_code"] or None)
            if root is not None:
                findings.append(
                    Finding(
                        kind="node_update",
                        target_id=root.id,
                        label=NodeLabel.ORGANIZACAO,
                        attrs={"country": org["country"]} if org["country"] else {},
                        metadata={
                            "wikidata_id": org["qid"],
                            "wikidata_label": org["label"],
                            "wikidata_matched_by": org["matched_by"],
                            **(
                                {"wikidata_website": ", ".join(sorted(org["websites"]))}
                                if org["websites"]
                                else {}
                            ),
                            **(
                                {"wikidata_industry": ", ".join(sorted(org["industry"]))}
                                if org["industry"]
                                else {}
                            ),
                            **(
                                {"wikidata_parent": ", ".join(sorted(org["parent"]))}
                                if org["parent"]
                                else {}
                            ),
                            **(
                                {"wikidata_employees": org["employees"]} if org["employees"] else {}
                            ),
                            **(
                                {"wikidata_inception": org["inception"]} if org["inception"] else {}
                            ),
                            **({"wikidata_headquarters": org["hq"]} if org["hq"] else {}),
                        },
                        dedupe_key=f"facilities:org={org['qid']}",
                        evidence=f"Wikidata {org['qid']} “{org['label']}” · {org['matched_by']}"
                        + (f" · {org['country']}" if org["country"] else ""),
                        raw={k: (sorted(v) if isinstance(v, set) else v) for k, v in org.items()},
                    )
                )
            hq_coord = org["hq_coord"] or org["coord"]
            if org["hq"] or hq_coord:
                hq_name = (
                    f"Sede — {org['label'] or org_name}"
                    if lang.startswith("pt")
                    else f"Headquarters — {org['label'] or org_name}"
                )
                findings.append(
                    Finding(
                        label=NodeLabel.INSTALACAO_FISICA,
                        attrs={
                            "name": hq_name[:200],
                            **({"address": org["hq"]} if org["hq"] else {}),
                            **(
                                {"latitude": hq_coord[0], "longitude": hq_coord[1]}
                                if hq_coord
                                else {}
                            ),
                            "facility_type": "headquarters",
                        },
                        metadata={"wikidata_id": org["qid"], "source_detail": "Wikidata P159/P625"},
                        edges=anchor,
                        dedupe_key=f"facilities:wd:{org['qid']}:hq",
                        evidence=f"Wikidata headquarters of {org['qid']}: "
                        + (org["hq"] or "coordinates only"),
                        raw={"hq": org["hq"], "coord": hq_coord},
                    )
                )
            for f in wd_facilities:
                types = ", ".join(sorted(f["types"]))
                findings.append(
                    Finding(
                        label=NodeLabel.INSTALACAO_FISICA,
                        attrs={
                            "name": f["name"][:200],
                            **({"address": f["admin"]} if f["admin"] else {}),
                            **(
                                {"latitude": f["coord"][0], "longitude": f["coord"][1]}
                                if f["coord"]
                                else {}
                            ),
                            **({"facility_type": types[:200]} if types else {}),
                        },
                        metadata={
                            "wikidata_id": f["qid"],
                            "wikidata_relation": f["relation"],
                            "source_detail": "Wikidata P137/P127/P1830",
                        },
                        edges=anchor,
                        dedupe_key=f"facilities:wd:{f['qid']}",
                        evidence=f"Wikidata {f['qid']} lists {org['qid']} as {f['relation']}"
                        + (f" · {types}" if types else ""),
                        raw={k: (sorted(v) if isinstance(v, set) else v) for k, v in f.items()},
                    )
                )

        if country_code:
            for f in await self._overpass(ctx, org_name, country_code):
                findings.append(
                    Finding(
                        label=NodeLabel.INSTALACAO_FISICA,
                        attrs={
                            "name": f["name"],
                            **({"address": f["address"]} if f["address"] else {}),
                            **(
                                {"latitude": f["lat"], "longitude": f["lon"]}
                                if f["lat"] is not None
                                else {}
                            ),
                            **({"facility_type": f["facility_type"]} if f["facility_type"] else {}),
                        },
                        metadata={
                            "osm_id": f["osm_id"],
                            "osm_url": osm_url(f["osm_id"]),
                            **({"osm_parts": str(f["parts"])} if f["parts"] > 1 else {}),
                            **({"osm_operator": f["operator"]} if f["operator"] else {}),
                            **({"osm_owner": f["owner"]} if f["owner"] else {}),
                            "source_detail": (
                                f"OSM Overpass (operator/owner ~ “{org_name}”, {country_code})"
                            ),
                        },
                        edges=anchor,
                        dedupe_key=f"facilities:osm:{f['osm_id']}",
                        evidence=(
                            f"OSM {f['osm_id']}: "
                            + " · ".join(
                                p
                                for p in (
                                    f["facility_type"],
                                    f["operator"] and f"operator={f['operator']}",
                                    f["owner"] and f"owner={f['owner']}",
                                )
                                if p
                            )
                        ),
                        raw={"osm_id": f["osm_id"], "tags": dict(list(f["tags"].items())[:30])},
                    )
                )
        elif org is None:
            raise CollectorInputError(
                f"no Wikidata item matches “{org_name}” and the Organizacao node has no ISO "
                "country code, so the OpenStreetMap query was skipped; set `country` (e.g. BR) "
                "or refine the name and run again"
            )
        return findings
