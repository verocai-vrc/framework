# OSINTree — Development Brief for Claude Code

> Paste this file as the initial instruction to Claude Code. It is the authoritative
> specification for the whole project. Work sprint by sprint, in order. Do not skip the
> human-review gate, the passive-only guard, or the provenance model. Run the acceptance
> test at the end of every sprint before moving on.

Working project name: **OSINTree** (rename freely). Default UI language: English, with all
user-facing strings centralized so a Portuguese locale can be added later. Default license: MIT.

---

## 1. Mission and context

Build a Linux desktop-grade web application that helps a security analyst map the passive,
externally observable attack surface of a target organization, organize open-source
intelligence (OSINT) about it, and reason over the result as a directed graph.

The tool is the practical instrument for an undergraduate thesis on OSINT-based passive
attack-surface modeling for critical infrastructure, and it is also intended to be released
publicly as a general-purpose tool. It must therefore be target-agnostic (no hardcoded
scenario), keyless, offline-capable after setup, and reproducible from a clean checkout.

The graph model, the axes, and the risk correlations below are fixed by the thesis and must
be implemented exactly as specified in Sections 5 and 12. Do not invent a different schema.

A reference UI exists (a client-side vis-network notepad called "OSINT.ree"). Reproduce its
three-panel Obsidian-style experience, but back it with the Python plus Neo4j architecture
defined here. The reference is a UX guide only, not an architecture to inherit.

---

## 2. Non-negotiable constraints

1. **Passive-only by default.** A global config flag `PASSIVE_ONLY` defaults to `true`. Every
   collector declares `interacts_with_target: bool`. When `PASSIVE_ONLY` is true, any collector
   with `interacts_with_target = true` is refused before executing, with a clear message. This
   encodes the thesis distinction between passive third-party collection and active target
   interaction. Collectors must query third-party repositories and public indices, never the
   target's own servers, DNS, or web properties.
2. **Human-in-the-loop.** Collectors never write to the live graph. They write candidate nodes
   and edges to a staging area. The analyst reviews, edits, approves, or rejects each candidate.
   Only approved items are merged into the graph.
3. **Provenance on everything.** Every node and edge carries `source` (for example `manual`,
   `crt.sh`, `nvd`, `rdap`), `collected_at` (ISO-8601 UTC), and `reviewed` (bool). Manual
   entries use `source = "manual"`.
4. **Target-agnostic.** No hardcoded organization, domain, or scenario anywhere in code or
   default data. The target is supplied at runtime as a project seed.
5. **Keyless and zero-budget.** Only free, keyless sources in the built-in collectors. Paid or
   key-gated services (Shodan, Censys, DeHashed, Hunter.io, and similar) are out of scope for
   automated collection; support them only through the generic manual-import path.
6. **Offline-capable.** Vendor front-end libraries locally (no CDN dependency at runtime). The
   app must run without internet once dependencies are installed, except when a collector is
   deliberately invoked.
7. **Methodology fidelity.** The node labels, relationship types, cross-axis impact rules, and
   the three validation criteria in Sections 5 and 12 are contractual. Any extension beyond the
   thesis list must be marked in code comments as an extension.

---

## 3. Technology stack (pinned choices)

- Language: Python 3.12+.
- Backend/API: FastAPI, served by Uvicorn. Async throughout.
- Graph database: Neo4j Community 5.x, run via Docker Compose, with the APOC and Graph Data
  Science (GDS) plugins enabled. Both plugins are free.
- Neo4j access: official `neo4j` Python driver.
- HTTP client for collectors: `httpx` (async), with a shared client, timeouts, and retry/backoff.
- Validation and models: `pydantic` v2; config via `pydantic-settings` reading a `.env`.
- Front-end: plain HTML, CSS, and vanilla JavaScript. Graph rendering with `vis-network`
  (vendored locally). Markdown rendering with `marked` (vendored locally). Served as static
  assets by FastAPI. No build step.
- Testing: `pytest`, `respx` (or `httpx` MockTransport) for collector HTTP mocking, and a
  Compose-based Neo4j for integration tests.
- Tooling: `ruff` for lint and format. `pyproject.toml` for packaging. A `Makefile` (or
  `justfile`) exposing `up`, `down`, `dev`, `test`, `lint`, `seed`, `reset`.

---

## 4. Repository layout

