"""Centralised backend user-facing strings (API error messages, report labels).

All strings that may reach a human live here, keyed by locale, so a Portuguese UI/report
can be produced without touching call sites. Front-end strings live in ``frontend/js/i18n.js``.
"""

from __future__ import annotations

from typing import Final

SUPPORTED_LOCALES: Final = ("en", "pt")

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "health.ok": "ok",
        "health.degraded": "degraded",
        "neo4j.connected": "connected",
        "neo4j.unavailable": "unavailable",
        "error.neo4j_unavailable": "Neo4j is unavailable. Start the database and retry.",
    },
    "pt": {
        "health.ok": "ok",
        "health.degraded": "degradado",
        "neo4j.connected": "conectado",
        "neo4j.unavailable": "indisponível",
        "error.neo4j_unavailable": "Neo4j indisponível. Inicie o banco de dados e tente novamente.",
    },
}


def t(key: str, locale: str = "en") -> str:
    """Translate ``key`` for ``locale``, falling back to English, then to the key itself."""
    table = _STRINGS.get(locale) or _STRINGS["en"]
    return table.get(key) or _STRINGS["en"].get(key, key)
