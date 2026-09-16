"""Example of an *active* collector, present only to demonstrate the passive guard.

It performs no network action at all: with ``PASSIVE_ONLY=true`` (the default) the registry
refuses it before ``collect`` runs, which is what the thesis requires for anything that
would touch the target's own infrastructure (DNS resolution, port probes, web fetches).
Even with the guard off it does nothing, so the built-in set stays passive.
"""

from __future__ import annotations

from app.collectors.base import Collector, Finding, InputKind, RunContext
from app.db.schema import Axis, NodeLabel


class ActiveProbeExample(Collector):
    name = "active_probe_example"
    description = "Direct DNS/port probe of the target (blocked by the passive guard; stub)"
    source_family = "active (out of scope)"
    axis = Axis.DIGITAL
    input_kind = InputKind.DOMAIN
    input_label = NodeLabel.DOMINIO
    interacts_with_target = True

    async def collect(self, seed: str, ctx: RunContext) -> list[Finding]:
        raise NotImplementedError(
            "active collection is deliberately not implemented; this stub exists to show the guard"
        )
