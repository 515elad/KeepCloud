"""FastAPI application: server-rendered UI shell (phase 0)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from sqlalchemy import Engine, func, insert, select, text, update
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from keepair import __version__
from keepair.clock import Clock, SystemClock, from_iso
from keepair.config import Settings
from keepair.db import make_engine
from keepair.failures import Alert, AlertStore, FailureReporter
from keepair.gateway.tokens import generate_token, hash_token
from keepair.health import ComponentHealth, read_health, unknown_health
from keepair.help_registry import HelpRegistry
from keepair.ids import uuid7
from keepair.metrics import Metrics
from keepair.registry import RegistryError, add_block
from keepair.rng import system_rng
from keepair.schema import agents, app_meta, gateway_credentials
from keepair.web import views
from keepair.web.formatting import format_ts
from keepair.web.helpui import HelpContext
from keepair.web.pages import PAGES, PAGES_BY_SLUG, Page

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}


MAX_FORM_BYTES = 4096
# No sign-in exists until phase 5, so UI changes are recorded under this name.
UI_ACTOR = "demo-operator"


def same_origin(request: Request) -> bool:
    """True when a state-changing request comes from one of this site's own pages.

    Browsers state this themselves in Sec-Fetch-Site, which page script cannot set.
    Clients that do not send it must show a matching Origin or Referer.
    """
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site == "same-origin"
    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        return False
    return urlsplit(source).netloc == request.headers.get("host")


@dataclass(slots=True)
class PageState:
    health: list[ComponentHealth]
    database_reachable: bool
    demo_clock: str | None = None
    tenant_id: uuid.UUID | None = None
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
    token_rng = system_rng()

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
        if request.method not in ("GET", "HEAD", "OPTIONS") and not same_origin(request):
            # Forms may only be posted from this site's own pages (TB-9, CSRF).
            response = PlainTextResponse("Cross-site request refused.", status_code=403)
        else:
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
                if "tenant_id" in meta:
                    state.tenant_id = uuid.UUID(meta["tenant_id"])
        except SQLAlchemyError:
            store.note_db_down()
            reporter.report(
                "DATABASE_UNREACHABLE",
                "The database could not be reached. Component health and page data "
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

    def page_context(slug: str) -> tuple[Page, PageState]:
        return PAGES_BY_SLUG[slug], load_state()

    @app.get("/budgets", response_class=HTMLResponse)
    def budgets_page() -> HTMLResponse:
        page, state = page_context("budgets")
        rows = None
        if state.tenant_id:
            with engine.connect() as conn:
                rows = views.load_budget_rows(conn, state.tenant_id)
        return render("budgets.html", page=page, state=state, rows=rows)

    @app.get("/budgets/{budget_id}", response_class=HTMLResponse)
    def budget_detail(budget_id: uuid.UUID) -> HTMLResponse:
        page, state = page_context("budgets")
        row = None
        if state.tenant_id:
            with engine.connect() as conn:
                rows = views.load_budget_rows(conn, state.tenant_id)
            row = next((r for r in rows if r.id == budget_id), None)
        if row is None and state.database_reachable:
            raise HTTPException(status_code=404)
        return render("budget_detail.html", page=page, state=state, row=row)

    def load_registry(state: PageState) -> views.RegistryView | None:
        if not state.tenant_id:
            return None
        with engine.connect() as conn:
            return views.load_registry(conn, state.tenant_id)

    def gateway_context(state: PageState) -> dict:
        activity = credentials = None
        if state.tenant_id:
            with engine.connect() as conn:
                activity = views.load_activity(conn, state.tenant_id, clock.now())
                credentials = views.load_credentials(conn, state.tenant_id)
        return {"registry": load_registry(state), "activity": activity, "credentials": credentials}

    @app.get("/gateway", response_class=HTMLResponse)
    def gateway_page(auto: int = 0) -> HTMLResponse:
        page, state = page_context("gateway")
        return render(
            "gateway.html",
            page=page,
            state=state,
            auto_refresh=bool(auto),
            **gateway_context(state),
        )

    async def read_form(request: Request) -> dict[str, str]:
        body = await request.body()
        if len(body) > MAX_FORM_BYTES:
            raise HTTPException(status_code=413)
        return {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()}

    @app.post("/gateway/credentials", response_class=HTMLResponse)
    async def credential_create(request: Request) -> HTMLResponse:
        """Create a credential. The token is shown in this response only and is never stored."""
        form = await read_form(request)
        page, state = page_context("gateway")
        label = " ".join(form.get("label", "").split())
        try:
            agent_id = uuid.UUID(form.get("agent_id", ""))
        except ValueError:
            raise HTTPException(status_code=404) from None
        if not state.tenant_id or not 1 <= len(label) <= 60:
            raise HTTPException(status_code=422)
        token = generate_token(token_rng)
        with engine.begin() as conn:
            agent = conn.execute(
                select(agents.c.name).where(
                    agents.c.id == agent_id, agents.c.tenant_id == state.tenant_id
                )
            ).scalar_one_or_none()
            if agent is None:
                raise HTTPException(status_code=404)
            conn.execute(
                insert(gateway_credentials).values(
                    id=uuid7(clock, token_rng),
                    tenant_id=state.tenant_id,
                    token_hash=hash_token(token),
                    agent_id=agent_id,
                    label=label,
                    created_at=func.now(),
                    expires_at=func.now() + text("interval '90 days'"),
                )
            )
        response = render(
            "credential_created.html", page=page, state=state, token=token, agent=agent, label=label
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/gateway/credentials/{credential_id}/revoke")
    async def credential_revoke(credential_id: uuid.UUID, request: Request):
        state = load_state()
        if not state.tenant_id:
            raise HTTPException(status_code=404)
        with engine.begin() as conn:
            result = conn.execute(
                update(gateway_credentials)
                .where(
                    gateway_credentials.c.id == credential_id,
                    gateway_credentials.c.tenant_id == state.tenant_id,
                    gateway_credentials.c.revoked_at.is_(None),
                )
                .values(revoked_at=func.now())
            )
        if result.rowcount != 1:
            raise HTTPException(status_code=404)
        return RedirectResponse("/gateway#credentials-title", status_code=303)

    def block_form(
        subject_type: str, subject_id: str, reason: str = "", error: str | None = None
    ) -> HTMLResponse:
        page, state = page_context("gateway")
        registry = load_registry(state)
        if registry is None:
            raise HTTPException(status_code=404)
        if subject_type == "vendor":
            subject = next((v for v in registry.vendors if v.id == subject_id), None)
            affected = [m for m in registry.models if m.vendor_id == subject_id]
        elif subject_type == "model":
            subject = next((m for m in registry.models if m.id == subject_id), None)
            affected = [subject] if subject else []
        else:
            subject, affected = None, []
        if subject is None:
            raise HTTPException(status_code=404)
        return render(
            "block_confirm.html",
            status_code=422 if error else 200,
            page=page,
            state=state,
            subject_type=subject_type,
            subject_id=subject_id,
            affected=affected,
            reason=reason,
            error=error,
        )

    @app.get("/gateway/block", response_class=HTMLResponse)
    def block_confirm(type: str, id: str) -> HTMLResponse:
        return block_form(type, id)

    @app.post("/gateway/block")
    async def block_submit(request: Request):
        form = await read_form(request)
        subject_type, subject_id = form.get("type", ""), form.get("id", "")
        reason = form.get("reason", "")
        state = load_state()
        if not state.tenant_id:
            raise HTTPException(status_code=404)
        try:
            with engine.begin() as conn:
                add_block(conn, state.tenant_id, subject_type, subject_id, UI_ACTOR, reason, clock)
        except RegistryError as exc:
            return block_form(subject_type, subject_id, reason, str(exc))
        return RedirectResponse(f"/gateway#{subject_type}s-title", status_code=303)

    @app.get("/{slug}", response_class=HTMLResponse)
    def page(slug: str) -> HTMLResponse:
        if slug == "overview" or slug not in PAGES_BY_SLUG:
            raise HTTPException(status_code=404)
        return render_page(PAGES_BY_SLUG[slug])

    @app.exception_handler(413)
    async def too_large(request: Request, exc: Exception) -> HTMLResponse:
        return render(
            "error.html",
            status_code=413,
            heading="Form too large",
            detail="The submitted form is larger than allowed.",
        )

    @app.exception_handler(OperationalError)
    async def database_down(request: Request, exc: Exception) -> HTMLResponse:
        store.note_db_down()
        reporter.report(
            "DATABASE_UNREACHABLE",
            f"The database could not be reached while handling {request.url.path}. "
            "Nothing was changed.",
        )
        return render(
            "error.html",
            status_code=503,
            heading="The database cannot be reached",
            detail="Nothing was changed. The failure is recorded as an alert on the Overview page.",
        )

    @app.exception_handler(RequestValidationError)
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
