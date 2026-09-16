# Architecture

> Living document; expanded each sprint.

## Overview

OSINTree is a **desktop application**: `osintree` (or `make app`) starts one Python process
that runs the engine and opens the UI in a native window. Nothing is meant to be opened in
a browser by the user; the browser path (`osintree --browser`, `make dev`) exists only for
development.

```
┌──────────────────────────── one process: `osintree` ────────────────────────────┐
│                                                                                 │
│  native window (pywebview → WebKitGTK)       engine (FastAPI + Uvicorn thread)  │
│  ┌──────────────────────────────┐   loopback  ┌────────────────────────────┐    │
│  │ frontend/ (HTML, JS,         │ ──HTTP────▶ │ routers/     request layer │    │
│  │ vis-network, marked; static) │  127.0.0.1  │ graph/       typed CRUD,   │    │
│  └──────────────────────────────┘  free port  │              projects, I/O │    │
│                                               │ collectors/  passive only, │    │
│                                               │              staging       │    │
│                                               │ review/      merge-on-     │    │
│                                               │              approve       │    │
│                                               │ analysis/    criteria,     │    │
│                                               │              paths, risk   │    │
│                                               └─────────────┬──────────────┘    │
└─────────────────────────────────────────────────────────────┼───────────────────┘
                                                              │ Bolt
                                                              ▼
                                                     Neo4j 5.26 (APOC, GDS)
```

### Why the engine still speaks HTTP

The brief pins the UI to HTML/JS with `vis-network`, a JavaScript library: it can only
render inside a web engine, so "our own window" is a WebView, and the JavaScript in it needs
a bridge to the Python engine. The bridge is HTTP on the loopback interface at a random free
port, never exposed beyond the machine. It is an *internal* service interface, not a public
API: it keeps the brief's FastAPI/Uvicorn stack, lets the whole UI contract be tested with
`httpx`, and lets developers debug in a browser. Closing the window stops the engine.

Single process, single user, bound to `127.0.0.1`. No build step for the front-end.

## Backend modules

