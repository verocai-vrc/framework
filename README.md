# OSINTree

> Working name — will be renamed before release.

A local, single-user **desktop application** for mapping the **passive, externally observable attack surface**
of an organization as a directed graph: collect open-source intelligence from third-party
sources (never the target itself), review every finding by hand before it enters the graph,
and reason over the result with the validation criteria of the accompanying thesis.

- **Passive-only by default.** `PASSIVE_ONLY=true` refuses any collector that would touch
  the target's own infrastructure.
- **Human-in-the-loop.** Collectors write to a review queue; only approved items are merged.
- **Provenance on everything.** Every node and edge records `source`, `collected_at`, `reviewed`.
- **Keyless, offline-capable, target-agnostic.** No API keys, no CDN at runtime, no built-in
  scenario; the target is a project seed you supply.

Stack: Python 3.12+ · FastAPI · Neo4j Community 5.26 (APOC + GDS) · vanilla JS + vis-network.

---

## Quickstart (Ubuntu, from zero)

The app runs entirely on your machine: `osintree` opens a native window and runs its engine
in the same process on the loopback interface. Neo4j runs either in Docker (recommended if
you already have it) or as a native service (no Docker needed).

### 1. Get the code and Python tooling

```bash
sudo apt update && sudo apt install -y git make curl
# Native window toolkit (already present on Ubuntu Desktop; needed on minimal installs)
sudo apt install -y python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
git clone <this-repo> osintree && cd osintree
cp .env.example .env            # defaults are fine for local use

# Python dependency manager (no sudo; installs to ~/.local/bin)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc                # or open a new terminal
make install                    # creates .venv and installs pinned dependencies
```

> Prefer plain `pip`? `sudo apt install python3-venv`, then `make install` falls back to
> a venv plus `pip install -r requirements-dev.txt` (pinned to the same versions as
> `uv.lock`) automatically when `uv` is absent.

### 2a. Neo4j with Docker (recommended if you can use Docker)

If you have never used Docker, this is the whole setup on Ubuntu:

```bash
# Install Docker Engine + Compose plugin from Docker's repository
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Let your user run docker without sudo (log out and back in afterwards)
sudo usermod -aG docker $USER
```

Then, from the repo:

```bash
make up          # pulls neo4j:5.26 with APOC + GDS and starts it in the background
make status      # wait until the container is "healthy" (about 30 s the first time)
```

Data persists in a Docker volume (`neo4j_data`) across restarts. `make down` stops it.

### 2b. Neo4j natively (no Docker)

```bash
sudo -v && bash scripts/install-neo4j-native.sh
```

The script installs Java 21, Neo4j Community 5.26 (LTS) from Neo4j's apt repository, drops
the APOC and GDS jars into `/var/lib/neo4j/plugins`, binds Neo4j to `127.0.0.1`, sets the
password from your `.env`, and enables the `neo4j` systemd service. Afterwards set
`NEO4J_MODE=native` in `.env` so `make up` / `make down` drive `systemctl` instead of Docker.

### 3. Open Neo4j Browser (optional)

Visit <http://localhost:7474>, connect with user `neo4j` and the password from `.env`
(default `osintree-dev`). Run `RETURN apoc.version(), gds.version()` to confirm the plugins.

### 4. Run the app

```bash
make app         # opens the OSINTree window (equivalent: uv run osintree)
```

The header shows a green **Neo4j connected** badge when the engine reached the database.

> Launch from a regular terminal, not from a snap-packaged terminal (e.g. VS Code's
> integrated terminal when VS Code is installed as a snap): snaps inject their own GTK
> library paths, which breaks the native window.

Developer mode: `make dev` runs the engine alone with auto-reload on
`http://127.0.0.1:8000` (interactive API docs at `/docs`); `uv run osintree --browser`
opens the UI in your default browser instead of a window.

### 5. Try it

```bash
make seed        # loads the fictional “Example Utility” project
```

