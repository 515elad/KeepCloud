"""Bypass suite: routes B-a to B-m and B-n1 to B-n12 that apply in the MVP.

Covered elsewhere: B-a/B-n7 (test_ledger), B-c, B-d, B-e, B-f, B-g, B-j, B-n5, B-n9
(test_gateway_path), B-i (test_ledger). Not applicable yet: B-b (phase 4),
B-l (phases 5 and 6), B-m (phase 3), B-n1/n3/n4/n12 (egress, not in the MVP),
B-n6 (no SDK), B-n8 (no replica).
"""

import logging
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from keepair.config import Settings
from keepair.demo.seed import agent_name, demo_clock, demo_token
from keepair.formulas import _tenant
from keepair.gateway import ledger
from keepair.gateway.adapters import ChatAdapter, DispatchPermit, MockVault, NoReservation
from keepair.gateway.app import ALLOWED_PATHS, DemoDataInProduction, create_gateway_app
from keepair.gateway.errors import GatewayError
from keepair.gateway.snapshot import SnapshotCache, load_from_database
from keepair.registry import add_block, decide_block
from keepair.rng import system_rng
from tests.gateway_harness import PROVIDER_URL, make_gateway

BODY = {
    "model": "vendor-a/model-1",
    "messages": [{"role": "user", "content": "x"}],
    "max_tokens": 5,
}


def adapter_for(gw) -> ChatAdapter:
    http = httpx.Client(transport=httpx.MockTransport(gw.router.handler))
    return ChatAdapter(gw.engine, http, MockVault())


def dispatch(adapter, permit, tenant):
    return adapter.dispatch(permit, tenant_id=tenant, vendor_id="vendor-a",
                            base_url="http://mock-provider:8090", body=BODY)  # fmt: skip


@pytest.mark.req("SEC-01", "Hard rule 6", "B-n6")
def test_no_dispatch_without_reservation(gw):
    """Calling an adapter directly, around the gateway, is refused and sends nothing."""
    adapter = adapter_for(gw)
    with gw.engine.begin() as conn:
        tenant = _tenant(conn)
        budget = gw.budget("Build Assistant").id
        make = lambda **kw: ledger.reserve(  # noqa: E731
            conn, clock=demo_clock(), rng=system_rng(), tenant_id=tenant,
            request_id=uuid.uuid4(), budget_id=budget, cost_micros=10, **kw)  # fmt: skip
        settled, released, expired, live = (
            make(),
            make(),
            make(limits=ledger.Limits(ttl_s=0)),
            make(),
        )
        held = ledger.reserve(conn, clock=demo_clock(), rng=system_rng(), tenant_id=tenant,
                              request_id=uuid.uuid4(), budget_id=gw.budget("Research Agent").id, cost_micros=10)  # fmt: skip
        ledger.settle(conn, settled.reservation_id, clock=demo_clock(), actual_micros=1)
        ledger.release(conn, released.reservation_id, clock=demo_clock())
    refused = [
        None,
        "a-string",
        uuid.uuid4(),  # a bare ID is not a permit
        DispatchPermit(uuid.uuid4()),  # made-up reservation
        DispatchPermit(settled.reservation_id),
        DispatchPermit(released.reservation_id),
        DispatchPermit(expired.reservation_id),
        DispatchPermit(held.reservation_id),  # held requests are not dispatched
    ]
    for permit in refused:
        with pytest.raises(NoReservation):
            dispatch(adapter, permit, tenant)
    assert not gw.provider.called
    # A live reservation dispatches exactly once.
    assert dispatch(adapter, DispatchPermit(live.reservation_id), tenant).status == 200
    with pytest.raises(NoReservation):
        dispatch(adapter, DispatchPermit(live.reservation_id), tenant)
    assert gw.provider.call_count == 1


@pytest.mark.req("SEC-01", "B-n11")
def test_no_passthrough_mode_exists():
    fields = set(Settings.model_fields)
    assert not [
        f for f in fields if any(w in f for w in ("passthrough", "bypass", "direct", "enforce"))
    ]
    import inspect

    import keepair.gateway.service as service

    source = inspect.getsource(service) + inspect.getsource(ChatAdapter)
    assert "passthrough" not in source.lower() and "pass_through" not in source.lower()
    assert source.count("self.adapter.dispatch(") == 1  # one call site, after reserve