```
osintree/
  docker-compose.yml
  .env.example
  Makefile
  pyproject.toml
  README.md
  ARCHITECTURE.md
  METHODOLOGY_MAPPING.md
  LICENSE
  backend/
    app/
      main.py              # FastAPI app, static mount, routers
      config.py            # settings (PASSIVE_ONLY, Neo4j URI, etc.)
      db/
        driver.py          # Neo4j driver lifecycle
        schema.py          # constraints, indexes, label/rel enums
        queries.py         # parametrized Cypher
      models/              # pydantic node/edge/candidate/project models
      graph/
        crud.py            # typed node/edge CRUD + edge-validity rules
        projects.py        # project (investigation) abstraction
        io.py              # JSON import/export, demo-format import
      collectors/
        base.py            # Collector interface + passive guard
        crtsh.py
        rdap.py
        bgp.py
        nvd.py
        registry.py        # collector discovery
      review/
        staging.py         # candidate store + merge-on-approve
      analysis/
        criteria.py        # the three validation criteria
        paths.py           # shortest path seed -> TO
        risk.py            # cross-axis impact + risk matrix
        report.py          # Markdown/HTML/JSON report export
      routers/             # nodes, edges, projects, collectors, review, analysis
    tests/
  frontend/
    index.html
    css/
    js/
    vendor/                # vis-network, marked (vendored)
```

---

## 5. Data model (Neo4j)

Labels are ASCII (no accents) for safe Cypher. Display names (with Portuguese accents) live in
the front-end label map. Every node carries `id` (UUID), `project_id`, `label_display`,
`title`, `notes` (Markdown), `axis`, `layer`, and the provenance fields from Section 2.

### 5.1 Node labels and axes (from thesis Tabela 7)

| Label (code)          | axis         | layer   | Meaning |
|-----------------------|--------------|---------|---------|
| `Organizacao`         | `ORG`        | null    | Audited entity; root/anchor of a project |
| `Dominio`             | `DIGITAL`    | `TI`    | Domain or subdomain, passively mapped |
| `Endereco_IP`         | `DIGITAL`    | `TI`    | Publicly routable IPv4/IPv6 |
| `Servico`             | `DIGITAL`    | `TI`    | Port and protocol exposed on an IP |
| `Software`            | `DIGITAL`    | `TI`/`TO` | OS, application, or firmware identified |
| `Dispositivo_Industrial` | `DIGITAL` | `TO`    | SCADA / PLC / IIoT asset |
| `CVE`                 | `DIGITAL`    | `TI`/`TO` | Catalogued vulnerability |
| `Funcionario`         | `HUMANO`     | null    | Employee identified from open sources |
| `Credencial_Vazada`   | `HUMANO`     | null    | Email/secret pair from a documented leak |
| `Instalacao_Fisica`   | `FISICO`     | null    | Operational site located geographically |
| `Fornecedor`          | `ECOSSISTEMA`| null    | Third party with operational relationship |

The four validation axes are `DIGITAL`, `HUMANO`, `FISICO`, `ECOSSISTEMA`. `ORG` is the anchor,
not an axis. `layer` distinguishes IT from OT for the seed-to-OT path metric.

### 5.2 Relationship types (from thesis, exact)

Allowed `(:Source)-[:REL]->(:Target)` combinations. CRUD must reject any relationship whose
endpoints violate this list.

- `(:Funcionario)-[:TRABALHA_EM]->(:Organizacao)`
- `(:Dominio)-[:RESOLVE_PARA]->(:Endereco_IP)`
- `(:Endereco_IP)-[:EXPOE]->(:Servico)`
- `(:Servico)-[:HOSPEDA]->(:Software)`
- `(:Software)-[:POSSUI_VULNERABILIDADE]->(:CVE)`
- `(:Funcionario)-[:POSSUI_CREDENCIAL_EXPOSTA]->(:Credencial_Vazada)`
- `(:Credencial_Vazada)-[:VIABILIZA_ACESSO_A]->(:Servico)`
- `(:Instalacao_Fisica)-[:ABRIGA]->(:Dispositivo_Industrial)`
- `(:Fornecedor)-[:MANTEM_ACESSO_A]->(:Endereco_IP)`
- `(:Dispositivo_Industrial)-[:OPERA_SOBRE]->(:Software)`

