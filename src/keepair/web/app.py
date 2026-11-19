"""FastAPI application: server-rendered UI shell (phase 0)."""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError

from keepair import __version__
from keepair.clock import Clock, SystemClock, from_iso
from keepair.config import Settings
from keepair.db import make_engine
from keepair.failures import Alert, AlertStore, FailureReporter
from keepair.health import ComponentHealth, read_health, unknown_health
from keepair.help_registry import HelpRegistry
from keepair.metrics import Metrics
from keepair.schema import app_meta, demo_placeholder
from keepair.web.formatting import format_money, format_ts
from keepair.web.helpui import HelpContext
from keepair.web.pages import PAGES, PAGES_BY_SLUG, Page

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


@dataclass(slots=True)
class PageState:
    health: list[ComponentHealth]
    database_reachable: bool
    demo_clock: str | None = None
    placeholder: str | None = None
    alerts: list[Alert] = field(default_factory=list)


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    clock: Clock | None = None,
    metrics: Metrics | None = None,
) -> FastAPI:
    settings = settings or Settings()
    engine = engine or make_engine(settings)
    clock = clock or SystemClock()
    metrics = metrics or Metrics()
    # Loading validates every entry; a broken registry stops startup.
    registry = HelpRegistry.load(settings.ui_dir / "help" / "field_help.yaml")
    store = AlertStore(engine, clock, metrics)
    reporter = FailureReporter(store, metrics, clock)

    env = Environment(
        loader=FileSystemLoader(settings.ui_dir / "templates"),
        autoescape=select_autoescape(default=True, default_for_string=True),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["ts"] = format_ts

    app = FastAPI(title="KeepAir", version=__version__, docs_url=None, redoc_url=None)
    app.state.metrics = metrics
    app.state.reporter = reporter
    app.state.registry = registry
    app.mount("/static", StaticFiles(directory=settings.ui_dir / "static"), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    def load_state() -> PageState:
        try:
            with engine.connect() as conn:
                state = PageState(health=read_health(conn, clock), database_reachable=True)
                meta = dict(conn.execute(select(app_meta.c.key, app_meta.c.value)).all())
                if "demo_clock" in meta:
                    state.demo_clock = format_ts(from_iso(meta["demo_clock"]))
                row = conn.execute(
                    select(demo_placeholder).where(demo_placeholder.c.id == 1)
                ).one_or_none()
                if row is not None:
                    state.placeholder = format_money(row.amount_micro, row.currency)
        except SQLAlchemyError:
            store.note_db_down()
            reporter.report(
                "DATABASE_UNREACHABLE",
                "The database could not be reached. Component health and demo data "
                "cannot be read, so every component is shown as Unknown.",
            )
            state = PageState(health=unknown_health(), database_reachable=False)
        state.alerts = store.recent()
        return state

    def render(template: str, status_code: int = 200, **context) -> HTMLResponse:
        html = env.get_template(template).render(
            pages=PAGES,
            demo_mode=settings.demo_mode,
            version=__version__,
            help=HelpContext(registry),
            **context,
        )
        return HTMLResponse(html, status_code=status_code)

    def render_page(page: Page) -> HTMLResponse:
        template = "overview.html" if page.slug == "overview" else "page.html"
        return render(template, page=page, state=load_state())

    @app.get("/", response_class=HTMLResponse)
    def overview() -> HTMLResponse:
        return render_page(PAGES_BY_SLUG["overview"])

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        """Liveness of the web process only. It says nothing about the controls."""
        return JSONResponse({"status": "alive", "version": __version__})

    @app.get("/metrics")
    def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    @app.get("/{slug}", response_class=HTMLResponse)
    def page(slug: str) -> HTMLResponse:
        if slug == "overview" or slug not in PAGES_BY_SLUG:
            raise HTTPException(status_code=404)
        return render_page(PAGES_BY_SLUG[slug])

    @app.exception_handler(404)
    async def not_found(request: Request, exc: Exception) -> HTMLResponse:
        return render(
            "error.html",
            status_code=404,
            heading="Page not found",
            detail="There is no page at this address. Use the navigation to continue.",
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> HTMLResponse:
        # Only the exception type is recorded: messages can carry data (SEC-34).
        reporter.report(
            "UNHANDLED_ERROR",
            f"The page {request.url.path} failed to load ({type(exc).__name__}).",
        )
        response = render(
            "error.html",
            status_code=500,
            heading="This page could not be shown",
            detail="The failure was recorded as an alert. It is listed on the Overview page.",
        )
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    return app
