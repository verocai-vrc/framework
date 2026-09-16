from __future__ import annotations

import httpx
import pytest

from app import desktop


def test_free_port_is_bindable_loopback_port():
    port = desktop.free_port()
    assert 1024 < port < 65536


def test_engine_starts_in_process_and_stops(settings):
    """The desktop shell must bring the engine up on loopback and tear it down cleanly,
    without any window. Neo4j need not be running: /health answers ``degraded``."""
    engine = desktop.start_engine(settings)
    try:
        assert engine.url.startswith("http://127.0.0.1:")
        body = httpx.get(f"{engine.url}/health", timeout=2).json()
        assert body["app"] == settings.app_name
        assert body["neo4j"] in {"connected", "unavailable"}
        assert httpx.get(f"{engine.url}/", timeout=2).status_code == 200
    finally:
        engine.stop()
    assert not engine.thread.is_alive()
    with pytest.raises(httpx.HTTPError):
        httpx.get(f"{engine.url}/health", timeout=1)


def test_cli_without_subcommand_opens_desktop(monkeypatch):
    from app import cli

    calls: list[dict] = []
    monkeypatch.setattr(desktop, "run", lambda **kw: calls.append(kw) or 0)
    assert cli.main([]) == 0
    assert calls == [{"browser": False, "port": None}]
    assert cli.main(["--browser", "--port", "8123"]) == 0
    assert calls[-1] == {"browser": True, "port": 8123}