Open the **Analysis** tab and press **Run analysis**: the three thesis criteria pass and
the seed → OT path lights up on the canvas. Then create your own project (**＋ New
project**, with the target's name and seed domain) and start from the **Collectors** tab.

---

## Using the workspace

Three panels, Obsidian-style: the **graph** (top left), the **tools** (bottom left:
collectors, analysis, review queue, import/export) and the **entity editor** (right).

- **Canvas**: `＋ Node` adds a typed node; `→ Edge` (or dragging from one node to another)
  creates a relationship and only offers the types the thesis schema allows between those
  two labels; `Delete`/`Backspace` removes the selection; `⟳ Layout` re-runs the layout;
  double-click the background to fit; `Esc` cancels connect mode or clears the path overlay.
- **⊞ Axes** collapses every axis into one node so a large graph reads as the four thesis
  axes; click a cluster to open it. The **legend** (bottom right of the canvas) explains
  colours, shapes, dashed extension relationships, impact colours and the path overlay.
- **Editor**: title, typed attributes, layer (TI/TO), description, Markdown notes with
  preview, free metadata, neighbours, provenance; everything autosaves. Selecting a
  relationship shows its impact / probability / risk, overridable per edge.
- **Language**: the `EN`/`PT` selector in the header switches the interface; the report
  language is chosen separately when exporting.

---

## Everyday commands

| Command        | What it does                                                        |
|----------------|---------------------------------------------------------------------|
| `make up/down` | Start / stop Neo4j (Docker or native, per `NEO4J_MODE`)             |
| `make app`     | Open the desktop app                                                |
| `make dev`     | Developer mode: engine only, auto-reload, browser at :8000          |
| `make test`    | Full test suite; Neo4j integration tests skip if the DB is down     |
| `make lint`    | `ruff check` + format check                                         |
| `make schema`  | Apply and verify constraints/indexes                                |
| `make seed`    | Load the fictional fixture project (all three criteria pass)        |
| `make reset`   | **Wipe the database** and re-apply the schema                       |

## Collectors (all passive, all keyless)

| Collector | Thesis source family | Input | Produces |
|-----------|----------------------|-------|----------|
| `crtsh`   | CT logs              | seed domain (or a selected `Dominio`) | `Dominio` candidates anchored to the `Organizacao` |
| `rdap`    | RDAP/WHOIS           | selected `Endereco_IP`, or an IP/ASN | enrichment of the address; `Fornecedor` (registrant) with `MANTEM_ACESSO_A` |
| `bgp`     | ASN/BGP (RIPEstat)   | selected `Endereco_IP`, or an IP/ASN | enrichment (origin ASN); `Fornecedor` (ASN holder) with `MANTEM_ACESSO_A` |
| `nvd`     | NVD/CVE              | selected `Software` | `CVE` candidates with `POSSUI_VULNERABILIDADE` |

Results never enter the graph directly: they land in the **review queue**, where each
candidate is approved (merged with `reviewed = true` and `source = <collector>`), edited
first, or rejected. Responses are cached on disk for 24 h under `.cache/collectors/` and
requests are rate-limited per host (NVD: one request every 6 s, the unauthenticated limit).

`active_probe_example` is a stub that declares `interacts_with_target = True` and performs
no network action; it exists to demonstrate the guard refusing it.

## Analysis and report

The **Analysis** tab (tools panel) runs the engine on the current project and never
collects anything:

1. every relationship is classified — **impact** from thesis Tabela 8, a heuristic
   **probability**, and the **risk level** from Tabela 2 — and the values are stamped on
   the edges (canvas colours follow the impact; the edge editor lets you override impact
   or probability per relationship, or hand them back to the engine with “auto”);
2. the three validation criteria are evaluated: ≥ 3 of 4 axes covered, a directed
   seed → OT path exists, ≥ 1 cross-axis relationship is CRITICO/ALTO;
3. the seed → OT path is highlighted on the canvas — the shortest one by hops (Cypher
   `shortestPath`) and, when the GDS plugin is installed, the cheapest one by attacker
   effort (Dijkstra over each edge's `weight`, default 1). *Entry* chooses which anchored
   nodes may start the path: domains only (the public seed, default) or any anchored node
   (employees, facilities, suppliers);
4. central nodes (GDS degree/betweenness, plain degree without GDS) are listed.

**Report**: Markdown, HTML (self-contained, printable) or JSON (analysis + full graph),
in Portuguese (default, `REPORT_LOCALE`) or English. `make seed` loads a fictional
“Example Utility” project that satisfies all three criteria, to try this out.

## Testing

```bash
make test        # everything; integration tests skip when Neo4j is down
make test-unit   # schema, models, collectors' parsers, risk engine, report — no Neo4j, no network
make test-e2e    # one end-to-end smoke run: seed → collect (recorded) → review → analysis → report → export/import
make check       # ruff + full suite, the same as CI
```

No test contacts the network: collector tests replay recorded responses under
`backend/tests/fixtures/collectors/` and any unexpected URL fails the test. The GitHub
Actions workflow (`.github/workflows/ci.yml`) runs the unit tests, then the full suite
against a Neo4j 5.26 service container with APOC and GDS.

## Offline use

After `make install` the app runs without Internet: the UI libraries and fonts are
vendored in `frontend/vendor/` (versions in `frontend/vendor/VERSIONS`; regenerate with
`make vendor`, which needs `npm` only at that moment), reports are self-contained files,
and the engine opens outbound connections only while a collector run is in progress.
`backend/tests/test_offline.py` checks that no served file or report references an
external asset.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Header badge says **Neo4j unavailable** | `make status`; start it with `make up`. Check `NEO4J_PASSWORD` in `.env` matches the database (Docker sets it on first start only — `docker compose down -v` resets the volume). |
| Window opens blank / GTK errors | Launch from a plain terminal (not a snap-packaged one), or install the toolkit: `sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1`. Without GTK, `uv sync --extra qt` and the window falls back to Qt. |
| `make` not found | `sudo apt install make`, or run the commands from the `Makefile` directly. |
| Analysis says **GDS unavailable** | The weighted path and betweenness need the Graph Data Science plugin; the Docker image installs it (`NEO4J_PLUGINS`), the native script copies the jar. Confirm with `RETURN gds.version()` in Neo4j Browser. Everything else works without it. |
| Collector returns nothing | Results are cached for 24 h in `.cache/collectors/`; delete the directory to refetch. NVD is rate-limited to one request per 6 s without an API key (keys are deliberately not supported). |
| `make reset` | Wipes **all** projects in the database. Export first (`↓ Export JSON`). |

## Configuration

All settings come from `.env` (see `.env.example`). The important one:

```
PASSIVE_ONLY=true
```

Leave it on. Every built-in collector queries third-party repositories (Certificate
Transparency, RDAP, RIR/BGP data, NVD) and never the target. A collector that declares
`interacts_with_target = True` is refused before it runs while this flag is on.

## Responsible use

OSINTree only reads public, third-party sources and never probes the organization under
study, but mapping someone's attack surface is still sensitive work. Use it on
organizations you are authorized to assess (your own, a client's under contract, or a
research subject with the relevant approval), keep exported projects and reports
confidential, and follow the disclosure norms of your jurisdiction if you find something
exploitable. The fixture project is fictional; `CVE-2018-13379` is the only real
identifier in it and appears purely as an example.

## Project status

Built sprint by sprint from `project-brief.md`:

- [x] Sprint 0 — foundations: Neo4j, health-checked API, schema, UI shell
- [x] Sprint 1 — typed graph core and manual CRUD
- [x] Sprint 2 — editor, notes, projects, import/export
- [x] Sprint 3 — passive collectors with review gate
- [x] Sprint 4 — correlation and risk analysis, report
- [x] Sprint 5 — polish (legend, axis clustering, language switcher, offline banner), packaging (pinned requirements, CI), docs, smoke test

See `ARCHITECTURE.md` for the code map and `METHODOLOGY_MAPPING.md` for how the thesis
tables map onto the schema and analysis engine.

## License

MIT — see `LICENSE`.