| Module                 | Responsibility |
|------------------------|----------------|
| `app/config.py`        | `Settings` (pydantic-settings, `.env`). Holds `PASSIVE_ONLY`. |
| `app/i18n.py`          | Backend user-facing strings (`en`, `pt`). |
| `app/db/schema.py`     | Label/axis/layer/relationship enums, allowed-edge table, constraint & index DDL. |
| `app/db/driver.py`     | `Neo4jClient`: async driver lifecycle, `verify()`, idempotent `ensure_schema()`, `run()`. |
| `app/db/queries.py`    | Parametrised Cypher strings. |
| `app/deps.py`          | FastAPI dependencies; DB dependency turns an unreachable Neo4j into a 503. |
| `app/routers/health.py`| `GET /health`. |
| `app/main.py`          | App factory, lifespan (connect + schema), static mount. |
| `app/desktop.py`       | Desktop shell: engine thread on a free loopback port, health wait, native window. |
| `app/cli.py`           | `osintree` (opens the window), `osintree schema \| reset --yes \| seed`. |
| `app/errors.py`        | Domain errors (`NotFound`, `Conflict`, `InvalidEdge`) mapped to HTTP + localized messages in `main.py`. |
| `app/models/nodes.py`  | Node envelope (`NodeCreate/Update/Out`) and one typed attribute model per label (`ATTR_MODELS`); environment and remote-auth inference. |
| `app/models/edges.py`  | `EdgeCreate/Update/Out`, `GraphOut`. |
| `app/models/projects.py` | Project models; the target (org name, seed domain) is supplied here at runtime. |
| `app/models/schema_info.py` | `GET /api/schema` payload: labels, fields, rel types, allowed edges. Drives the UI palette. |
| `app/graph/crud.py`    | Node/edge CRUD; refuses disallowed `(source, rel, target)` triples with a hint; stamps provenance; computes `cross_axis`. |
| `app/graph/projects.py`| Project CRUD; creating a project with `org_name` creates its `Organizacao` anchor. |
| `app/graph/io.py`      | Export (`osintree/1`, lossless incl. ids/provenance) and import: typed files (ids kept unless they collide) and the reference tool's legacy `{meta, nodes, edges}` format (best-effort, warnings, anchoring edges, unknown types become re-typable defaults). |
| `app/collectors/base.py` | `Collector` interface (`name`, `interacts_with_target`, `axis`, `input_kind`, `source_family`), `Finding`/`FindingEdge`, `RunContext`, guard error. |
| `app/collectors/http.py` | Shared `httpx` client: timeouts, per-host rate limiting, retry/backoff, 24 h on-disk cache. |
| `app/collectors/{crtsh,rdap,bgp,nvd}.py` | Built-in passive collectors; each docstring names its thesis source family. |
| `app/collectors/active_example.py` | Stub with `interacts_with_target = True`; refused by the guard, never contacts anything. |
| `app/collectors/registry.py` | Discovery, **passive guard** (`check_passive_guard`, applied before seed resolution), seed resolution from a node or a string, run pipeline collect → stage. |
| `app/review/staging.py` | `:Candidate` store (never `:Entity`); dedupe against pending/approved/in-graph; edit; **merge-on-approve** (`reviewed = true`, `source = collector`); reject; purge. |
| `app/models/analysis.py` | `AnalysisResult` and its parts (`Criterion`, `PathResult`, `RiskEdge`, `CentralityEntry`, `Inventory`), `AnalysisOptions`. |
| `app/analysis/risk.py` | Tabela 8 rules (`IMPACT_RULES`, matched on endpoint labels in either direction with preconditions), probability heuristic (`estimate_probability`, evidence keys), Tabela 2 matrix (`RISK_MATRIX`, `risk_level`), `stamp_project` writes `impact`/`probability`/`risk_level` to edges honouring `*_manual` overrides. Pure functions over `NodeOut`/`EdgeOut`. |
| `app/analysis/paths.py` | Seed resolution (`Organizacao` anchor, else seed `Dominio`); Cypher `shortestPath` seed → OT with the anchoring hop reversed; GDS Dijkstra over `weight` via a Cypher projection (anchoring edges collapsed into an undirected `ANCHOR` type); GDS degree/betweenness with a Cypher-degree fallback. Entry policy `digital` (Dominio entry points) or `any`. In-memory GDS graphs are always dropped. |
| `app/analysis/criteria.py` | The three criteria and `analyse()`, the orchestrator producing one `AnalysisResult`. |
| `app/analysis/report.py` | One document model rendered to Markdown and HTML (inline CSS, no assets), plus JSON (`osintree-report/1` = analysis + graph). Strings from `app/i18n.py` (`pt`/`en`). |
| `app/graph/fixture.py` | Fictional fixture project (`osintree seed`, e2e tests): `.test` domains, RFC 5737 addresses, all six Tabela 8 rows fire, both path variants differ. |
| `app/routers/*.py`     | `schema`, `projects`, `nodes`, `edges`, `io`, `collectors`, `review`, `analysis` (all under `/api`). |

## Data model conventions

- Every typed node carries the thesis label (e.g. `:Dominio`) **and** the internal `:Entity`
  label, which backs the single `id` uniqueness constraint and the `project_id` index.
- Projects are `:Project` nodes; candidates awaiting review are `:Candidate` nodes and never
  carry `:Entity`, so they cannot leak into graph queries.
- Relationship ids are indexed per type (`rel_<type>_id`).

## Front-end modules

| File | Responsibility |
|------|----------------|
| `js/i18n.js`   | All UI strings (`en`, `pt`), `t()`, `apply()`, `setLocale()` (topbar switcher; a change reloads the page because panels are rendered from strings). |
| `js/api.js`    | `fetch` wrapper; errors carry the server's `detail`; sends `X-Locale` so backend error messages match the UI language. |
| `js/schema.js` | Loads `/api/schema`; display names, axis colours, shapes, `allowedRels(src, dst)`. |
| `js/modals.js` | Modal host, confirm dialog, schema-driven form inputs. |
| `js/graph.js`  | vis-network canvas; mirrors backend state only; drag-to-connect hook; edge colour by impact; path overlay (`highlightPath`/`clearHighlight`); axis clustering (`toggleCluster`: one vis cluster per axis, click to open, expanded automatically before any overlay/relayout/select); legend (built from the schema colours); `fitView` fits the path while an overlay is on, the whole graph otherwise. |
| `js/collectors.js` | Tools panel: run collectors on the seed or the selected node; blocked collectors shown locked; review badge. Manual OSINT tool reference list (links only). |
| `js/review.js` | Review queue modal: pending/approved/rejected tabs, inline edit, approve/reject (single and bulk), purge. |
| `js/editor.js` | Entity editor: title, typed attributes, layer, description, Markdown notes (marked preview), metadata, neighbours, provenance; debounced autosave; re-type dialog; edge editor (impact/probability override or “auto”, risk level, weight, notes). |
| `js/analysis.js` | Analysis tab: run (entry policy, weighted toggle), criteria cards, path cards with canvas highlight, ranked high-impact and unclassified cross-axis edges (click → edge editor), centrality, report download/open (format + locale). |
| `js/app.js`    | Glue: projects, toolbar, tools-panel tabs, node/edge dialogs, selection → editor, language switcher, health polling with an “engine unreachable” banner (reloads the project once the engine is back), global `error`/`unhandledrejection` → toast. Exposes `window.App`. |

