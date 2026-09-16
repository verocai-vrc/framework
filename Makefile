# OSINTree developer entry points. Run `make help` for a summary.
# Uses `uv` when available (https://docs.astral.sh/uv/); falls back to a plain venv.

-include .env
export

NEO4J_MODE ?= docker
PORT ?= 8000
HOST ?= 127.0.0.1

UV := $(shell command -v uv 2>/dev/null || echo $(HOME)/.local/bin/uv)
ifeq ($(wildcard $(UV)),)
  PY := .venv/bin/python
  RUN :=
else
  PY := $(UV) run python
  RUN := $(UV) run
endif

.PHONY: help install up down status app dev test test-unit test-int lint fmt schema seed reset vendor

help:
	@echo "make install   install Python dependencies (uv sync, or pip into .venv)"
	@echo "make up        start Neo4j (NEO4J_MODE=docker|native, from .env)"
	@echo "make down      stop Neo4j"
	@echo "make status    show Neo4j status"
	@echo "make app       open the desktop app (native window, engine in-process)"
	@echo "make dev       developer mode: engine only with auto-reload on http://$(HOST):$(PORT)"
	@echo "make test      run the whole test suite (integration tests skip without Neo4j)"
	@echo "make lint      ruff check + format check"
	@echo "make fmt       ruff format"
	@echo "make schema    apply/verify Neo4j constraints and indexes"
	@echo "make seed      load the fixture project (Sprint 4)"
	@echo "make reset     WIPE the database and re-apply the schema"
	@echo "make vendor    (re)copy front-end libraries into frontend/vendor"

# --system-site-packages lets the venv use the distro's GTK/WebKit bindings (python3-gi,
# gir1.2-webkit2-4.1) for the native window. Without them, install the `qt` extra instead.
install:
ifeq ($(RUN),)
	python3 -m venv --system-site-packages .venv && .venv/bin/pip install -e ".[dev]"
else
	$(UV) venv --system-site-packages --allow-existing && $(UV) sync --extra dev
endif

up:
ifeq ($(NEO4J_MODE),native)
	sudo systemctl start neo4j && echo "Neo4j (native) starting; browser at http://localhost:7474"
else
	docker compose up -d && echo "Neo4j (docker) starting; browser at http://localhost:7474"
endif

down:
ifeq ($(NEO4J_MODE),native)
	sudo systemctl stop neo4j
else
	docker compose down
endif

status:
ifeq ($(NEO4J_MODE),native)
	systemctl status neo4j --no-pager | head -5
else
	docker compose ps
endif

app:
	$(PY) -m app.cli

dev:
	$(RUN) uvicorn app.main:app --app-dir backend --host $(HOST) --port $(PORT) --reload

test:
	$(RUN) pytest -q

test-unit:
	$(RUN) pytest -q -m "not neo4j"

test-int:
	$(RUN) pytest -q -m neo4j

lint:
	$(RUN) ruff check . && $(RUN) ruff format --check .

fmt:
	$(RUN) ruff format . && $(RUN) ruff check --fix .

schema:
	$(PY) -m app.cli schema

seed:
	$(PY) -m app.cli seed

reset:
	$(PY) -m app.cli reset --yes

vendor:
	bash scripts/vendor-frontend.sh
