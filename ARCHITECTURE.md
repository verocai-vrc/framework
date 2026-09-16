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
| `app/routers/*.py`     | `schema`, `projects`, `nodes`, `edges` (all under `/api`). |

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
| `js/app.js`    | Glue: projects, toolbar, node/edge dialogs, selection → editor. Exposes `window.App`. |

Node property storage: attribute models are flattened onto the Neo4j node (so `Dominio.name`,
`Endereco_IP.address`, `CVE.cve_id` indexes apply); `metadata` is stored as `metadata_json`.

## Resilience

The API starts even if Neo4j is down (`/health` reports `degraded`). Schema application is
lazy and idempotent: the first successful connectivity check applies it.