Anchoring extensions (needed so the graph is traversable from the seed for path metrics; mark
as extensions in comments): `(:Dominio)-[:PERTENCE_A]->(:Organizacao)`,
`(:Instalacao_Fisica)-[:PERTENCE_A]->(:Organizacao)`,
`(:Fornecedor)-[:FORNECE_PARA]->(:Organizacao)`.

### 5.3 Cross-axis risk edges and impact (from thesis Tabela 8)

When a relationship crosses two distinct axes, stamp an `impact` property on it. The engine
classifies impact from the endpoint types using this table:

| Source axis   | Target (axis/layer)          | impact    |
|---------------|------------------------------|-----------|
| `Credencial_Vazada` (HUMANO) | `Servico`, remote-auth (DIGITAL/TI) | `CRITICO` |
| `Software` with CVE (DIGITAL/TI) | `Dispositivo_Industrial` (DIGITAL/TO) | `CRITICO` |
| `Instalacao_Fisica` (FISICO) | `Dispositivo_Industrial` (DIGITAL/TO) | `CRITICO` |
| `Funcionario` (HUMANO) | `Dispositivo_Industrial` (DIGITAL/TO) | `ALTO` |
| `Fornecedor` (ECOSSISTEMA) | `Endereco_IP` (DIGITAL/TI) | `ALTO` |
| `Dominio`, staging/homolog (DIGITAL/TI) | `Fornecedor` (ECOSSISTEMA) | `MEDIO` |

### 5.4 Risk matrix (from thesis Tabela 2)

Probability {`BAIXA`, `MEDIA`, `ALTA`} times Impact {`BAIXO`, `MEDIO`, `ALTO`} maps to a level
in {`MINIMO`, `BAIXO`, `MEDIO`, `ALTO`, `CRITICO`}, per the thesis matrix. Store this mapping as
a small lookup table in `analysis/risk.py`. Probability may be heuristic (for example, presence
of a known CVE, or an exposed remote-auth service) and must be overridable by the analyst.

### 5.5 Staging and provenance

Candidates are stored separately from the live graph (either a dedicated `:Candidate` label
namespace or a staging store keyed by project). Merge-on-approve copies the candidate into the
live graph with `reviewed = true`. Constraints: unique `id` per node; helpful indexes on
`project_id`, on `Dominio.name`, `Endereco_IP.address`, and `CVE.cve_id`.

---

## 6. Collection layer (passive, keyless)

`collectors/base.py` defines an abstract `Collector` with: `name`, `interacts_with_target`
(false for all built-ins), `axis`, an async `collect(seed, context) -> list[Candidate]`, shared
`httpx` client injection, on-disk response caching, and polite rate limiting. The registry
enforces the passive guard from Section 2 before any collector runs.

Built-in keyless collectors:

- **crt.sh** (`crtsh.py`): query Certificate Transparency logs by domain via the public JSON
  endpoint. Produces `Dominio` candidates (subdomains) and `PERTENCE_A` edges to the seed org.
- **RDAP** (`rdap.py`): resolve IP and ASN registration data through public RDAP bootstrap.
  Produces `Endereco_IP` and `Fornecedor` candidates with registration metadata.
- **BGP/ASN** (`bgp.py`): map ASNs and announced prefixes through a free, keyless looking-glass
  or RIR data service. Produces `Endereco_IP` and `Fornecedor` (ecosystem) candidates.
- **NVD** (`nvd.py`): query the NVD CVE API 2.0 (keyless; respect the unauthenticated rate
  limit and back off) to correlate a `Software` node (by product/version or CPE) with `CVE`
  candidates and `POSSUI_VULNERABILIDADE` edges.

Every collector output is a `Candidate` carrying its target node/edge payload plus provenance.
Nothing reaches the live graph without approval. Add clear docstrings citing which thesis source
family each collector represents (CT logs, RDAP/WHOIS, ASN, NVD/CVE).

Do not implement direct DNS resolution or direct fetches of the target site in the built-in
set. If such an active collector is ever added, it must set `interacts_with_target = true` so
the passive guard blocks it by default.

---

## 7. Analysis engine

- **Axis coverage** (`criteria.py`): count distinct axes among {DIGITAL, HUMANO, FISICO,
  ECOSSISTEMA} present in the project. Criterion 1 passes at >= 3.
