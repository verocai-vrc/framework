"""Parametrised Cypher statements. Never interpolate user input into these strings; labels
and relationship types that must be spliced in are always taken from the schema enums.
"""

from __future__ import annotations

SHOW_CONSTRAINT_NAMES = "SHOW CONSTRAINTS YIELD name RETURN name"
SHOW_INDEX_NAMES = "SHOW INDEXES YIELD name RETURN name"

# Danger: wipes the whole database. Only reachable through the CLI ``reset`` command.
DELETE_EVERYTHING = "MATCH (n) DETACH DELETE n"

COUNT_NODES = "MATCH (n) RETURN count(n) AS count"
