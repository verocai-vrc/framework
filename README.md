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
> `python3 -m venv .venv && pip install -e ".[dev]"` automatically when `uv` is absent.

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
| `make seed`    | Load the fixture project (from Sprint 4)                            |
| `make reset`   | **Wipe the database** and re-apply the schema                       |

## Configuration

All settings come from `.env` (see `.env.example`). The important one:

```
PASSIVE_ONLY=true
```

Leave it on. Every built-in collector queries third-party repositories (Certificate
Transparency, RDAP, RIR/BGP data, NVD) and never the target. A collector that declares
`interacts_with_target = True` is refused before it runs while this flag is on.

## Project status

Built sprint by sprint from `project-brief.md`:

- [x] Sprint 0 — foundations: Neo4j, health-checked API, schema, UI shell
- [x] Sprint 1 — typed graph core and manual CRUD
- [ ] Sprint 2 — editor, notes, projects, import/export
- [ ] Sprint 3 — passive collectors with review gate
- [ ] Sprint 4 — correlation and risk analysis, report
- [ ] Sprint 5 — polish, packaging, docs

See `ARCHITECTURE.md` for the code map and `METHODOLOGY_MAPPING.md` for how the thesis
tables map onto the schema and analysis engine.

## License

MIT — see `LICENSE`.