- **Seed-to-OT path** (`paths.py`): using Cypher `shortestPath` from the seed (project
  `Organizacao` or seed `Dominio`) to any node with `layer = "TO"` (prefer
  `Dispositivo_Industrial`). Report the hop count. Provide an optional weighted variant using
  GDS Dijkstra where edge weight represents estimated attacker effort. Criterion 2 passes when
  at least one such path exists.
- **Cross-axis high-impact detection** (`risk.py`): find relationships whose endpoints sit in
  distinct axes and whose classified `impact` is `CRITICO` or `ALTO`. Criterion 3 passes at >= 1.
- **Centrality** (optional, GDS): degree/betweenness to surface critical nodes.
- **Report** (`report.py`): export a project report in Markdown, HTML, and JSON summarizing the
  three criteria (pass/fail with evidence), the shortest path and its hops, the ranked
  high-impact cross-axis edges, and a node/edge inventory. This report is a primary thesis
  artifact, so keep it clean and self-contained.

---

## 8. Front-end (reproduce the reference UX)

Three-panel Obsidian-style layout, dark theme:

- **Center/left: graph canvas.** `vis-network` rendering of the live project graph. Nodes
  colored by axis (and shaped or badged by label). Click selects a node and loads it in the
  editor. Support creating a node (pick a label from a palette), connecting two nodes (pick a
  valid relationship type; invalid combinations are refused with a hint), and deleting.
- **Left/bottom: tools and collectors panel.** A list to launch collectors against the project
  seed and a quick-reference list of OSINT tool categories. Launching a collector opens the
  review queue rather than mutating the graph.
- **Right: entity editor.** Title, description, and Markdown notes bound to the selected node's
  id, with autosave to the backend. Show the node's provenance (source, collected_at, reviewed).
- **Review queue view.** Presents candidates with source and payload; approve/edit/reject;
  approved items merge into the graph and appear on the canvas.
- **Project switcher, import/export.** Create and switch projects. Export a project to JSON;
  import it back. Also accept the reference tool's simpler `{nodes, edges, pages}` JSON and
  migrate it into the typed model (best-effort label inference, defaulting unknowns to a generic
  typed node the analyst can retype).
- **Analysis panel.** Run analysis, show the three criteria with pass/fail, highlight the
  shortest seed-to-OT path on the canvas, and download the report.

Vendor `vis-network` and `marked` under `frontend/vendor/`. No runtime CDN calls.

---

## 9. Sprint plan

Each sprint proceeds in short loops (implement a slice, run it, test it, refine), and ends only
when its acceptance test passes. Commit at the end of each sprint.

### Sprint 0 — Foundations and infrastructure
Goal: a running skeleton with Neo4j and a health-checked backend, plus beginner-friendly setup.
Loops:
1. Scaffold repo, `pyproject.toml`, `ruff`, `Makefile`, `.env.example`, `README` quickstart.
2. `docker-compose.yml` for Neo4j Community 5.x with APOC and GDS enabled and a persisted
   volume. Document, step by step for a Docker beginner on Ubuntu, how to install Docker, run
   `make up`, and open Neo4j Browser. Record the native `apt` fallback in `README`.
3. FastAPI app with `/health` returning app status and Neo4j connectivity. Driver lifecycle.
4. Apply schema constraints and indexes on startup. Serve an empty front-end shell.
**Acceptance test:** `make up` starts Neo4j; `make dev` serves the API; `GET /health` returns
ok with `neo4j: connected`; the front-end shell loads in the browser; constraints exist in the
database. No graph features yet.

### Sprint 1 — Typed graph core and manual CRUD
Goal: build a valid typed graph by hand through the UI.
Loops:
1. Pydantic models for every label and relationship; the edge-validity rule table (Section 5.2).
2. Backend CRUD endpoints for nodes and edges, enforcing valid endpoint combinations and
   stamping provenance (`source = manual`).
3. Front-end graph canvas with the node palette, node creation, typed edge creation with
   validity feedback, selection, and deletion. Axis-based coloring.
**Acceptance test:** create several typed nodes and connect them with valid relationships in the
UI; an invalid combination is refused; reload the page and the graph reloads identically from
Neo4j.

### Sprint 2 — Editor, notes, projects, import/export
Goal: usable investigation workspace with persistence and portability.
Loops:
1. Project (investigation) abstraction: create, list, switch; every node scoped by `project_id`.
2. Entity editor with title, description, Markdown notes, autosave, and provenance display.
3. JSON export/import of a full typed project (round-trip lossless), plus best-effort import of
   the reference tool's `{nodes, edges, pages}` format.
