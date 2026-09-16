"""Offline guarantee (brief, Section 2): after installation the app must run without any
network access except when a collector is explicitly invoked. This scans the served
front-end and the generated HTML report for anything that would be fetched from the web."""

from __future__ import annotations

import re
from pathlib import Path

from app.analysis import report
from app.config import FRONTEND_DIR
from tests.test_analysis_unit import _result as analysis_result

# Manual OSINT tool links in the collectors panel open in the user's browser on demand;
# they are anchors, never loaded assets, so only asset-loading constructs are inspected.
ASSET_REFS = (
    re.compile(r"""<script[^>]+src=["'](?P<url>[^"']+)["']""", re.I),
    re.compile(r"""<link[^>]+href=["'](?P<url>[^"']+)["']""", re.I),
    re.compile(r"""@import\s+(?:url\()?["']?(?P<url>[^"')\s]+)""", re.I),
    re.compile(r"""url\(\s*["']?(?P<url>[^"')\s]+)""", re.I),
    re.compile(r"""<img[^>]+src=["'](?P<url>[^"']+)["']""", re.I),
    re.compile(r"""<iframe[^>]+src=["'](?P<url>[^"']+)["']""", re.I),
)
EXTERNAL = re.compile(r"^(https?:)?//", re.I)


def external_refs(text: str) -> list[str]:
    found: list[str] = []
    for pattern in ASSET_REFS:
        found.extend(
            m.group("url") for m in pattern.finditer(text) if EXTERNAL.match(m.group("url"))
        )
    return found


def frontend_files() -> list[Path]:
    root = Path(FRONTEND_DIR)
    return [p for p in root.rglob("*") if p.suffix in {".html", ".css", ".js"}]


def test_frontend_loads_no_external_assets():
    files = frontend_files()
    assert files, "front-end directory is empty"
    offenders = {
        str(p.relative_to(FRONTEND_DIR)): external_refs(p.read_text(encoding="utf-8"))
        for p in files
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert offenders == {}, f"external assets referenced: {offenders}"


def test_frontend_never_fetches_external_urls():
    """`fetch(` / `XMLHttpRequest` / `new WebSocket(` only ever target the loopback engine."""
    bad: dict[str, list[str]] = {}
    for p in (Path(FRONTEND_DIR) / "js").glob("*.js"):
        text = p.read_text(encoding="utf-8")
        hits = re.findall(
            r"""(?:fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(\s*["'`](https?:)?//""", text
        )
        if hits:
            bad[p.name] = hits
    assert bad == {}, bad


def test_vendored_libraries_are_present_and_pinned():
    vendor = Path(FRONTEND_DIR) / "vendor"
    versions = (vendor / "VERSIONS").read_text(encoding="utf-8").split()
    assert "vis-network" in versions and "marked" in versions
    for name in ("vis-network.min.js", "marked.umd.js", "fonts.css"):
        assert (vendor / name).stat().st_size > 0, name
    for font in (vendor / "fonts").glob("*.woff2"):
        assert font.stat().st_size > 0
    assert len(list((vendor / "fonts").glob("*.woff2"))) == 4
    # index.html loads exactly the vendored copies.
    index = (Path(FRONTEND_DIR) / "index.html").read_text(encoding="utf-8")
    assert 'src="vendor/vis-network.min.js"' in index
    assert 'src="vendor/marked.umd.js"' in index


def test_html_report_is_self_contained():
    html, media = report.render(
        analysis_result(), None, "html", locale="pt", app_name="X", entry="digital"
    )
    assert media.startswith("text/html")
    assert external_refs(html) == []
    assert "<style>" in html  # styling is inlined, never linked
