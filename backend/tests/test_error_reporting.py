"""Errors the UI shows verbatim: body validation as one readable string, collector
upstream failures as a typed 502 instead of a bare 500 (the desktop toast shows ``detail``)."""

from __future__ import annotations

import httpx
import pytest

from app.collectors import registry
from app.collectors.base import Collector, CollectorUpstreamError, Finding, InputKind, RunContext
from app.collectors.http import CollectorHTTP
from app.db.schema import Axis
from app.models.nodes import SoftwareAttrs


async def test_body_validation_detail_is_a_readable_string(client):
    r = await client.post(
        "/api/projects/p1/nodes",
        json={"label": "Endereco_IP", "attrs": {"address": "192.168.0.0/24"}},
    )
    assert r.status_code == 422
    body = r.json()
    assert isinstance(body["detail"], str)
    assert body["detail"].startswith("address: ")
    assert "IPv4 or IPv6" in body["detail"]
    assert body["code"] == "error.validation"
    assert body["errors"][0]["loc"] == ["address"]

    r = await client.post("/api/projects/p1/nodes", json={"label": "Dominio", "attrs": {}})
    assert r.status_code == 422 and r.json()["detail"].startswith("name: ")


def test_software_title_omits_missing_version():
    assert SoftwareAttrs(product="nginx").default_title() == "nginx"
    assert SoftwareAttrs(product="nginx", version="1.2").default_title() == "nginx 1.2"


async def test_collector_input_error_carries_the_specific_reason(client):
    # The project lookup answers nothing on the fake DB, so the run stops at 404: the seed
    # check is unit-tested through registry.resolve_seed elsewhere. What matters here is the
    # DomainError handler appending the collector's own reason to the localised sentence.
    from app.collectors.base import CollectorInputError
    from app.main import create_app

    app = create_app()
    handler = app.exception_handlers[CollectorInputError.__mro__[1]]
    resp = await handler(
        httpx.Request("POST", "http://test/x"),  # type: ignore[arg-type]
        CollectorInputError("the 'crtsh' collector needs a domain seed"),
    )
    body = resp.body.decode()
    assert "needs a domain seed" in body and "cannot run with that input" in body


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (
            httpx.ReadTimeout("", request=httpx.Request("GET", "https://crt.sh/?q=x")),
            "crt.sh: ReadTimeout",
        ),
        (
            httpx.ConnectError(
                "[Errno -2] Name or service not known",
                request=httpx.Request("GET", "https://web.archive.org/cdx"),
            ),
            "web.archive.org: [Errno -2]",
        ),
        (CollectorUpstreamError("crt.sh returned HTTP 404"), "crt.sh returned HTTP 404"),
    ],
)
async def test_collect_failures_become_upstream_errors(
    settings, tmp_path, exc, expected, monkeypatch
):
    class Boom(Collector):
        name = "boom"
        description = "always fails"
        source_family = "CT logs"
        axis = Axis.DIGITAL
        input_kind = InputKind.DOMAIN

        async def collect(self, seed: str, ctx: RunContext) -> list[Finding]:
            raise exc

    class FakeProjects:
        @staticmethod
        async def get_project(db, pid):
            class P:
                seed_domain = "example.com"
                org_name = None
                root_node_id = None

            return P()

    class FakeCrud:
        @staticmethod
        async def list_nodes(db, pid):
            return []

    monkeypatch.setitem(registry.REGISTRY, "boom", Boom())
    monkeypatch.setattr(registry, "projects", FakeProjects)
    monkeypatch.setattr(registry, "crud", FakeCrud)
    http = CollectorHTTP(tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(CollectorUpstreamError) as info:
        await registry.run("boom", "p1", None, settings, http, seed="example.com")  # type: ignore[arg-type]
    err = info.value
    assert err.status_code == 502 and err.key == "error.collector_upstream"
    assert err.extra["collector"] == "boom"
    assert expected in err.extra["reason"]
    await http.aclose()
