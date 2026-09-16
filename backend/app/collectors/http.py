"""Shared HTTP client for collectors: timeouts, polite per-host rate limiting, retry with
backoff, and an on-disk response cache so repeated runs are offline and reproducible."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

DEFAULT_TTL_S = 24 * 3600
RETRY_STATUSES = {429, 500, 502, 503, 504}


@dataclass
class CachedResponse:
    status_code: int
    url: str
    text: str
    from_cache: bool
    fetched_at: float

    def json(self) -> Any:
        return json.loads(self.text)


class CollectorHTTP:
    """One instance per process. ``min_interval`` is seconds between requests to a host."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        timeout: float = 20.0,
        user_agent: str = "OSINTree",
        ttl_s: int = DEFAULT_TTL_S,
        min_interval: dict[str, float] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.cache_dir = cache_dir / "collectors"
        self.ttl_s = ttl_s
        self.min_interval = {"default": 1.0, **(min_interval or {})}
        self._last_call: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            follow_redirects=True,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- cache --------------------------------------------------------------------------

    def _cache_path(self, url: str, params: dict[str, Any] | None) -> Path:
        key = hashlib.sha256(
            (url + "?" + json.dumps(params or {}, sort_keys=True)).encode()
        ).hexdigest()
        host = urlsplit(url).hostname or "unknown"
        return self.cache_dir / host / f"{key}.json"

    def _read_cache(self, path: Path) -> CachedResponse | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if time.time() - data["fetched_at"] > self.ttl_s:
            return None
        return CachedResponse(
            data["status_code"], data["url"], data["text"], True, data["fetched_at"]
        )

    def _write_cache(self, path: Path, resp: CachedResponse) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "status_code": resp.status_code,
                        "url": resp.url,
                        "text": resp.text,
                        "fetched_at": resp.fetched_at,
                    }
                ),
                encoding="utf-8",
            )
        except OSError as exc:  # cache is best-effort
            log.warning("could not write cache %s: %s", path, exc)

    # --- rate limiting ------------------------------------------------------------------

    async def _throttle(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            interval = self.min_interval.get(host, self.min_interval["default"])
            wait = self._last_call.get(host, 0.0) + interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call[host] = time.monotonic()

    # --- request ------------------------------------------------------------------------

    async def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
        retries: int = 3,
    ) -> CachedResponse:
        path = self._cache_path(url, params)
        if use_cache and (cached := self._read_cache(path)) is not None:
            return cached
        host = urlsplit(url).hostname or "unknown"
        delay = 2.0
        last_exc: Exception | None = None
        for attempt in range(retries):
            await self._throttle(host)
            try:
                r = await self._client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                log.info("%s attempt %d failed: %s", host, attempt + 1, exc)
            else:
                if r.status_code not in RETRY_STATUSES:
                    resp = CachedResponse(r.status_code, str(r.url), r.text, False, time.time())
                    if use_cache and r.status_code == 200:
                        self._write_cache(path, resp)
                    return resp
                retry_after = r.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = max(delay, float(retry_after))
                log.info("%s returned %d, backing off %.0fs", host, r.status_code, delay)
            await asyncio.sleep(delay)
            delay *= 2
        if last_exc is not None:
            raise last_exc
        raise httpx.HTTPStatusError("gave up after retries", request=r.request, response=r)