@pytest.mark.req("SEC-03", "B-n2", "S-02")
@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", p) for p in (
        "/v1/embeddings", "/v1/files", "/v1/images/generations", "/v1/audio/speech", "/v1/batches",
        "/v1/realtime", "/v1/assistants", "/v1/responses", "/v1/completions", "/v1/chat/completions/x",
        "/v1/vendors/vendor-a/embeddings", "/chat/completions", "/v2/chat/completions",
    )] + [("GET", "/v1/chat/completions"), ("GET", "/v1/models"), ("DELETE", "/v1/chat/completions"),
          ("PUT", "/v1/vendors/vendor-a/chat/completions"), ("GET", "/"), ("GET", "/docs"), ("GET", "/openapi.json")],
)  # fmt: skip
def test_unlisted_provider_path_denied(gw, method, path):
    token = demo_token(agent_name("Build Assistant"))
    response = gw.client.request(
        method,
        path,
        json=BODY,
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "p"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PATH_NOT_ALLOWED"
    assert not gw.provider.called


@pytest.mark.req("SEC-03")
def test_allowlist_classifies_every_path_as_billable_or_not():
    assert {(m, p): billable for m, p, billable in ALLOWED_PATHS} == {
        ("POST", "/v1/chat/completions"): True,
        ("POST", "/v1/vendors/{vendor}/chat/completions"): True,
        ("GET", "/healthz"): False,
        ("GET", "/metrics"): False,
    }


@pytest.mark.req("FR-20 (the gateway is not an open proxy)", "SEC-02", "S-15")
def test_gateway_is_not_an_open_proxy(gw):
    token = demo_token(agent_name("Build Assistant"))
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "proxy"}
    for method, path in (("CONNECT", "/vendor-a.example:443"), ("POST", "/http://evil.example/v1/chat/completions"),
                         ("GET", "/proxy?url=http://evil.example")):  # fmt: skip
        assert gw.client.request(method, path, headers=headers).status_code == 404
    # A destination named in the body or a header changes nothing: the registry decides.
    body = BODY | {"base_url": "http://evil.example", "api_base": "http://evil.example"}
    spoof = {
        "X-Base-Url": "http://evil.example",
        "X-Forwarded-Host": "evil.example",
        "Host": "evil.example",
    }
    assert gw.chat(body=body, headers=spoof).status_code == 200
    assert str(gw.provider.calls.last.request.url) == PROVIDER_URL
    assert "base_url" not in gw.provider.calls.last.request.content.decode()


@pytest.mark.req("SEC-12", "SEC-14", "B-n9")
def test_token_cannot_reach_admin_routes(gw):
    """The gateway listener serves no admin or UI route at all."""
    token = demo_token(agent_name("Build Assistant"))
    headers = {"Authorization": f"Bearer {token}", "Origin": "http://testserver"}
    for method, path in (("POST", "/gateway/block"), ("GET", "/gateway"), ("GET", "/budgets"), ("GET", "/admin"),
                         ("POST", "/v1/admin/kill-switch"), ("PUT", "/v1/admin/vendors/vendor-b/status"),
                         ("POST", "/gateway/credentials")):  # fmt: skip
        response = gw.client.request(
            method, path, headers=headers, data={"type": "vendor", "id": "vendor-a"}
        )
        assert (
            response.status_code == 404 and response.json()["error"]["code"] == "PATH_NOT_ALLOWED"
        )
    assert gw.rows("SELECT status FROM vendors WHERE id = 'vendor-a'")[0].status == "ALLOWED"


@pytest.mark.req("FR-18 (staleness rule)", "SEC-09", "B-k")
def test_block_fails_closed_when_snapshot_stale(gw, monkeypatch):
    assert gw.chat("Build Assistant").status_code == 200  # snapshot loaded at t0

    def down(*args, **kwargs):
        raise OperationalError("SELECT", {}, Exception("replica gone"))

    monkeypatch.setattr("keepair.gateway.snapshot.load_snapshot", down)
    gw.clock.advance(timedelta(seconds=29))
    assert gw.chat("Build Assistant").status_code == 200  # old but not yet stale
    assert (
        gw.chat("Build Assistant", "vendor-b/model-1").json()["error"]["code"] == "VENDOR_BLOCKED"
    )
    gw.clock.advance(timedelta(seconds=2))  # 31 s old and cannot refresh
    calls = gw.provider.call_count
    for project, model in (
        ("Build Assistant", "model-1"),
        ("Call Notes", "va-fast"),
        ("Ticket Triage", "model-1"),
    ):
        response = gw.chat(project, model)  # allowed models, monitor and soft budgets: all refused
        assert response.status_code == 403 and response.json()["error"]["code"] == "SNAPSHOT_STALE"
    assert gw.provider.call_count == calls
    assert gw.metrics.value("keepair_failures_total", code="SNAPSHOT_STALE") == 3
    assert (
        len(gw.rows("SELECT 1 FROM alerts WHERE code = 'SNAPSHOT_STALE'")) == 1
    )  # one alert per minute
    monkeypatch.undo()
    assert gw.chat("Build Assistant").status_code == 200  # recovers once it can refresh


