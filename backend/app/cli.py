"""Command-line entry point.

``osintree`` with no subcommand opens the desktop window (see ``app.desktop``). The
subcommands ``schema``, ``reset --yes`` and ``seed`` are maintenance helpers.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable

from app import desktop
from app.config import get_settings
from app.db import queries
from app.db.driver import Neo4jClient


async def _with_client(fn: Callable[[Neo4jClient], Awaitable[int]]) -> int:
    client = Neo4jClient(get_settings())
    await client.connect()
    try:
        if not await client.verify():
            print("error: Neo4j is unreachable; is it running? (make up)", file=sys.stderr)
            return 2
        return await fn(client)
    finally:
        await client.close()


async def cmd_schema(client: Neo4jClient) -> int:
    await client.ensure_schema()
    status = await client.schema_status()
    print(f"present: {len(status['present'])}  missing: {len(status['missing'])}")
    for name in status["missing"]:
        print(f"  missing: {name}")
    return 0 if not status["missing"] else 1


async def cmd_reset(client: Neo4jClient) -> int:
    await client.run(queries.DELETE_EVERYTHING)
    client.schema_applied = False
    await client.ensure_schema()
    print("database wiped; schema re-applied")
    return 0


async def cmd_seed(client: Neo4jClient) -> int:
    """Load the fictional fixture project (satisfies all three validation criteria)."""
    from app.graph.fixture import seed_fixture

    await client.ensure_schema()
    project = await seed_fixture(client)
    print(f"seeded project '{project.name}' ({project.node_count} nodes, "
          f"{project.edge_count} edges) id={project.id}")  # fmt: skip
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="osintree", description="passive OSINT attack-surface mapper"
    )
    desktop.add_arguments(parser)
    sub = parser.add_subparsers(dest="command", required=False)
    sub.add_parser("schema", help="apply and verify constraints/indexes")
    reset = sub.add_parser("reset", help="DELETE ALL DATA and re-apply the schema")
    reset.add_argument("--yes", action="store_true", help="confirm the wipe")
    sub.add_parser("seed", help="load the fictional fixture project (all three criteria pass)")
    args = parser.parse_args(argv)

    if args.command is None:
        return desktop.run(browser=args.browser, port=args.port)
    if args.command == "schema":
        return asyncio.run(_with_client(cmd_schema))
    if args.command == "reset":
        if not args.yes:
            print("refusing to wipe the database without --yes", file=sys.stderr)
            return 2
        return asyncio.run(_with_client(cmd_reset))
    if args.command == "seed":
        return asyncio.run(_with_client(cmd_seed))
    return 2


if __name__ == "__main__":
    sys.exit(main())
