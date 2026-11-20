"""The gateway listener. Separate from the UI (SEC-14): it serves no admin route.

Only allowlisted paths are served (SEC-03). Everything else, with any method,
is 404 PATH_NOT_ALLOWED. The gateway is not a proxy: it never forwards to a
host named by the caller.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import Engine

from keepair import __version__
from keepair.clock import Clock, SystemClock, to_iso
from keepair.config import Settings
from keepair.db import make_engine
from keepair.failures import AlertStore, FailureReporter
from keepair.gateway.adapters import ChatAdapter, MockVault
from keepair.gateway.errors import error_body
from keepair.gateway.ledgerstate import LedgerState
from keepair.gateway.maintenance import Maintenance
from keepair.gateway.parse import MAX_BODY_BYTES
from keepair.gateway.service import Gateway
from keepair.gateway.snapshot import SnapshotCache, load_from_database
from keepair.gateway.spool import Caps, Spool, load_key
from keepair.ids import uuid7
from keepair.metrics import Metrics
from keepair.rng import Rng, system_rng
from keepair.startup import DemoDataInProduction, refuse_test_material

# method, path template, billable (SEC-03). Anything not listed is refused.
ALLOWED_PATHS = (
    ("POST", "/v1/chat/completions", True),
    ("POST", "/v1/vendors/{vendor}/chat/completions", True),
    ("GET", "/healthz", False),
    ("GET", "/metrics", False),
    ("GET", "/status", False),
)
# Demo mode only, never in production: lets the demo console simulate a ledger outage.
DEMO_PATHS = (("POST", "/demo/ledger-fault", False),)


def create_gateway_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    clock: Clock | None = None,
    metrics: Metrics | None = None,
    rng: Rng | None = None,
    http: httpx.Client | None = None,
    run_maintenance: bool = True,
    spool_caps: Caps | None = None,
) -> FastAPI:
    settings = settings or Settings()
    engine = engine or make_engine(settings)
    clock = clock or SystemClock()
    metrics = metrics or Metrics()
    rng = rng or system_rng()
    http = http or httpx.Client(trust_env=False, follow_redirects=False)
    refuse_test_material(engine, settings)

    store = AlertStore(engine, clock, metrics)
    reporter = FailureReporter(store, metrics, clock)
    snapshots = SnapshotCache(lambda tenant_id: load_from_database(engine, tenant_id, clock), clock)
    spool_key, key_is_ephemeral = load_key(settings.spool_key, settings.env, rng)
    spool = Spool(settings.spool_dir, spool_key, clock, rng, spool_caps)
    ledger_state = LedgerState(clock)
    gateway = Gateway(
        engine=engine, clock=clock, rng=rng, metrics=metrics, reporter=reporter,
        snapshots=snapshots, adapter=ChatAdapter(engine, http, MockVault(), spool),
        spool=spool, ledger_state=ledger_state, timeout_s=settings.provider_timeout_s,
    )  # fmt: skip
    maintenance = Maintenance(engine, clock, snapshots, store, reporter, spool, ledger_state, rng)
    demo_routes = settings.demo_mode and settings.env != "prod"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if run_maintenance:
            maintenance.start()
        yield
        maintenance.stop()

    app = FastAPI(title="KeepAir gateway", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)  # fmt: skip
    app.state.gateway = gateway
    app.state.maintenance = maintenance
    app.state.metrics = metrics
    app.state.snapshots = snapshots
    app.state.spool = spool
    app.state.ledger_state = ledger_state

    async def chat(request: Request, vendor: str | None = None) -> JSONResponse:
        declared = request.headers.get("content-length", "0")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            rid = str(uuid7(clock, rng))
            return JSONResponse(error_body("REQUEST_TOO_LARGE", rid), status_code=413)
        raw = await request.body()
        result = await run_in_threadpool(
            gateway.handle_chat,
            authorization=request.headers.get("authorization"),
            headers={k.lower(): v for k, v in request.headers.items()},
            raw_body=raw,
            route_vendor=vendor,
        )
        return JSONResponse(result.body, status_code=result.status, headers=result.headers)

    @app.post("/v1/chat/completions")
    async def chat_default(request: Request):
        return await chat(request)

    @app.post("/v1/vendors/{vendor}/chat/completions")
    async def chat_vendor(vendor: str, request: Request):
        return await chat(request, vendor)

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"status": "alive", "version": __version__})

    @app.get("/metrics")
    def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    @app.get("/status")
    def status() -> JSONResponse:
        """Operational state of this instance. No amounts, names or identifiers."""
        stats = spool.stats()
        down_since = ledger_state.down_since
        return JSONResponse(
            {
                "ledger": {
                    "reachable": not ledger_state.is_down,
                    "down_since": to_iso(down_since) if down_since else None,
                    "simulated_fault": ledger_state.fault_injected,
                },
                "spool": {
                    "waiting": stats.waiting,
                    "waiting_requests": stats.waiting_usage,
                    "bytes": stats.bytes,
                    "oldest_at": to_iso(stats.oldest_at) if stats.oldest_at else None,
                    "unreadable_lines": stats.corrupt_lines,
                    "key_is_ephemeral": key_is_ephemeral,
                    "max_records": stats.caps.max_records,
                    "max_bytes": stats.caps.max_bytes,
                    "max_age_s": stats.caps.max_age_s,
                },
            }
        )

    if demo_routes:

        @app.post("/demo/ledger-fault")
        async def demo_ledger_fault(request: Request) -> JSONResponse:
            """Demo console: make ledger writes fail, or let them work again, on this instance."""
            body = await request.json()
            active = body.get("active") is True
            ledger_state.set_fault(active)
            if not active:
                await run_in_threadpool(maintenance.tick)  # probe and replay at once
            return JSONResponse({"simulated_fault": ledger_state.fault_injected})

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "CONNECT", "TRACE"]

    @app.api_route("/{path:path}", methods=methods, include_in_schema=False)
    def not_allowed(path: str) -> JSONResponse:
        rid = str(uuid7(clock, rng))
        return JSONResponse(error_body("PATH_NOT_ALLOWED", rid), status_code=404)

    @app.exception_handler(404)
    @app.exception_handler(405)
    async def refused(request: Request, exc: Exception) -> JSONResponse:
        rid = str(uuid7(clock, rng))
        return JSONResponse(error_body("PATH_NOT_ALLOWED", rid), status_code=404)

    return app


__all__ = ["DemoDataInProduction", "create_gateway_app", "refuse_test_material"]
