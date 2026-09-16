"""Neo4j driver lifecycle: a single async driver per process, lazy connectivity checks,
and idempotent schema application.

The app must start even when Neo4j is down (the UI shows a degraded health badge); any
request that needs the database gets a clear 503 instead of a crash.
"""

from __future__ import annotations

import logging
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase, Record, RoutingControl
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from app.config import Settings
from app.db import queries
from app.db.schema import SCHEMA_NAMES, SCHEMA_STATEMENTS

log = logging.getLogger(__name__)


class Neo4jUnavailable(RuntimeError):
    """Raised when a database-backed operation is attempted while Neo4j is unreachable."""


class Neo4jClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._driver: AsyncDriver | None = None
        self.schema_applied = False

    # --- lifecycle -----------------------------------------------------------------

    async def connect(self) -> None:
        s = self._settings
        self._driver = AsyncGraphDatabase.driver(
            s.neo4j_uri,
            auth=(s.neo4j_user, s.neo4j_password),
            connection_timeout=s.neo4j_connect_timeout,
            # "index already exists" notes from idempotent schema statements are not news.
            notifications_min_severity="WARNING",
        )

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    @property
    def driver(self) -> AsyncDriver:
        if self._driver is None:
            raise Neo4jUnavailable("driver not initialised")
        return self._driver

    async def verify(self) -> bool:
        """True when Neo4j answers; never raises."""
        try:
            await self.driver.verify_connectivity()
        except (ServiceUnavailable, Neo4jError, OSError, Neo4jUnavailable) as exc:
            log.debug("neo4j connectivity check failed: %s", exc)
            return False
        return True

    async def ensure_schema(self) -> bool:
        """Apply constraints and indexes once per process. Returns True when applied."""
        if self.schema_applied:
            return True
        if not await self.verify():
            return False
        for name, statement in SCHEMA_STATEMENTS:
            await self.run(statement)
            log.debug("schema statement applied: %s", name)
        self.schema_applied = True
        log.info("neo4j schema ensured (%d statements)", len(SCHEMA_STATEMENTS))
        return True

    async def schema_status(self) -> dict[str, list[str]]:
        """Names of expected constraints/indexes that exist vs are missing."""
        present = {r["name"] for r in await self.run(queries.SHOW_CONSTRAINT_NAMES)}
        present |= {r["name"] for r in await self.run(queries.SHOW_INDEX_NAMES)}
        return {
            "present": sorted(SCHEMA_NAMES & present),
            "missing": sorted(SCHEMA_NAMES - present),
        }

    # --- query helpers ---------------------------------------------------------------

    async def run(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        *,
        readonly: bool = False,
    ) -> list[Record]:
        """Run one parametrised Cypher statement in a managed transaction."""
        try:
            result = await self.driver.execute_query(
                query,
                parameters_=parameters or {},
                database_=self._settings.neo4j_database,
                routing_=RoutingControl.READ if readonly else RoutingControl.WRITE,
            )
        except (ServiceUnavailable, OSError) as exc:
            raise Neo4jUnavailable(str(exc)) from exc
        return result.records

    async def run_one(
        self, query: str, parameters: dict[str, Any] | None = None, *, readonly: bool = False
    ) -> Record | None:
        records = await self.run(query, parameters, readonly=readonly)
        return records[0] if records else None
