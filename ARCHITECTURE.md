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
| `app/routers/*.py`     | `schema`, `projects`, `nodes`, `edges`, `io`, `collectors`, `review` (all under `/api`). |

## Data model conventions

- Every typed node carries the thesis label (e.g. `:Dominio`) **and** the internal `:Entity`
  label, which backs the single `id` uniqueness constraint and the `project_id` index.
- Projects are `:Project` nodes; candidates awaiting review are `:Candidate` nodes and never
  carry `:Entity`, so they cannot leak into graph queries.
- Relationship ids are indexed per type (`rel_<type>_id`).

## Front-end modules

| File | Responsibility |
|------|----------------|
| `js/i18n.js`   | All UI strings (`en`, `pt`), `t()`, `apply()`. |
| `js/api.js`    | `fetch` wrapper; errors carry the server's `detail`. |
| `js/schema.js` | Loads `/api/schema`; display names, axis colours, shapes, `allowedRels(src, dst)`. |
| `js/modals.js` | Modal host, confirm dialog, schema-driven form inputs. |
| `js/graph.js`  | vis-network canvas; mirrors backend state only; drag-to-connect hook. |
| `js/collectors.js` | Tools panel: run collectors on the seed or the selected node; blocked collectors shown locked; review badge. Manual OSINT tool reference list (links only). |
| `js/review.js` | Review queue modal: pending/approved/rejected tabs, inline edit, approve/reject (single and bulk), purge. |
| `js/editor.js` | Entity editor: title, typed attributes, layer, description, Markdown notes (marked preview), metadata, neighbours, provenance; debounced autosave; re-type dialog; edge editor (impact override, weight, notes). |
| `js/app.js`    | Glue: projects, toolbar, node/edge dialogs, selection → editor. Exposes `window.App`. |

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

## Resilience

The API starts even if Neo4j is down (`/health` reports `degraded`). Schema application is
lazy and idempotent: the first successful connectivity check applies it.