Node property storage: attribute models are flattened onto the Neo4j node (so `Dominio.name`,
`Endereco_IP.address`, `CVE.cve_id` indexes apply); `metadata` is stored as `metadata_json`.

## Collection and review flow

```
seed / selected node ─▶ registry.run ─▶ passive guard ─▶ collector.collect ─▶ Finding[]
                                                                        │
                                            :Candidate (pending) ◀── staging.stage (dedupe)
                                                    │
                    analyst: edit ─▶ approve ─▶ staging.approve ─▶ crud.create_node / update_node + edges
                                     reject  ─▶ status = rejected (kept for audit, purgeable)
```

A finding is either a new node, an enrichment (`node_update`: fills empty attributes, merges
metadata, appends notes) or a link (`edge`), plus edges to nodes that already exist in the
graph. Merge stamps `source = <collector>`, the run's `collected_at`, and `reviewed = true`.

## Import / export

`GET /api/projects/{id}/export` returns the typed format (`format: "osintree/1"`) as a download.
`POST /api/projects/import` detects the format: typed files round-trip losslessly (ids are kept
unless they already exist, in which case all ids are remapped); legacy files are migrated with a
warning list. Downloads inside the native window go through pywebview's Save dialog.

## Analysis flow

```
POST /api/projects/{id}/analysis?entry=digital|any   (body: AnalysisOptions)
  risk.stamp_project   graph -> Evidence -> assess each edge -> SET impact/probability/risk_level
  paths.shortest_path_to_ot   Cypher shortestPath, anchoring hop reversed          -> PathResult
  paths.weighted_path_to_ot   GDS Cypher projection + allShortestPaths.dijkstra    -> PathResult
  paths.centrality            GDS degree + betweenness (undirected projection)     -> top N
  criteria.*                  axis coverage / seed-to-OT / high impact             -> AnalysisResult
GET  /api/projects/{id}/report?format=md|html|json&locale=pt|en&entry=...   re-runs, renders
```

Edge risk fields are engine-owned unless flagged `impact_manual` / `probability_manual`
(set by a PATCH with a value, or by a value given at creation/import); `*_manual: false`
clears the override and the stale `risk_level`.

## Resilience

The API starts even if Neo4j is down (`/health` reports `degraded`). Schema application is
lazy and idempotent: the first successful connectivity check applies it. The UI polls
`/health` every 15 s; while the engine or the database is down it shows a banner and, when
they return, reloads the current project so the canvas mirrors the database again.

## Offline operation

After `make install`, the app needs no network: the front-end libraries and fonts are
vendored under `frontend/vendor/` (`scripts/vendor-frontend.sh` pins the versions in
`frontend/vendor/VERSIONS`), the HTML report inlines its CSS, and the engine only opens
outbound connections inside a collector run. `backend/tests/test_offline.py` enforces this
by scanning the served files and the rendered report for external asset references.

## Tests

| Layer | Files | Needs |
|-------|-------|-------|
| Unit (schema, models, collectors' parsers, risk engine, criteria, report, offline guarantee, desktop shell) | `test_schema.py`, `test_models.py`, `test_schema_api.py`, `test_health.py`, `test_collectors_unit.py`, `test_analysis_unit.py`, `test_offline.py`, `test_desktop.py` | nothing (fake DB, `respx`-mocked HTTP) |
| Integration (CRUD, import/export, staging/merge, analysis, paths) | `test_crud_integration.py`, `test_io_integration.py`, `test_review_integration.py`, `test_analysis_integration.py` | live Neo4j (auto-skip when down; `OSINTREE_REQUIRE_NEO4J=1` turns the skip into a failure, as CI does) |
| End-to-end smoke | `test_smoke_e2e.py` | live Neo4j; third-party HTTP mocked from recorded fixtures |

No test makes a live network call: `respx` runs with `assert_all_mocked=True`, so an
unexpected URL fails the test. `.github/workflows/ci.yml` runs lint + unit tests, then the
full suite against a Neo4j service container with APOC and GDS.
