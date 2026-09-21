"""Wayback Machine collectors — historical hostnames and archived "people" pages
(thesis family: web archives; the methodology's passive web reconnaissance reads the
target's public web presence through third-party archives instead of fetching the site).

Both collectors use only the Internet Archive: the CDX index (``web.archive.org/cdx``) and
raw archived snapshots (``web.archive.org/web/<ts>id_/<url>``). The target's own servers are
never contacted, which is why crawling the *live* site is not offered here (it would be an
``interacts_with_target = True`` collector).

* ``wayback`` — every hostname under the seed domain that the archive has ever captured →
  ``Dominio`` candidates (DIGITAL) anchored with ``PERTENCE_A``; forgotten hosts are a
  classic passive attack-surface find.
* ``wayback_people`` — archived team / contact / management pages under the seed domain,
  parsed for names, roles and corporate e-mail addresses → ``Funcionario`` candidates
  (HUMANO) anchored with ``TRABALHA_EM``. Extraction is heuristic (capitalised name next to a
  role keyword, e-mail at the seed domain); every candidate goes through the review gate.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

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

CDX = "https://web.archive.org/cdx/search/cdx"
SNAPSHOT = "https://web.archive.org/web/{ts}id_/{url}"
MAX_HOST_ROWS = 5000
MAX_PEOPLE_PAGES = 12
MAX_PEOPLE_PER_PAGE = 60

_HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\.)+[a-z0-9-]{2,63}$")
_EMAIL_RE = re.compile(r"[\w.+-]+@(?:[\w-]+\.)+[a-z]{2,}", re.I)

# URL path words that mark a page listing people (pt-BR + en).
PEOPLE_PATH_WORDS = (
    "equipe", "time", "team", "staff", "people", "pessoas", "diretoria", "conselho",
    "governanca", "governança", "administracao", "administração", "gestao", "gestão",
    "quem-somos", "quemsomos", "sobre", "about", "contato", "contact", "fale-conosco",
    "faleconosco", "management", "leadership", "board", "executivos", "executives",
    "organograma", "unidades", "institucional",
)  # fmt: skip

# Role keywords (lower-case) that make a nearby capitalised phrase a probable person.
ROLE_WORDS = (
    "diretor", "diretora", "director", "gerente", "manager", "coordenador", "coordenadora",
    "coordinator", "presidente", "president", "vice-presidente", "superintendente",
    "supervisor", "supervisora", "chefe", "head", "ceo", "cfo", "cto", "cio", "ciso", "coo",
    "engenheiro", "engenheira", "engineer", "analista", "analyst", "técnico", "tecnico",
    "technician", "operador", "operadora", "operator", "secretário", "secretária", "secretary",
    "assessor", "assessora", "advisor", "conselheiro", "conselheira", "administrador",
    "administrator", "responsável", "responsavel", "encarregado", "lead", "líder", "lider",
    "ouvidor", "ouvidora", "procurador", "procuradora", "contador", "contadora", "ti ", "it ",
)  # fmt: skip

GENERIC_MAILBOXES = {
    "contato", "contact", "info", "sac", "ouvidoria", "imprensa", "press", "comercial",
    "sales", "vendas", "suporte", "support", "admin", "administrator", "webmaster",
    "noreply", "no-reply", "nao-responda", "naoresponda", "atendimento", "faleconosco",
    "marketing", "rh", "hr", "recrutamento", "jobs", "careers", "licitacao", "licitacoes",
    "compras", "financeiro", "juridico", "postmaster", "abuse", "security", "seguranca",
    "privacidade", "privacy", "lgpd", "dpo", "cotacao", "orcamento", "newsletter",
}  # fmt: skip

_UPPER = "A-ZÁÉÍÓÚÂÊÔÃÕÇÀÜ"
_LOWER = "a-záéíóúâêôãõçàü"
_NAME_RE = re.compile(
    rf"\b([{_UPPER}][{_LOWER}]{{1,}}(?:(?:\s+(?:de|da|do|dos|das|e|di|del|van|von)\s+|\s+|-)"
    rf"[{_UPPER}][{_LOWER}]{{1,}}){{1,4}})"
)
_NAME_STOP = {
    "rua", "avenida", "av", "alameda", "praça", "praca", "travessa", "rodovia", "estrada",
    "fale", "conosco", "quem", "somos", "todos", "direitos", "reservados", "política",
    "politica", "termos", "uso", "privacidade", "street", "avenue", "road", "copyright",
}  # fmt: skip


class _TextBlocks(HTMLParser):
    """Collect visible text per element. Every block-level element yields one block (its
    whole visible text, children joined with ``|``) when it is short enough to be a "card":
    a heading, a paragraph, a list item, a team-member ``div``... Long containers (the page
    body, a wide section) are skipped, but their children were already emitted."""

    BLOCK = {
        "p", "div", "li", "td", "th", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section",
        "article", "header", "footer", "dd", "dt", "dl", "figcaption", "blockquote", "address",
        "span", "strong", "b", "em", "a", "ul", "ol", "table", "tbody", "thead", "main", "aside",
        "nav", "figure", "small", "label",
    }  # fmt: skip
    INLINE = {"span", "strong", "b", "em", "a", "small", "label"}
    SKIP = {"script", "style", "noscript", "svg", "head", "template"}
    MAX_CARD = 400

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._stack: list[list[str]] = [[]]  # text parts per open element
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip += 1
        if tag == "br":
            self._stack[-1].append("|")
        if tag in self.BLOCK:
            self._stack.append([])
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href.lower().startswith("mailto:"):
                self._stack[-1].append(href[7:].split("?")[0])

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag in self.BLOCK and len(self._stack) > 1:
            parts = self._stack.pop()
            text = re.sub(r"\s+", " ", " ".join(parts)).strip(" |")
            text = re.sub(r"\s*\|\s*(\|\s*)*", " | ", text)
            if text and tag not in self.INLINE and len(text) <= self.MAX_CARD:
                self.blocks.append(text)
            if text:
                self._stack[-1].append(text if tag in self.INLINE else f"| {text} |")

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self._stack[-1].append(data.strip())

    def close(self) -> None:
        super().close()
        while len(self._stack) > 1:
            self.handle_endtag("div")


def text_blocks(html: str) -> list[str]:
    p = _TextBlocks()
    try:
        p.feed(html)
        p.close()
    except Exception:  # malformed markup: keep what was parsed
        pass
    seen: set[str] = set()
    out: list[str] = []
    for b in p.blocks:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


def cdx_rows(resp: Any) -> list[list[str]]:
    if resp.status_code != 200:
        raise CollectorUpstreamError(f"Wayback CDX returned HTTP {resp.status_code}")
    if not resp.text.strip():
        return []
    try:
        rows = resp.json()
    except ValueError as exc:  # the archive answers maintenance pages as HTML
        raise CollectorUpstreamError(
            "Wayback CDX returned a non-JSON page (archive offline?)"
        ) from exc
    return rows if isinstance(rows, list) else []


def in_scope(host: str, seed: str) -> bool:
    return host == seed or host.endswith("." + seed)


def parse_cdx_hosts(rows: list[list[str]], seed: str) -> dict[str, dict[str, Any]]:
    """CDX JSON (``fl=original,timestamp``) → {hostname: {first, last, urls}} within seed."""
    hosts: dict[str, dict[str, Any]] = {}
    for row in rows[1:] if rows and rows[0] and rows[0][0] == "original" else rows:
        if len(row) < 2:
            continue
        original, ts = row[0], row[1]
        host = (
            urlsplit(original if "://" in original else f"http://{original}").hostname or ""
        ).lower()
        host = host.rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        if not host or not _HOST_RE.match(host) or not in_scope(host, seed):
            continue
        h = hosts.setdefault(host, {"first": ts, "last": ts, "urls": 0})
        h["first"] = min(h["first"], ts)
        h["last"] = max(h["last"], ts)
        h["urls"] += 1
    return hosts


def is_people_url(url: str) -> bool:
    path = urlsplit(url if "://" in url else f"http://{url}").path.lower()
    return any(w in path for w in PEOPLE_PATH_WORDS)


def pick_people_pages(
    rows: list[list[str]], limit: int = MAX_PEOPLE_PAGES
) -> list[tuple[str, str]]:
    """Latest snapshot per people-looking URL, most recent first."""
    latest: dict[str, str] = {}
    for row in rows[1:] if rows and rows[0] and rows[0][0] == "original" else rows:
        if len(row) < 2 or not is_people_url(row[0]):
            continue
        original, ts = row[0], row[1]
        if ts > latest.get(original, ""):
            latest[original] = ts
    ranked = sorted(latest.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[:limit]


def _pretty_local(local: str) -> str:
    parts = re.split(r"[._-]+", re.sub(r"\d+", "", local))
    return " ".join(p.capitalize() for p in parts if p)


def _is_person_name(name: str) -> bool:
    toks = name.split()
    if not 2 <= len(toks) <= 5:
        return False
    low = {t.lower().strip("-") for t in toks}
    return not (low & _NAME_STOP) and not any(t.lower().rstrip("s") in _ROLE_TOKENS for t in toks)


_ROLE_TOKENS = {w.strip() for w in ROLE_WORDS if " " not in w.strip()} | {
    "operações", "operacoes", "infraestrutura", "network", "segurança", "seguranca",
    "área", "area", "setor", "departamento", "department", "unidade", "reservados",
}  # fmt: skip


def _role_from(block: str) -> str:
    low = block.lower()
    for w in ROLE_WORDS:
        idx = low.find(w)
        if idx < 0:
            continue
        # the role is the pipe-delimited segment containing the keyword
        seg_start = low.rfind("|", 0, idx) + 1
        seg_end = low.find("|", idx)
        seg = block[seg_start : seg_end if seg_end > 0 else None].strip(" |")
        return seg[:80]
    return ""


def extract_people(html: str, seed: str) -> list[dict[str, str]]:
    """Heuristic people extraction: (name, role, email) triples from one archived page."""
    people: dict[str, dict[str, str]] = {}
    parsed: list[tuple[str, list[str], str, list[str]]] = []
    for block in text_blocks(html):
        emails = [
            e.lower()
            for e in _EMAIL_RE.findall(block)
            if in_scope(e.lower().split("@", 1)[1], seed)
        ]
        names = [
            m.group(1).strip()
            for m in _NAME_RE.finditer(block)
            if _is_person_name(m.group(1).strip())
        ][:3]
        parsed.append((block, emails, _role_from(block), names))
    # pass 1: names with a role and/or a single e-mail in the same card
    for _block, emails, role, names in parsed:
        if not names:
            continue
        if role or (len(names) == 1 and len(emails) == 1):
            rec = people.setdefault(names[0], {"name": names[0], "role": "", "email": ""})
            rec["role"] = rec["role"] or role
            if emails and not rec["email"]:
                rec["email"] = emails[0]
    # pass 2: personal mailboxes nobody claimed
    claimed = {p["email"] for p in people.values() if p["email"]}
    for _block, emails, _role, _names in parsed:
        for e in emails:
            local = e.split("@", 1)[0]
            if e in claimed or local in GENERIC_MAILBOXES or not re.search(r"[a-z]", local):
                continue
            name = _pretty_local(local)
            if len(name) < 3:
                continue
            claimed.add(e)
            people.setdefault(name, {"name": name, "role": "", "email": e})
    return list(people.values())[:MAX_PEOPLE_PER_PAGE]


class WaybackCollector(Collector):
    name = "wayback"
    description = "Historical hostnames under the seed domain from the Wayback Machine CDX index"
    source_family = "Web archives"
    axis = Axis.DIGITAL
    input_kind = InputKind.DOMAIN
    input_label = NodeLabel.DOMINIO

    async def collect(self, seed: str, ctx: RunContext) -> list[Finding]:
        resp = await ctx.http.get(
            CDX,
            {
                "url": f"*.{seed}",
                "output": "json",
                "fl": "original,timestamp",
                "collapse": "urlkey",
                "filter": "!statuscode:[45]..",
                "limit": str(MAX_HOST_ROWS),
            },
            timeout_s=SLOW_SOURCE_TIMEOUT_S,
            retries=2,
        )
        rows = cdx_rows(resp)
        hosts = parse_cdx_hosts(rows, seed)
        root = ctx.root
        findings: list[Finding] = []
        for host in sorted(hosts):
            if host == seed:
                continue
            h = hosts[host]
            first, last = h["first"][:4], h["last"][:4]
            existing = ctx.find_node(NodeLabel.DOMINIO, "name", host)
            if existing is not None:
                continue
            findings.append(
                Finding(
                    label=NodeLabel.DOMINIO,
                    attrs={"name": host},
                    metadata={
                        "wayback_first": h["first"][:8],
                        "wayback_last": h["last"][:8],
                        "wayback_urls": str(h["urls"]),
                    },
                    edges=[FindingEdge(rel=RelType.PERTENCE_A, other_id=root.id)] if root else [],
                    dedupe_key=f"Dominio:name={host}",
                    evidence=f"archived {first} → {last} · {h['urls']} URL(s) captured",
                    raw=h,
                )
            )
        return findings


class WaybackPeopleCollector(Collector):
    name = "wayback_people"
    description = "Names, roles and corporate e-mails from archived team/contact pages (Wayback)"
    source_family = "Web archives"
    axis = Axis.HUMANO
    input_kind = InputKind.DOMAIN
    input_label = NodeLabel.DOMINIO

    async def collect(self, seed: str, ctx: RunContext) -> list[Finding]:
        resp = await ctx.http.get(
            CDX,
            {
                "url": f"*.{seed}",
                "output": "json",
                "fl": "original,timestamp",
                "collapse": "urlkey",
                "filter": ["statuscode:200", "mimetype:text/html"],
                "limit": str(MAX_HOST_ROWS),
            },
            timeout_s=SLOW_SOURCE_TIMEOUT_S,
            retries=2,
        )
        rows = cdx_rows(resp)
        pages = pick_people_pages(rows)
        root = ctx.root
        edges = [FindingEdge(rel=RelType.TRABALHA_EM, other_id=root.id)] if root else []
        findings: list[Finding] = []
        seen: set[str] = set()
        for url, ts in pages:
            page = await ctx.http.get(
                SNAPSHOT.format(ts=ts, url=url), headers={"Accept": "text/html"}
            )
            if page.status_code != 200 or not page.text:
                continue
            for p in extract_people(page.text, seed):
                key = p["name"].lower()
                if key in seen or ctx.find_node(NodeLabel.FUNCIONARIO, "name", p["name"]):
                    continue
                seen.add(key)
                findings.append(
                    Finding(
                        label=NodeLabel.FUNCIONARIO,
                        attrs={
                            "name": p["name"],
                            **({"role": p["role"]} if p["role"] else {}),
                            **({"email": p["email"]} if p["email"] else {}),
                        },
                        metadata={
                            "wayback_url": url,
                            "wayback_snapshot": ts[:8],
                            "extraction": "heuristic (name near role keyword / corporate e-mail)",
                        },
                        edges=edges,
                        dedupe_key=f"Funcionario:name={p['name']}",
                        evidence=f"{url} @ {ts[:8]}"
                        + (f" · {p['role']}" if p["role"] else "")
                        + (f" · {p['email']}" if p["email"] else ""),
                        raw=p,
                    )
                )
        return findings