**Acceptance test:** create two projects; add notes to nodes; export a project, reset the
database, re-import, and confirm the graph and notes are identical; import a reference-format
file and see it migrated into typed nodes.

### Sprint 3 — Automated collection with review gate
Goal: passive, keyless collection that never mutates the graph without approval.
Loops:
1. `Collector` base, passive guard, shared client, caching, rate limiting, registry.
2. Implement `crt.sh`, `rdap`, `bgp`, `nvd` collectors, each producing provenance-stamped
   candidates.
3. Staging store and review queue API; front-end review view with approve/edit/reject and
   merge-on-approve.
**Acceptance test:** with `PASSIVE_ONLY=true`, run the crt.sh collector against a benign,
well-known seed domain; candidates appear in the review queue with source and timestamp;
approving a subset merges only those into the graph with `reviewed = true`; a hypothetical
active collector is refused by the guard.

### Sprint 4 — Correlation and risk analysis
Goal: compute the thesis validation criteria and export a report.
Loops:
1. Cross-axis impact classification (Section 5.3) and the risk matrix (Section 5.4).
2. Axis coverage, seed-to-OT shortest path (hops; optional GDS Dijkstra), high-impact detection.
3. Report export (Markdown, HTML, JSON) and canvas highlighting of the shortest path.
**Acceptance test:** load a fixture project engineered to satisfy all three criteria; the
analysis reports >= 3 axes, a seed-to-OT path with a hop count, and >= 1 CRITICO/ALTO cross-axis
edge; the report renders in all three formats and the path is highlighted on the canvas.

### Sprint 5 — Polish, packaging, docs, publish-readiness
Goal: a clean, documented, releasable tool.
Loops:
1. UI polish: legend, hover states, custom scrollbars, empty states, error handling, path
   overlay styling, axis clustering.
2. Vendor front-end libraries; confirm full offline operation after install.
3. Packaging and docs: pinned dependencies, `README` (Ubuntu 26 setup from zero, Docker
   quickstart, native fallback), `ARCHITECTURE.md`, `METHODOLOGY_MAPPING.md` (Section 12),
   `LICENSE` (MIT). Test suite green (unit for schema/collectors/metrics with mocked HTTP,
   integration against Compose Neo4j, one smoke end-to-end).
**Acceptance test:** on a clean checkout, following only the `README`, `make up` and `make dev`
bring the app online; a sample project imports; collection, review, and analysis all work; the
full test suite passes; the app runs offline except when a collector is explicitly invoked.

---

## 10. Testing strategy

- Unit: edge-validity rules, impact classification, risk-matrix mapping, criteria math, and each
  collector's parser against recorded fixture responses (mock HTTP, no live calls in CI).
- Integration: CRUD, staging/merge, and path queries against a Compose Neo4j instance.
- End-to-end smoke: seed a fixture project, run analysis, assert the three criteria and a
  generated report.
- No test may make live network calls. Collector tests use recorded fixtures only.

---

## 11. Coding standards and how to work

- Type hints everywhere; `ruff` clean; small, single-purpose modules.
- All Cypher parametrized; never string-format user input into queries.
- Centralize user-facing strings for future localization.
- Comment any deviation or extension beyond the thesis schema as an explicit extension.
- Do not proceed to the next sprint until the current acceptance test passes. After each loop,
  run the relevant tests.
- Do not add key-gated data sources to the automated path. Do not let any collector contact the
  target directly while `PASSIVE_ONLY` is true.

---

## 12. Appendix — thesis-to-code mapping (keep in METHODOLOGY_MAPPING.md)

- Node labels correspond to Tabela 7 (Section 5.1).
- Relationship types correspond to the thesis Cypher relationship list (Section 5.2).
- Cross-axis impact rules correspond to Tabela 8 (Section 5.3).
- The risk matrix corresponds to Tabela 2 (Section 5.4).
- The three PoC validation criteria: (1) coverage of at least three of four axes; (2) at least
  one path from the public seed to an Operational Technology asset; (3) at least one cross-axis
  relationship classified CRITICO or ALTO (Section 7).
- The passive-only guard corresponds to the collection distinction in the thesis Section 2.1 and
  the exclusion of active tooling; keep this mapping explicit for the defense.