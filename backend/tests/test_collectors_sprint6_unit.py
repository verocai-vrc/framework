"""Sprint 6 collectors: InternetDB, Wayback (hosts + people) and facilities parsers against
recorded/synthetic responses. No network."""

from __future__ import annotations

from app.collectors import registry
from app.collectors.base import Finding, InputKind
from app.collectors.facilities import (
    osm_address,
    overpass_query,
    parse_coord,
    parse_facility_rows,
    parse_org_rows,
    parse_overpass,
    parse_search,
    pick_org,
)
from app.collectors.internetdb import guess_ports, parse_cpe, parse_internetdb
from app.collectors.wayback import (
    extract_people,
    parse_cdx_hosts,
    pick_people_pages,
    text_blocks,
)
from app.db.schema import Axis, NodeLabel
from tests.conftest import FIXTURES, fixture_json


def test_registry_lists_sprint6_collectors_with_axes():
    by_name = registry.REGISTRY
    assert by_name["internetdb"].axis is Axis.DIGITAL
    assert by_name["wayback"].axis is Axis.DIGITAL
    assert by_name["wayback_people"].axis is Axis.HUMANO
    assert by_name["facilities"].axis is Axis.FISICO
    assert by_name["facilities"].input_kind is InputKind.ORG
    assert by_name["facilities"].input_label is NodeLabel.ORGANIZACAO
    for n in ("internetdb", "wayback", "wayback_people", "facilities"):
        assert by_name[n].interacts_with_target is False


def test_edge_finding_kind_is_accepted():
    """bgp/nvd emit ``kind="edge"`` when the node already exists; the model must allow it."""
    f = Finding(kind="edge", target_id="n1", label=NodeLabel.CVE, dedupe_key="k")
    assert f.kind == "edge"


# --- InternetDB ------------------------------------------------------------------------


def test_parse_cpe_both_syntaxes():
    assert parse_cpe("cpe:/a:apache:http_server") == {
        "part": "a",
        "vendor": "apache",
        "product": "http_server",
        "version": "",
    }
    assert parse_cpe("cpe:2.3:a:openbsd:openssh:7.4:*:*:*:*:*:*:*")["version"] == "7.4"
    assert parse_cpe("garbage") is None and parse_cpe("cpe:/a:vendor") is None


def test_parse_internetdb_real_and_synthetic():
    real = parse_internetdb(fixture_json("internetdb-192.0.43.8.json"))
    assert real["ports"] == [21, 80, 443] and real["ot_ports"] == {} and real["vulns"] == []
    assert real["cpes"][0]["product"] == "http_server"
    assert "iana.org" in real["hostnames"]

    ics = parse_internetdb(fixture_json("internetdb-ics-synthetic.json"))
    assert ics["ot_ports"] == {102: "S7comm (Siemens)", 502: "Modbus/TCP"}
    assert ics["vulns"] == ["CVE-2016-9042", "CVE-2018-1312"]  # invalid id dropped, sorted
    assert ics["tags"] == ["ics"]
    assert guess_ports(ics["cpes"][0], ics["ports"]) == [22]  # openssh
    assert guess_ports(ics["cpes"][1], ics["ports"]) == []  # firmware: no port convention
    assert guess_ports(ics["cpes"][2], ics["ports"]) == [80]  # apache


# --- Wayback ---------------------------------------------------------------------------


def test_parse_cdx_hosts_scopes_and_aggregates():
    rows = fixture_json("wayback-cdx-iana.json")
    hosts = parse_cdx_hosts(rows, "iana.org")
    assert set(hosts) == {"iana.org", "legacy.iana.org", "ftp.iana.org", "rs.iana.org"}
    assert "iana.org.evil.test" not in hosts  # suffix trick rejected
    assert hosts["legacy.iana.org"] == {
        "first": "20030601000000",
        "last": "20040601000000",
        "urls": 2,
    }
    assert hosts["iana.org"]["urls"] == 6  # www. folded into the apex


def test_pick_people_pages_latest_snapshot_per_url():
    pages = pick_people_pages(fixture_json("wayback-cdx-iana.json"))
    urls = [u for u, _ in pages]
    assert urls[0] == "https://www.iana.org/about/staff/"  # newest first
    assert "http://www.iana.org/contact" in urls
    assert all("logo.png" not in u and "old-service" not in u for u in urls)
    assert pick_people_pages([]) == []


