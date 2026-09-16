"""Centralised backend user-facing strings (API error messages, report labels).

All strings that may reach a human live here, keyed by locale, so a Portuguese UI/report
can be produced without touching call sites. Front-end strings live in ``frontend/js/i18n.js``.
"""

from __future__ import annotations

import contextlib
from typing import Final

SUPPORTED_LOCALES: Final = ("en", "pt")

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "health.ok": "ok",
        "health.degraded": "degraded",
        "neo4j.connected": "connected",
        "neo4j.unavailable": "unavailable",
        "error.neo4j_unavailable": "Neo4j is unavailable. Start the database and retry.",
        "error.generic": "Request failed.",
        "error.not_found": "Not found.",
        "error.conflict": "This relationship already exists.",
        "error.validation": "Invalid data.",
        "error.invalid_edge": "{source_label} → {target_label} cannot use {rel}.",
        "error.invalid_edge.allowed": "Allowed here: {allowed}.",
        "error.invalid_edge.reverse": "The opposite direction allows: {reverse_allowed}.",
        "error.invalid_edge.none": "No relationship type connects these two labels.",
        "error.passive_guard": (
            "Collector '{collector}' would interact with the target and PASSIVE_ONLY is on. "
            "Refused."
        ),
        "error.collector_input": "This collector cannot run with that input.",
    },
    "pt": {
        "health.ok": "ok",
        "health.degraded": "degradado",
        "neo4j.connected": "conectado",
        "neo4j.unavailable": "indisponível",
        "error.neo4j_unavailable": "Neo4j indisponível. Inicie o banco de dados e tente novamente.",
        "error.generic": "A requisição falhou.",
        "error.not_found": "Não encontrado.",
        "error.conflict": "Essa relação já existe.",
        "error.validation": "Dados inválidos.",
        "error.invalid_edge": "{source_label} → {target_label} não pode usar {rel}.",
        "error.invalid_edge.allowed": "Permitido aqui: {allowed}.",
        "error.invalid_edge.reverse": "A direção oposta permite: {reverse_allowed}.",
        "error.invalid_edge.none": "Nenhum tipo de relação conecta esses dois rótulos.",
        "error.passive_guard": (
            "O coletor '{collector}' interagiria com o alvo e PASSIVE_ONLY está ativo. Recusado."
        ),
        "error.collector_input": "Este coletor não pode rodar com essa entrada.",
    },
}


def t(key: str, locale: str = "en", **vars: object) -> str:
    """Translate ``key`` for ``locale`` (fallback: English, then the key), filling ``{vars}``.

    ``allowed``/``reverse_allowed`` lists are joined so the message reads naturally; for
    ``error.invalid_edge`` the hint sentence is appended."""
    table = _STRINGS.get(locale) or _STRINGS["en"]
    text = table.get(key) or _STRINGS["en"].get(key, key)
    fmt = {k: ", ".join(v) if isinstance(v, list | tuple) else v for k, v in vars.items()}
    with contextlib.suppress(KeyError, IndexError):
        text = text.format(**fmt)
    if key == "error.invalid_edge" and "source_label" in vars:
        if vars.get("allowed"):
            text += " " + t("error.invalid_edge.allowed", locale, **vars)
        elif vars.get("reverse_allowed"):
            text += " " + t("error.invalid_edge.reverse", locale, **vars)
        else:
            text += " " + t("error.invalid_edge.none", locale)
    return text
