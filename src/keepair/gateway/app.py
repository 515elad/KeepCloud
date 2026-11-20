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
from sqlalchemy import Engine, select

from keepair import __version__
from keepair.clock import Clock, SystemClock
from keepair.config import Settings
from keepair.db import make_engine
from keepair.failures import AlertStore, FailureReporter
from keepair.gateway.adapters import ChatAdapter, MockVault
from keepair.gateway.errors import error_body
from keepair.gateway.maintenance import Maintenance
from keepair.gateway.parse import MAX_BODY_BYTES
from keepair.gateway.service import Gateway
from keepair.gateway.snapshot import SnapshotCache, load_from_database
from keepair.ids import uuid7
from keepair.metrics import Metrics
from keepair.rng import Rng, system_rng
from keepair.schema import app_meta

# method, path template, billable (SEC-03). Anything not listed is refused.
ALLOWED_PATHS = (
    ("POST", "/v1/chat/completions", True),
    ("POST", "/v1/vendors/{vendor}/chat/completions", True),
    ("GET", "/healthz", False),
    ("GET", "/metrics", False),
)


class DemoDataInProduction(RuntimeError):
    """Demo data found in a production database (SEC-23)."""


def refuse_test_material(engine: Engine, settings: Settings) -> None:
    if settings.env != "prod":
        return
    with engine.connect() as conn:
        demo = conn.execute(select(app_meta.c.value).where(app_meta.c.key == "demo")).scalar()
    if demo == "true":
        raise DemoDataInProduction(
            "This database holds demo data and demo credentials. Refusing to start in production."
        )


def create_gateway_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    clock: Clock | None = None,
    metrics: Metrics | None = None,
    rng: Rng | None = None,
    http: httpx.Client | None = None,
    run_maintenance: bool = True,
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
    gateway = Gateway(
        engine=engine, clock=clock, rng=rng, metrics=metrics, reporter=reporter,
        snapshots=snapshots, adapter=ChatAdapter(engine, http, MockVault()),
        timeout_s=settings.provider_timeout_s,
    )  # fmt: skip
    maintenance = Maintenance(engine, clock, snapshots, store, reporter)

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
