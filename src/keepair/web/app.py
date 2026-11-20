"""FastAPI application: the server-rendered UI.

Every route is listed in ``keepair.web.access.ROUTE_PERMS`` with the permission
it needs. One middleware checks the session and the role before any handler
runs; a route that is not listed is refused (FR-13, SEC-14).
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from sqlalchemy import Engine, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from starlette.routing import Match, Mount

from keepair import __version__, audit, iam
from keepair.billing import reconcile
from keepair.billing.finalization import SOURCES
from keepair.billing.focus import MAX_BYTES, Quarantine
from keepair.billing.ingest import BatchResult, ingest, reallocate, record_batch
from keepair.clock import Clock, SystemClock, from_iso
from keepair.config import Settings
from keepair.db import make_engine
from keepair.demo.seed import agent_name, demo_token
from keepair.failures import Alert, AlertStore, FailureReporter
from keepair.gateway.tokens import generate_token, hash_token
from keepair.health import ComponentHealth, read_health, record_heartbeat, unknown_health
from keepair.help_registry import HelpRegistry
from keepair.ids import uuid7
from keepair.metrics import Metrics
from keepair.permissions import ROLE_LABEL, Perm, allowed
from keepair.registry import RegistryError, add_block
from keepair.rng import system_rng
from keepair.schema import (
    agents,
    app_meta,
    fail_events,
    gateway_credentials,
    manual_allocations,
    normalized_cost_records,
    projects,
)
from keepair.startup import refuse_test_material
from keepair.web import (
    auth_routes,
    control_routes,
    control_views,
    record_routes,
    spend_views,
    views,
)
from keepair.web.access import PAGE_PERMS, ROUTE_PERMS
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
AUTHZ_DENIED_TOTAL = "keepair_authz_denied_total"
STEP_UP_FAILED_TOTAL = "keepair_step_up_failed_total"
# The signed-in user of the request being handled. Set by the middleware only.
_ACTOR: ContextVar[iam.Actor | None] = ContextVar("keepair_actor", default=None)


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
    fail_open: views.FailOpenState = field(default_factory=views.FailOpenState)
    alerts: list[Alert] = field(default_factory=list)
    kill_switches: list = field(default_factory=list)  # switches that are on (UX-7)


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    clock: Clock | None = None,
    metrics: Metrics | None = None,
    gateway_client: httpx.Client | None = None,
) -> FastAPI:
    settings = settings or Settings()
    engine = engine or make_engine(settings)
    clock = clock or SystemClock()
    metrics = metrics or Metrics()
    refuse_test_material(engine, settings)
    # Loading validates every entry; a broken registry stops startup.
    registry = HelpRegistry.load(settings.ui_dir / "help" / "field_help.yaml")
    store = AlertStore(engine, clock, metrics)
    reporter = FailureReporter(store, metrics, clock)
    token_rng = system_rng()
    box = iam.SecretBox(iam.load_mfa_key(settings.mfa_key, settings.env))
    demo_enabled = settings.demo_mode and settings.env != "prod"
    metrics.describe(AUTHZ_DENIED_TOTAL, "Requests refused because the role does not allow them.")
    metrics.describe(
        STEP_UP_FAILED_TOTAL, "Sensitive actions refused for a bad authenticator code."
    )
    gateway_http = gateway_client or httpx.Client(
        base_url=settings.gateway_url, timeout=1.5, trust_env=False
    )

    def gateway_status() -> dict | None:
        """The gateway's own account of its ledger and spool. None when it does not answer."""
        try:
            response = gateway_http.get("/status")
            return response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None

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

    def route_perm(request: Request) -> Perm | str | None:
        """The permission of the route this request will reach.

        None: no route matches, so the request ends as a 404. "missing": a route
        matches but names no permission, which is refused.
        """
        for route in app.router.routes:
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                if isinstance(route, Mount):
                    return Perm.PUBLIC  # static files
                return ROUTE_PERMS.get((request.method, route.path), "missing")
        return None

    def session_actor(token: str | None) -> iam.Actor | None:
        with engine.begin() as conn:
            return iam.authenticate(conn, clock, token)

    def outage_page() -> HTMLResponse:
        """The database cannot be reached, so nobody can be authenticated. This page
        shows the outage and nothing else: no page data, only this failure's alert."""
        store.note_db_down()
        reporter.report(
            "DATABASE_UNREACHABLE",
            "The database could not be reached. Nobody can be signed in and no page data "
            "can be read, so every component is shown as Unknown.",
        )
        state = PageState(health=unknown_health(), database_reachable=False)
        state.fail_open = views.fail_open_from_status(gateway_status())
        state.alerts = [a for a in store.recent() if a.code == "DATABASE_UNREACHABLE"]
        return render("outage.html", status_code=503, state=state)

    @app.middleware("http")
    async def security(request: Request, call_next):
        response, reset = None, None
        if request.method not in ("GET", "HEAD", "OPTIONS") and not same_origin(request):
            # Forms may only be posted from this site's own pages (TB-9, CSRF).
            response = PlainTextResponse("Cross-site request refused.", status_code=403)
        else:
            perm = route_perm(request)
            if perm == "missing":
                response = render(
                    "error.html", status_code=403, heading="Not allowed",
                    detail="This address has no permission entry, so it is refused.",
                )  # fmt: skip
            elif perm is not None and perm is not Perm.PUBLIC:
                try:
                    actor = await run_in_threadpool(session_actor, request.cookies.get(iam.COOKIE))
                except SQLAlchemyError:
                    response = await run_in_threadpool(outage_page)
                else:
                    if actor is None:
                        response = RedirectResponse("/login", status_code=303)
                    elif not allowed(actor.role, perm):
                        metrics.inc(AUTHZ_DENIED_TOTAL, permission=perm.value)
                        reset = _ACTOR.set(actor)
                        response = render(
                            "error.html", status_code=403, heading="Your role does not allow this",
                            detail=f"You are signed in as {actor.username} "
                            f"({ROLE_LABEL[actor.role]}). This page or action needs another role.",
                        )  # fmt: skip
                    else:
                        reset = _ACTOR.set(actor)
        try:
            if response is None:
                response = await call_next(request)
        finally:
            if reset is not None:
                _ACTOR.reset(reset)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    def current_actor() -> iam.Actor:
        actor = _ACTOR.get()
        if actor is None:  # a handler ran without the middleware: refuse
            raise HTTPException(status_code=403)
        return actor

    def load_state() -> PageState:
        fail_open = views.fail_open_from_status(gateway_status())
        try:
            with engine.connect() as conn:
                state = PageState(health=read_health(conn, clock), database_reachable=True)
                meta = dict(conn.execute(select(app_meta.c.key, app_meta.c.value)).all())
                if "demo_clock" in meta:
                    state.demo_clock = format_ts(from_iso(meta["demo_clock"]))
                if "tenant_id" in meta:
                    state.tenant_id = uuid.UUID(meta["tenant_id"])
                    views.add_unacknowledged(conn, state.tenant_id, fail_open)
                    state.kill_switches = control_views.active_switches(conn, state.tenant_id)
        except SQLAlchemyError:
            store.note_db_down()
            reporter.report(
                "DATABASE_UNREACHABLE",
                "The database could not be reached. Component health and page data "
                "cannot be read, so every component is shown as Unknown.",
            )
            state = PageState(health=unknown_health(), database_reachable=False)
        state.alerts = store.recent()
        state.fail_open = fail_open  # known even when the UI's own database read failed
        return state

    def render(template: str, status_code: int = 200, **context) -> HTMLResponse:
        actor = _ACTOR.get()
        demo_code = None
        if actor is not None and demo_enabled:
            try:
                with engine.connect() as conn:
                    demo_code = iam.demo_code(conn, clock, box, actor.id)
            except SQLAlchemyError:
                demo_code = None
        html = env.get_template(template).render(
            # Only the pages this role may open are in the navigation.
            pages=[p for p in PAGES if actor and allowed(actor.role, PAGE_PERMS[p.slug])],
            demo_mode=settings.demo_mode,
            version=__version__,
            help=HelpContext(registry),
            user=actor,
            role_label=ROLE_LABEL[actor.role] if actor else None,
            demo_code=demo_code,
            **context,
        )
        return HTMLResponse(html, status_code=status_code)

    def render_page(page: Page) -> HTMLResponse:
        state = load_state()
        if page.slug != "overview":
            return render("page.html", page=page, state=state)
        try:
            summary = spend_context(state, None)
            with engine.connect() as conn:
                summary["unowned"] = (
                    control_views.unowned(conn, state.tenant_id, summary.get("period"))
                    if state.tenant_id
                    else None
                )
        except SQLAlchemyError:
            # The page's own notice already says the database is down.
            summary = {"period": None, "unowned": None}
        return render("overview.html", page=page, state=state, **summary)

    def record(conn, state: PageState, action: str, subject_type: str, subject_id: str,
               **details) -> None:  # fmt: skip
        """Append to the audit record, in the transaction of the action itself (SEC-31)."""
        actor = current_actor()
        audit.record(
            conn, clock, tenant_id=state.tenant_id, actor=actor.username, actor_id=actor.id,
            action=action, subject_type=subject_type, subject_id=subject_id, **details,
        )  # fmt: skip

    def step_up_ok(form: dict[str, str]) -> bool:
        """SEC-13: a fresh authenticator code, given in the same form. Accepted once."""
        with engine.begin() as conn:
            return iam.step_up(conn, clock, box, current_actor(), form.get("totp", ""))

    def step_up_refused() -> HTMLResponse:
        metrics.inc(STEP_UP_FAILED_TOTAL)
        with engine.connect() as conn:
            locked = iam.is_locked(conn, clock, current_actor().username)
        if locked:
            reporter.report(
                "ACCOUNT_LOCKED",
                "An account was locked for 15 minutes after 5 failed authenticator codes. "
                "See the audit record for the account.",
                dedupe_s=60,
            )
        return render(
            "error.html", status_code=403, heading="Authenticator code not accepted",
            detail="This action needs a fresh code from your authenticator. The code was missing, "
            "wrong, or already used. Nothing was changed. Go back and enter the next code.",
        )  # fmt: skip

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
                rows = views.load_budget_rows(
                    conn, state.tenant_id, reconcile.uncontrolled_projects(conn, state.tenant_id)
                )
        return render("budgets.html", page=page, state=state, rows=rows)

    @app.get("/budgets/{budget_id}", response_class=HTMLResponse)
    def budget_detail(budget_id: uuid.UUID) -> HTMLResponse:
        page, state = page_context("budgets")
        row = None
        if state.tenant_id:
            with engine.connect() as conn:
                rows = views.load_budget_rows(
                    conn, state.tenant_id, reconcile.uncontrolled_projects(conn, state.tenant_id)
                )
            row = next((r for r in rows if r.id == budget_id), None)
        if row is None and state.database_reachable:
            raise HTTPException(status_code=404)
        return render("budget_detail.html", page=page, state=state, row=row,
                      **control_routes.budget_forms(ctx, state, row))  # fmt: skip

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
        lifts = {}
        if state.tenant_id:
            with engine.connect() as conn:
                lifts = control_views.pending_lifts(conn, state.tenant_id)
        return {
            "registry": load_registry(state), "activity": activity, "credentials": credentials,
            "lifts": lifts,
        }  # fmt: skip

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
            record(conn, state, "credential.created", "agent", agent, after={"label": label})
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
            record(conn, state, "credential.revoked", "credential", str(credential_id))
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
        if not step_up_ok(form):
            return step_up_refused()
        actor = current_actor()
        try:
            with engine.begin() as conn:
                add_block(
                    conn, state.tenant_id, subject_type, subject_id, actor.username, reason, clock
                )
                record(
                    conn, state, "registry.blocked", subject_type, subject_id,
                    before={"status": "ALLOWED"}, after={"status": "BLOCKED"},
                    reason=" ".join(reason.split()),
                )  # fmt: skip
        except RegistryError as exc:
            return block_form(subject_type, subject_id, reason, str(exc))
        return RedirectResponse(f"/gateway#{subject_type}s-title", status_code=303)

    # --- Spend data: explorer, allocation, upload, reconciliation (phase 4) ---------

    def spend_context(state: PageState, period_text: str | None) -> dict:
        if not state.tenant_id:
            return {"period": None}
        with engine.connect() as conn:
            found, default = spend_views.periods(conn, state.tenant_id)
            period = spend_views.parse_period(period_text, found, default)
            context = {"period": period, "periods": found}
            if period is None:
                return context
            totals = spend_views.state_totals(conn, state.tenant_id, period)
            charts, scale_top = spend_views.explorer(conn, state.tenant_id, period)
            context.update(
                totals=totals,
                charts=charts,
                scale_top=scale_top,
                allocations=spend_views.allocation_tables(conn, state.tenant_id, period),
                queue=spend_views.queue(conn, state.tenant_id, period),
                batches=spend_views.batches(conn, state.tenant_id),
                projects=spend_views.project_choices(conn, state.tenant_id),
                recon=spend_views.reconciliation(conn, state.tenant_id, period, totals),
                sources=list(SOURCES.values()),
            )
        return context

    @app.get("/spend", response_class=HTMLResponse)
    def spend_page(period: str | None = None, status_code: int = 200) -> HTMLResponse:
        page, state = page_context("spend")
        return render("spend.html", page=page, state=state, upload_result=None,
                      **spend_context(state, period))  # fmt: skip

    @app.get("/reconciliation", response_class=HTMLResponse)
    def reconciliation_page(period: str | None = None) -> HTMLResponse:
        page, state = page_context("reconciliation")
        return render("reconciliation.html", page=page, state=state, **spend_context(state, period))

    @app.post("/spend/upload", response_class=HTMLResponse)
    async def spend_upload(request: Request):
        """Load a billing file. It is untrusted: limits first, then strict parsing (SEC-28)."""
        declared = request.headers.get("content-length", "")
        if not declared.isdigit() or int(declared) > MAX_BYTES + 64 * 1024:
            raise HTTPException(status_code=413)
        form = await request.form(max_files=1, max_fields=4)
        upload, source = form.get("file"), str(form.get("source", ""))
        if not hasattr(upload, "read"):
            raise HTTPException(status_code=422)
        data = await upload.read(MAX_BYTES + 1)
        file_name = (upload.filename or "unnamed")[:200]
        page, state = page_context("spend")
        if not state.tenant_id:
            raise HTTPException(status_code=404)
        try:
            with engine.begin() as conn:
                result = ingest(
                    conn, tenant_id=state.tenant_id, source=source, file_name=file_name,
                    data=data, actor=current_actor().username, clock=clock, rng=token_rng,
                )  # fmt: skip
                record_heartbeat(conn, "data_sources", clock)
                record(
                    conn, state, "billing.file_loaded", "ingestion_batch", str(result.batch_id),
                    after={"source": source, "file": file_name, "rows": result.rows_total,
                           "new": result.rows_new, "revised": result.rows_revised},
                )  # fmt: skip
                findings = reconcile.uncontrolled_projects(conn, state.tenant_id)
        except Quarantine as bad:
            failed = BatchResult(uuid7(clock, token_rng), "QUARANTINED", reasons=bad.reasons)
            with engine.begin() as conn:
                record_batch(
                    conn, state.tenant_id, source if source in SOURCES else "unknown",
                    file_name, data, failed, current_actor().username, clock,
                )  # fmt: skip
                record(
                    conn, state, "billing.file_refused", "ingestion_batch", str(failed.batch_id),
                    after={"source": source[:40], "file": file_name,
                           "reasons": len(bad.reasons)},
                )  # fmt: skip
            reporter.report(
                "INGEST_QUARANTINED",
                f"A billing file was refused and nothing from it was loaded ({len(bad.reasons)} "
                "reasons). See the ingestion history on the Spend page.",
            )
            page, state = page_context("spend")
            return render("spend.html", status_code=422, page=page, state=state,
                          upload_result=failed, **spend_context(state, None))  # fmt: skip
        if findings and result.rows_new + result.rows_revised:
            reporter.report(
                "UNCONTROLLED_SPEND",
                f"The provider reports more usage than the gateway recorded for {len(findings)} "
                "project(s). See the Reconciliation page.",
                dedupe_s=60,
            )
        return RedirectResponse("/spend#history-title", status_code=303)

    @app.post("/spend/assign")
    async def spend_assign(request: Request):
        """Assign one billing record to a project by hand (FR-03, confidence MANUAL)."""
        form = await read_form(request)
        state = load_state()
        try:
            record_id, project_id = (
                uuid.UUID(form.get("record_id", "")),
                uuid.UUID(form.get("project_id", "")),
            )
        except ValueError:
            raise HTTPException(status_code=404) from None
        reason = " ".join(form.get("reason", "").split())
        if not state.tenant_id or not 10 <= len(reason) <= 300:
            raise HTTPException(status_code=422)
        n = normalized_cost_records
        actor_name = current_actor().username
        with engine.begin() as conn:
            found = conn.execute(
                select(n.c.source, n.c.record_key).where(
                    n.c.id == record_id, n.c.tenant_id == state.tenant_id, n.c.is_current
                )
            ).one_or_none()
            known = conn.execute(
                select(projects.c.id, projects.c.name).where(
                    projects.c.id == project_id, projects.c.tenant_id == state.tenant_id
                )
            ).one_or_none()
            if found is None or known is None:
                raise HTTPException(status_code=404)
            stmt = pg_insert(manual_allocations).values(
                tenant_id=state.tenant_id, source=found.source, record_key=found.record_key,
                project_id=project_id, actor=actor_name, reason=reason, assigned_at=clock.now(),
            )  # fmt: skip
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["tenant_id", "source", "record_key"],
                    set_={"project_id": project_id, "actor": actor_name, "reason": reason,
                          "assigned_at": clock.now()},
                )
            )  # fmt: skip
            reallocate(conn, state.tenant_id, [record_id], clock)
            record(
                conn, state, "billing.record_assigned", "billing_record",
                f"{found.source}:{found.record_key}", after={"project": known.name},
                reason=reason,
            )  # fmt: skip
        return RedirectResponse("/spend#queue-title", status_code=303)

    # --- Fail-open: status for the banner, report, acknowledgement (UX-7) -----------

    @app.get("/api/fail-open")
    def fail_open_status() -> JSONResponse:
        return JSONResponse({"signature": load_state().fail_open.signature})

    @app.get("/gateway/fail-open", response_class=HTMLResponse)
    def fail_open_report() -> HTMLResponse:
        page, state = page_context("gateway")
        report = None
        if state.tenant_id:
            with engine.connect() as conn:
                report = views.load_fail_open_report(conn, state.tenant_id)
        return render("fail_open.html", page=page, state=state, report=report)

    @app.post("/gateway/fail-open/acknowledge")
    async def fail_open_acknowledge(request: Request):
        state = load_state()
        if not state.tenant_id:
            raise HTTPException(status_code=404)
        if state.fail_open.active or state.fail_open.waiting:
            # Not over yet: there is nothing complete to acknowledge.
            raise HTTPException(status_code=409)
        with engine.begin() as conn:
            done = conn.execute(
                update(fail_events)
                .where(
                    fail_events.c.tenant_id == state.tenant_id,
                    fail_events.c.acknowledged_at.is_(None),
                )
                .values(acknowledged_at=func.now(), acknowledged_by=current_actor().username)
            )
            record(conn, state, "fail_open.acknowledged", "fail_open", "events",
                   after={"events": done.rowcount})  # fmt: skip
        return RedirectResponse("/gateway/fail-open", status_code=303)

    # --- Demo console (demo mode only) ---------------------------------------------

    def admin_page(console_results=None, console_error=None, status_code=200,
                   **extra) -> HTMLResponse:  # fmt: skip
        page, state = page_context("admin")
        return render(
            "admin.html",
            status_code=status_code,
            page=page,
            state=state,
            demo_console=demo_enabled and allowed(current_actor().role, Perm.DEMO_CONSOLE),
            console_results=console_results,
            console_error=console_error,
            **{**control_routes.admin_context(ctx, state), **extra},
        )

    @app.get("/admin", response_class=HTMLResponse)
    def admin() -> HTMLResponse:
        return admin_page()

    def require_demo() -> None:
        if not demo_enabled:
            raise HTTPException(status_code=404)

    @app.post("/admin/demo/ledger", response_class=HTMLResponse)
    async def demo_ledger(request: Request):
        require_demo()
        form = await read_form(request)
        action = form.get("action")
        if action not in ("stop", "restore"):
            raise HTTPException(status_code=422)
        try:
            answer = gateway_http.post("/demo/ledger-fault", json={"active": action == "stop"})
            answer.raise_for_status()
        except httpx.HTTPError:
            return admin_page(
                console_error="The gateway did not answer. Is it running?", status_code=502
            )
        with engine.begin() as conn:
            record(conn, load_state(), "demo.ledger_fault", "gateway", "ledger",
                   after={"simulated_outage": action == "stop"})  # fmt: skip
        return RedirectResponse("/admin#console-title", status_code=303)

    @app.post("/admin/demo/requests", response_class=HTMLResponse)
    async def demo_requests(request: Request):
        require_demo()
        state = load_state()
        kinds: dict[str, str] = {}
        if state.tenant_id:
            with engine.connect() as conn:
                kinds = views.limit_kinds(conn, state.tenant_id)
        results = []
        try:
            for project, model in views.CONSOLE_REQUESTS:
                agent = agent_name(project)
                answer = gateway_http.post(
                    "/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {demo_token(agent)}",
                        "Idempotency-Key": f"console-{uuid7(clock, token_rng)}",
                    },
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "Demo console request."}],
                        "max_tokens": 64,
                    },
                )
                body = answer.json()
                words, code, sent = views.describe_outcome(
                    answer.status_code,
                    answer.headers.get("x-keepair-decision"),
                    body.get("error", {}).get("code") if isinstance(body, dict) else None,
                )
                results.append(
                    views.ConsoleResult(
                        agent, project, kinds.get(project, "Unknown"), model, words, code, sent
                    )
                )
        except (httpx.HTTPError, ValueError):
            return admin_page(
                console_error="The gateway did not answer. Is it running?", status_code=502
            )
        return admin_page(console_results=results)

    ctx = SimpleNamespace(
        app=app, settings=settings, engine=engine, clock=clock, rng=token_rng, box=box,
        metrics=metrics, reporter=reporter, render=render, page_context=page_context,
        load_state=load_state, read_form=read_form, actor=current_actor, record=record,
        step_up_ok=step_up_ok, step_up_refused=step_up_refused, demo_enabled=demo_enabled,
        admin_page=admin_page, spend_context=spend_context, actor_or_none=_ACTOR.get,
    )  # fmt: skip
    auth_routes.register(ctx)
    control_routes.register(ctx)
    record_routes.register(ctx)

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