def test_text_blocks_skip_scripts_and_keep_cards():
    html = (FIXTURES / "wayback-page-staff.html").read_text(encoding="utf-8")
    blocks = text_blocks(html)
    assert not any("Fake Person Script" in b for b in blocks)
    assert (
        "Ana Beatriz de Souza | Diretora de Operações | ana.souza@iana.org ana.souza@iana.org"
        in blocks
    )


def test_extract_people_heuristics():
    html = (FIXTURES / "wayback-page-staff.html").read_text(encoding="utf-8")
    people = {p["name"]: p for p in extract_people(html, "iana.org")}
    assert people["Ana Beatriz de Souza"] == {
        "name": "Ana Beatriz de Souza",
        "role": "Diretora de Operações",
        "email": "ana.souza@iana.org",
    }
    assert people["Carlos Eduardo Lima"]["role"] == "Gerente de TI"
    assert people["John Smith"]["email"] == "john.smith@iana.org"
    assert people["Maria Oliveira"] == {
        "name": "Maria Oliveira",
        "role": "",
        "email": "maria.oliveira@iana.org",
    }
    # addresses, role phrases, generic mailboxes, foreign domains and long blocks are ignored
    assert "Rua das Flores" not in people and "Diretora de Operações" not in people
    assert "Network Engineer" not in people and "Pedro Alvares Cabral" not in people
    assert not any(p["email"].startswith(("contato@", "imprensa@")) for p in people.values())
    assert not any("external.example" in p["email"] for p in people.values())


# --- Facilities ------------------------------------------------------------------------


def test_wikidata_parsers_prefer_website_match_and_georeferenced_sites():
    hits = parse_search(fixture_json("wikidata-search-icann.json"))
    assert hits[0]["id"] == "Q485750"
    orgs = parse_org_rows(fixture_json("wikidata-sparql-org-icann.json"))
    org, how = pick_org(orgs, "icann.org")
    assert org["qid"] == "Q485750" and how.startswith("website")
    assert org["hq"] == "Los Angeles" and org["hq_coord"] == (34.05223, -118.24368)
    assert org["country_code"] == "US" and org["employees"] == "388"
    _, how = pick_org(orgs, "nomatch.test")
    assert how.startswith("top search hit")
    assert pick_org([], None) is None
    # ICANN "operates" TLDs and the root zone: not georeferenced, so not facilities
    assert parse_facility_rows(fixture_json("wikidata-sparql-facilities-icann.json")) == []
    assert parse_coord("Point(-54.5 -25.4)") == (-25.4, -54.5) and parse_coord("x") is None


def test_overpass_query_scopes_to_country_and_escapes():
    q = overpass_query("Itaipu Binacional (BR)", "br")
    assert "[out:json]" in q and 'area["ISO3166-1"="BR"]' in q and "nwr(area.a)" in q
    assert r"\(BR\)" in q  # regex-escaped
    q2 = overpass_query("X Corp", None)
    assert "area[" not in q2 and 'nwr["operator"' in q2


def test_parse_overpass_groups_components():
    sites = {
        s["name"]: s for s in parse_overpass(fixture_json("overpass-itaipu-br.json"), "Itaipu")
    }
    # 3 unnamed generator nodes -> one summary candidate with a mean position
    gen = sites["3x power=generator (ITAIPU Binacional)"]
    assert (
        gen["parts"] == 3 and gen["lat"] is not None and gen["facility_type"] == "power=generator"
    )
    # a named line made of ways + a route relation -> one candidate
    assert (
        sites["IPU 60Hz FI1"]["parts"] == 3
        and sites["IPU 60Hz FI1"]["facility_type"] == "power=line"
    )
    assert sites["Refúgio Binacional de Mbaracaju"]["facility_type"] == "leisure=nature_reserve"
    assert all(s["operator"] for s in sites.values())
    assert osm_address({"addr:street": "Rua A", "addr:housenumber": "1", "addr:city": "Foz"}) == (
        "Rua A 1, Foz"
    )
    assert osm_address({}) is None
