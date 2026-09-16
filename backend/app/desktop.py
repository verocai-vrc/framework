"""Desktop shell: run the engine in-process and open the UI in a native window.

The engine is the FastAPI app served by Uvicorn on ``127.0.0.1`` at a free port that is
never exposed beyond loopback; the window is a pywebview WebView (WebKitGTK on Ubuntu)
pointed at it. Closing the window stops the engine. ``--browser`` is a developer
convenience that opens the same UI in the default browser instead of a window.
"""

from __future__ import annotations

import argparse
import logging
import socket
import threading
import time
import webbrowser
from dataclasses import dataclass

import httpx
import uvicorn

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

STARTUP_TIMEOUT_S = 20.0


def free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


@dataclass
class EngineHandle:
    """A running in-process engine and the thread driving it."""

    url: str
    server: uvicorn.Server
    thread: threading.Thread

    def stop(self, timeout: float = 10.0) -> None:
        self.server.should_exit = True
        self.thread.join(timeout)


def start_engine(
    settings: Settings, host: str = "127.0.0.1", port: int | None = None
) -> EngineHandle:
    """Serve the app on a background thread and block until ``/health`` answers."""
    port = port or free_port(host)
    config = uvicorn.Config(
        "app.main:app",
        host=host,
        port=port,
        log_level=settings.log_level.lower(),
        # The window is the only client; access logs are just noise there.
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="osintree-engine", daemon=True)
    thread.start()

    url = f"http://{host}:{port}"
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    with httpx.Client(timeout=1.0) as client:
        while time.monotonic() < deadline:
            if not thread.is_alive():
                raise RuntimeError("engine thread exited during startup")
            try:
                if client.get(f"{url}/health").status_code == 200:
                    return EngineHandle(url=url, server=server, thread=thread)
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
    server.should_exit = True
    raise RuntimeError(f"engine did not become healthy within {STARTUP_TIMEOUT_S:.0f}s")


def open_window(url: str, settings: Settings) -> None:
    """Open the native window and block until it is closed."""
    import webview  # imported lazily: the GUI toolkit is not needed for --browser or tests

    # Report/JSON downloads and the import file picker happen inside the WebView.
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.create_window(
        settings.app_name,
        url,
        width=1440,
        height=900,
        min_size=(1024, 640),
        text_select=True,
    )
    storage = settings.cache_dir / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    # private_mode=False keeps localStorage (UI preferences) across sessions.
    webview.start(private_mode=False, storage_path=str(storage))


def run(*, browser: bool = False, port: int | None = None) -> int:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    engine = start_engine(settings, port=port)
    log.info("engine ready at %s", engine.url)
    try:
        if browser:
            webbrowser.open(engine.url)
            print(f"{settings.app_name} engine running at {engine.url} (Ctrl+C to stop)")
            while engine.thread.is_alive():
                engine.thread.join(0.5)
        else:
            open_window(engine.url, settings)
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
    return 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--browser",
        action="store_true",
        help="developer mode: open the UI in the default browser instead of a native window",
    )
    parser.add_argument("--port", type=int, default=None, help="loopback port (default: free port)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="osintree", description="open the desktop app")
    add_arguments(parser)
    args = parser.parse_args(argv)
    return run(browser=args.browser, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
