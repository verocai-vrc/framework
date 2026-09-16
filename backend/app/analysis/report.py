"""Project report in Markdown, HTML and JSON (brief, Section 7).

The report is a primary thesis artifact: self-contained (inline CSS, no external assets),
localised (``pt`` by default, ``en`` selectable), and built from one ``AnalysisResult`` so
all three formats say exactly the same thing. Markdown and HTML are rendered from the same
small document model (headings, paragraphs, tables, lists) to keep them in sync.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from typing import Literal

from app.db.schema import EXTENSION_REL_TYPES, LABEL_SPECS
from app.i18n import t
from app.models.analysis import AnalysisResult, PathResult, RiskEdge
from app.models.edges import GraphOut

ReportFormat = Literal["md", "html", "json"]

# --- tiny document model -----------------------------------------------------------------


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]


@dataclass
class Section:
    title: str
    level: int = 2
    blocks: list[str | Table | list[str]] = field(default_factory=list)  # str = paragraph


@dataclass
class Document:
    title: str
    subtitle: str
    sections: list[Section] = field(default_factory=list)


# --- building -------------------------------------------------------------------------------


def _display(label: str, locale: str) -> str:
    spec = LABEL_SPECS.get(label)  # type: ignore[call-overload]
    if spec is None:
        return label
    return spec.display_en if locale == "en" else spec.display_pt


def _rel(rel: str, locale: str) -> str:
    return f"{rel} ({t('report.extension_mark', locale)})" if rel in EXTENSION_REL_TYPES else rel


def _risk_rows(edges: list[RiskEdge], locale: str, *, with_rule: bool = True) -> Table:
    headers = [
        t("report.from", locale),
        t("report.relationship", locale),
        t("report.to", locale),
        t("report.impact", locale),
        t("report.probability", locale),
        t("report.risk", locale),
        t("report.evidence", locale),
    ]
    if with_rule:
        headers.insert(3, t("report.rule", locale))
    rows = []
    for r in edges:
        evidence = "; ".join(t(f"report.evidence_key.{k}", locale) for k in r.probability_evidence)
        if r.probability_manual:
            evidence = t("report.manual", locale)
        impact = (r.impact.value if r.impact else "-") + (" *" if r.impact_manual else "")
        row = [
            f"{r.source_title} ({_display(r.source_label.value, locale)})",
            _rel(r.rel.value, locale),
            f"{r.target_title} ({_display(r.target_label.value, locale)})",
            impact,
            r.probability.value if r.probability else "-",
            r.risk_level.value if r.risk_level else "-",
            evidence or "-",
        ]
        if with_rule:
            row.insert(3, r.rule or "-")
        rows.append(row)
    return Table(headers, rows)


def _path_section(path: PathResult, title: str, locale: str) -> list[str | Table | list[str]]:
    if not path.found:
        return [f"**{title}**: {t(f'report.path_reason.{path.reason}', locale)}"]
    chain = " → ".join(h.title for h in path.nodes)
    cost = f", {t('report.cost', locale)} {path.cost:g}" if path.cost is not None else ""
    blocks: list[str | Table | list[str]] = [
        f"**{title}** — {path.hops} {t('report.hops', locale)}{cost}: {chain}"
    ]
    by_id = {h.node_id: h for h in path.nodes}
    rows = []
    for i, s in enumerate(path.edges, start=1):
        a, b = by_id.get(s.source_id), by_id.get(s.target_id)
        rows.append(
            [
                str(i),
                a.title if a else s.source_id,
                _rel(s.rel.value, locale),
                b.title if b else s.target_id,
                f"{s.weight:g}",
            ]
        )
    blocks.append(
        Table(
            [
                t("report.step", locale),
                t("report.from", locale),
                t("report.relationship", locale),
                t("report.to", locale),
                t("report.weight", locale),
            ],
            rows,
        )
    )
    return blocks


def build_document(
    result: AnalysisResult, graph: GraphOut | None, locale: str, app_name: str, entry: str
) -> Document:
    p = result.project
    doc = Document(
        title=t("report.title", locale),
        subtitle=t("report.subtitle", locale, app=app_name, date=result.computed_at),
    )

    # Summary
    passed = sum(1 for c in result.criteria if c.passed)
    verdict = (
        t("report.verdict_pass", locale)
        if result.all_passed
        else t("report.verdict_fail", locale, n=passed)
    )
    summary = Section(t("report.summary", locale))
    summary.blocks.append(
        Table(
            ["", ""],
            [
                [t("report.project", locale), p.name],
                [t("report.target", locale), p.org_name or "-"],
                [t("report.seed", locale), p.seed_domain or "-"],
                [t("report.nodes", locale), str(result.inventory.node_count)],
                [t("report.edges", locale), str(result.inventory.edge_count)],
                [t("report.entry_policy", locale), t(f"report.entry.{entry}", locale)],
            ],
        )
    )
    summary.blocks.append(f"**{verdict}**")
    doc.sections.append(summary)

    # Criteria
    crit = Section(t("report.criteria", locale))
    crit.blocks.append(
        Table(
            [
                "#",
                t("report.criterion", locale),
                t("report.result", locale),
                t("report.value", locale),
                t("report.threshold", locale),
            ],
            [
                [
                    str(c.number),
                    t(f"report.c{c.number}", locale),
                    t("report.pass" if c.passed else "report.fail", locale),
                    str(c.value),
                    f">= {c.threshold}",
                ]
                for c in result.criteria
            ],
        )
    )
    for c in result.criteria:
        crit.blocks.append(f"**{c.number}. {t(f'report.c{c.number}', locale)}**")
        crit.blocks.append(list(c.evidence) or [t("report.none", locale)])
    doc.sections.append(crit)

    # Path
    path_sec = Section(t("report.path", locale))
    path_sec.blocks.extend(_path_section(result.path, t("report.path_hops", locale), locale))
    if result.weighted_path is not None:
        path_sec.blocks.extend(
            _path_section(result.weighted_path, t("report.path_weighted", locale), locale)
        )
    doc.sections.append(path_sec)

    # High-impact edges
    hi = Section(t("report.high_impact", locale))
    hi.blocks.append(t("report.high_impact_note", locale))
    hi.blocks.append(
        _risk_rows(result.high_impact_edges, locale)
        if result.high_impact_edges
        else t("report.none", locale)
    )
    doc.sections.append(hi)

    other = [r for r in result.classified_edges if r not in result.high_impact_edges]
    if other:
        allc = Section(t("report.classified", locale))
        allc.blocks.append(_risk_rows(other, locale))
        doc.sections.append(allc)

    if result.unclassified_cross_axis:
        un = Section(t("report.unclassified", locale))
        un.blocks.append(t("report.unclassified_note", locale))
        un.blocks.append(_risk_rows(result.unclassified_cross_axis, locale, with_rule=False))
        doc.sections.append(un)

    # Centrality
    if result.centrality:
        cen = Section(t("report.centrality", locale))
        cen.blocks.append(
            t(
                "report.centrality_note_gds"
                if result.centrality_method == "gds"
                else "report.centrality_note_cypher",
                locale,
            )
        )
        headers = [
            t("report.node", locale),
            t("report.type", locale),
            t("report.axis", locale),
            t("report.degree", locale),
        ]
        if result.centrality_method == "gds":
            headers.append(t("report.betweenness", locale))
        rows = []
        for c in result.centrality:
            row = [c.title, _display(c.label.value, locale), c.axis.value, f"{c.degree:g}"]
            if result.centrality_method == "gds":
                row.append(f"{(c.betweenness or 0):.1f}")
            rows.append(row)
        cen.blocks.append(Table(headers, rows))
        doc.sections.append(cen)

    # Inventory
    inv = Section(t("report.inventory", locale))
    inv.blocks.append(
        Table(
            [t("report.by_axis", locale), t("report.count", locale)],
            [[k, str(v)] for k, v in result.inventory.nodes_by_axis.items()],
        )
    )
    inv.blocks.append(
        Table(
            [t("report.by_label", locale), t("report.count", locale)],
            [[_display(k, locale), str(v)] for k, v in result.inventory.nodes_by_label.items()],
        )
    )
    inv.blocks.append(
        Table(
            [t("report.by_rel", locale), t("report.count", locale)],
            [[_rel(k, locale), str(v)] for k, v in result.inventory.edges_by_rel.items()],
        )
    )
    if graph is not None:
        inv.blocks.append(
            Table(
                [
                    t("report.node", locale),
                    t("report.type", locale),
                    t("report.axis", locale),
                    t("report.source", locale),
                    t("report.reviewed", locale),
                ],
                [
                    [
                        n.title,
                        _display(n.label.value, locale),
                        f"{n.axis.value}{'/' + n.layer.value if n.layer else ''}",
                        n.source,
                        t("report.yes" if n.reviewed else "report.no", locale),
                    ]
                    for n in sorted(
                        graph.nodes, key=lambda n: (n.axis.value, n.label.value, n.title)
                    )
                ],
            )
        )
    doc.sections.append(inv)

    method = Section(t("report.method", locale))
    method.blocks.append(t("report.method_text", locale))
    doc.sections.append(method)
    return doc


# --- rendering ------------------------------------------------------------------------------


def _md_cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def render_markdown(doc: Document) -> str:
    out = [f"# {doc.title}", "", f"_{doc.subtitle}_", ""]
    for sec in doc.sections:
        out.append(f"{'#' * sec.level} {sec.title}")
        out.append("")
        for block in sec.blocks:
            if isinstance(block, Table):
                out.append("| " + " | ".join(_md_cell(h) for h in block.headers) + " |")
                out.append("|" + "---|" * len(block.headers))
                out.extend("| " + " | ".join(_md_cell(c) for c in row) + " |" for row in block.rows)
            elif isinstance(block, list):
                out.extend(f"- {item}" for item in block)
            else:
                out.append(block)
            out.append("")
    return "\n".join(out).rstrip() + "\n"


_HTML_CSS = """
:root { color-scheme: light dark; }
body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; max-width: 1100px;
  margin: 2rem auto; padding: 0 1.25rem; line-height: 1.5; color: #1f2328; background: #fff; }