@pytest.mark.req("FR-18 (propagation within 5 s)", "B-11")
def test_block_propagates_within_5s_across_instances(settings, engine):
    clock = demo_clock()
    caches = [
        SnapshotCache(lambda t: load_from_database(engine, t, clock), clock) for _ in range(2)
    ]
    with engine.begin() as conn:
        tenant = _tenant(conn)
    assert all(decide_block(c.get(tenant).policy, "model-1").allowed for c in caches)
    with engine.begin() as conn:
        add_block(
            conn, tenant, "vendor", "vendor-a", "tester", "Emergency block for the test.", clock
        )
    clock.advance(timedelta(seconds=5))
    for cache in caches:  # both instances see the block at their next request, 5 s after commit
        decision = decide_block(cache.get(tenant).policy, "model-1")
        assert not decision.allowed and decision.reason.value == "VENDOR_BLOCKED"


@pytest.mark.req("FR-18", "SEC-09")
def test_instance_with_no_snapshot_denies(settings, engine, monkeypatch):
    def down(*args, **kwargs):
        raise OperationalError("SELECT", {}, Exception("no database"))

    monkeypatch.setattr("keepair.gateway.snapshot.load_snapshot", down)
    cache = SnapshotCache(lambda t: load_from_database(engine, t, demo_clock()), demo_clock())
    with pytest.raises(GatewayError) as err:
        cache.get(uuid.uuid4())
    assert err.value.code == "SNAPSHOT_STALE"


@pytest.mark.req("SEC-06 (blocks and hard limits fail closed)", "D-01")
def test_ledger_outage_refuses_every_request(settings, unreachable_engine):
    gw = make_gateway(settings, unreachable_engine)
    for project in ("Build Assistant", "Call Notes"):  # hard and monitor alike in phase 2
        response = gw.chat(project)
        assert (
            response.status_code == 503 and response.json()["error"]["code"] == "LEDGER_UNAVAILABLE"
        )
    assert not gw.provider.called
    assert gw.metrics.value("keepair_failures_total", code="DATABASE_UNREACHABLE") == 2


@pytest.mark.req("SEC-23", "B-n10")
def test_test_secret_refused_in_prod(settings, engine):
    with pytest.raises(DemoDataInProduction, match="demo data"):
        create_gateway_app(
            settings.model_copy(update={"env": "prod"}), engine=engine, run_maintenance=False
        )
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE app_meta SET value = 'false' WHERE key = 'demo'")
    create_gateway_app(
        settings.model_copy(update={"env": "prod"}), engine=engine, run_maintenance=False
    )


@pytest.mark.req("SEC-34", "SEC-19", "Hard rule 8 (tokens never logged)", "SEC-25")
def test_logs_contain_no_prompt_or_key_material(gw, caplog):
    """Run every kind of outcome with canary strings, then scan logs and every table."""
    canary = "CANARY-PROMPT-7f3a9"
    token = demo_token(agent_name("Build Assistant"))
    caplog.set_level(logging.DEBUG)
    gw.chat("Build Assistant", content=canary)  # allowed
    gw.chat("Build Assistant", "vendor-b/model-1", content=canary)  # denied
    gw.chat("Research Agent", content=canary)  # held
    gw.chat("Build Assistant", content=canary, headers={"Authorization": f"Bearer {token}x"})  # 401
    gw.provider.mock(side_effect=httpx.ReadTimeout(f"timeout {canary}"))
    gw.chat("Build Assistant", content=canary)  # unknown usage
    gw.provider.mock(
        return_value=httpx.Response(500, json={"error": {"message": f"echo {canary}"}})
    )
    gw.chat("Build Assistant", content=canary)  # provider error that echoes the prompt
    gw.app.state.maintenance.tick()

    secrets = [canary, token, token[5:25], "mock-provider-key-not-a-secret"]
    logged = caplog.text + gw.client.get("/metrics").text
    tables = [r[0] for r in gw.rows("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")]
    stored = "".join(str(gw.rows(f"SELECT t::text FROM {t} t")) for t in tables)  # noqa: S608
    assert len(tables) >= 18 and "build-assistant-agent" in stored  # the scan really reads the data
    for secret in secrets:
        assert secret not in logged, f"leaked into logs: {secret[:12]}"
        assert secret not in stored, f"leaked into the database: {secret[:12]}"