h1 { font-size: 1.7rem; margin-bottom: .2rem; } h2 { font-size: 1.2rem; margin-top: 2rem;
  border-bottom: 1px solid #d0d7de; padding-bottom: .25rem; }
.subtitle { color: #57606a; margin-top: 0; }
table { border-collapse: collapse; width: 100%; margin: .75rem 0 1rem; font-size: .92rem; }
th, td { border: 1px solid #d0d7de; padding: .35rem .55rem; text-align: left; vertical-align: top; }
th { background: #f6f8fa; }
td.lvl-CRITICO { color: #a40e26; font-weight: 600; }
td.lvl-ALTO { color: #bc4c00; font-weight: 600; }
td.lvl-MEDIO { color: #9a6700; } td.lvl-BAIXO, td.lvl-MINIMO { color: #57606a; }
td.res-pass { color: #1a7f37; font-weight: 600; } td.res-fail { color: #a40e26; font-weight: 600; }
code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: .9em; }
@media (prefers-color-scheme: dark) { body { color: #e6edf3; background: #0d1117; }
  th { background: #161b22; } th, td, h2 { border-color: #30363d; } .subtitle { color: #8b949e; }
  td.lvl-CRITICO { color: #ff7b72; } td.lvl-ALTO { color: #f0883e; }
  td.lvl-MEDIO { color: #d29922; }
  td.res-pass { color: #3fb950; } td.res-fail { color: #ff7b72; } }
@media print { body { margin: 0; max-width: none; } }
"""

_LEVELS = {"CRITICO", "ALTO", "MEDIO", "BAIXO", "MINIMO"}


def _inline(s: str) -> str:
    """Escape, then honour the one bit of Markdown the builder uses (**bold**)."""
    parts = html.escape(s).split("**")
    return "".join(f"<strong>{p}</strong>" if i % 2 else p for i, p in enumerate(parts))


def _td(cell: str, pass_label: str, fail_label: str) -> str:
    cls = ""
    plain = cell.rstrip(" *")
    if plain in _LEVELS:
        cls = f' class="lvl-{plain}"'
    elif cell == pass_label:
        cls = ' class="res-pass"'
    elif cell == fail_label:
        cls = ' class="res-fail"'
    return f"<td{cls}>{_inline(cell)}</td>"


def render_html(doc: Document, locale: str) -> str:
    pass_label, fail_label = t("report.pass", locale), t("report.fail", locale)
    out = [
        "<!DOCTYPE html>",
        f'<html lang="{"pt-BR" if locale == "pt" else "en"}"><head><meta charset="utf-8">',
        f"<title>{html.escape(doc.title)}</title>",
        f"<style>{_HTML_CSS}</style></head><body>",
        f"<h1>{html.escape(doc.title)}</h1>",
        f'<p class="subtitle">{html.escape(doc.subtitle)}</p>',
    ]
    for sec in doc.sections:
        out.append(f"<h{sec.level}>{html.escape(sec.title)}</h{sec.level}>")
        for block in sec.blocks:
            if isinstance(block, Table):
                out.append("<table><thead><tr>")
                out.extend(f"<th>{html.escape(h)}</th>" for h in block.headers)
                out.append("</tr></thead><tbody>")
                for row in block.rows:
                    out.append(
                        "<tr>" + "".join(_td(c, pass_label, fail_label) for c in row) + "</tr>"
                    )
                out.append("</tbody></table>")
            elif isinstance(block, list):
                out.append("<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in block) + "</ul>")
            else:
                out.append(f"<p>{_inline(block)}</p>")
    out.append("</body></html>")
    return "\n".join(out)


def render_json(result: AnalysisResult, graph: GraphOut | None, entry: str) -> str:
    payload = {
        "format": "osintree-report/1",
        "entry_policy": entry,
        "analysis": result.model_dump(mode="json"),
    }
    if graph is not None:
        payload["graph"] = graph.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render(
    result: AnalysisResult,
    graph: GraphOut | None,
    fmt: ReportFormat,
    *,
    locale: str,
    app_name: str,
    entry: str,
) -> tuple[str, str]:
    """Return (content, media type) for the requested format."""
    if fmt == "json":
        return render_json(result, graph, entry), "application/json"
    doc = build_document(result, graph, locale, app_name, entry)
    if fmt == "html":
        return render_html(doc, locale), "text/html; charset=utf-8"
    return render_markdown(doc), "text/markdown; charset=utf-8"
