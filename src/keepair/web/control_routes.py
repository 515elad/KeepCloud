"""Routes for owners, approvals, two-person actions, users and the kill switch (phase 5).

Every handler here that changes policy first checks a fresh authenticator code
(``ctx.step_up_ok``). The permission for each route is in ``keepair.web.access``.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError

from keepair import approvals, iam, killswitch
from keepair.permissions import ROLE_LABEL, Perm, Role, allowed
from keepair.registry import RegistryError
from keepair.web import control_views, views


def budget_forms(ctx, state, row) -> dict:
    """What the budget page needs for its owner and policy forms."""
    actor = ctx.actor()
    can_manage = allowed(actor.role, Perm.MANAGE_BUDGETS)
    context = {"can_manage": can_manage, "owner_choices": [], "policy_choices": [],
               "budget_pending": []}  # fmt: skip
    if row is None or not state.tenant_id:
        return context
    with ctx.engine.connect() as conn:
        context["budget_pending"] = [
            p for p in control_views.pending_rows(conn, ctx.clock, state.tenant_id, actor)
            if p.kind in ("OWNER_CHANGE", "POLICY_CHANGE") and row.name in p.summary
        ]  # fmt: skip
        if can_manage:
            context["owner_choices"] = control_views.owner_choices(conn, state.tenant_id)
            context["policy_choices"] = control_views.policy_choices(row.policy)
    return context


def admin_context(ctx, state) -> dict:
    actor = ctx.actor()
    if not state.tenant_id:
        return {"users": None, "switches": [], "past_switches": [], "scopes": None,
                "can_manage_users": False, "can_switch": False, "roles": [],
                "user_error": None}  # fmt: skip
    with ctx.engine.connect() as conn:
        return {
            "users": control_views.user_rows(conn, ctx.clock, state.tenant_id, actor),
            "switches": state.kill_switches,
            "past_switches": control_views.past_switches(conn, state.tenant_id),
            "scopes": control_views.scope_choices(conn, state.tenant_id),
            "can_manage_users": allowed(actor.role, Perm.MANAGE_USERS),
            "can_switch": allowed(actor.role, Perm.KILL_SWITCH),
            "roles": [(r.value, ROLE_LABEL[r]) for r in Role],
            "user_error": None,
        }


def register(ctx) -> None:
    app, engine, clock = ctx.app, ctx.engine, ctx.clock

    def tenant(state) -> uuid.UUID:
        if not state.tenant_id:
            raise HTTPException(status_code=404)
        return state.tenant_id

    def refused(heading: str, detail: str, status: int = 409) -> HTMLResponse:
        return ctx.render("error.html", status_code=status, heading=heading, detail=detail)

    def as_uuid(value: str) -> uuid.UUID:
        try:
            return uuid.UUID(value)
        except ValueError:
            raise HTTPException(status_code=404) from None

    # --- Approvals page (FR-11, UX-11) ----------------------------------------------

    def approvals_page(notice: str | None = None, status_code: int = 200) -> HTMLResponse:
        page, state = ctx.page_context("approvals")
        actor = ctx.actor()
        held = pending = decisions = None
        if state.tenant_id:
            with engine.begin() as conn:
                approvals.expire_due(conn, clock, state.tenant_id)
                held = control_views.held_rows(conn, state.tenant_id, actor)
                pending = control_views.pending_rows(conn, clock, state.tenant_id, actor)
                decisions = control_views.recent_decisions(conn, state.tenant_id)
        return ctx.render(
            "approvals.html", status_code=status_code, page=page, state=state, held=held,
            waiting=pending, decisions=decisions, notice=notice,
            window_min=approvals.RESUBMIT_WINDOW_S // 60,
        )  # fmt: skip

    @app.get("/approvals", response_class=HTMLResponse)
    def approvals_get() -> HTMLResponse:
        return approvals_page()

    @app.post("/approvals/held/{reservation_id}")
    async def held_decide(reservation_id: uuid.UUID, request: Request):
        form = await ctx.read_form(request)
        state = ctx.load_state()
        decision = form.get("decision")
        if decision not in ("approve", "reject"):
            raise HTTPException(status_code=422)
        try:
            with engine.begin() as conn:
                approvals.decide_held(
                    conn, clock, ctx.rng, tenant_id=tenant(state), reservation_id=reservation_id,
                    actor=ctx.actor(), approve=decision == "approve", note=form.get("note", ""),
                )  # fmt: skip
        except approvals.ApprovalError as exc:
            return approvals_page(str(exc), 403 if exc.code == "SELF_APPROVAL" else 409)
        return RedirectResponse("/approvals#held-title", status_code=303)

    @app.post("/approvals/{approval_id}/decide")
    async def two_person_decide(approval_id: uuid.UUID, request: Request):
        form = await ctx.read_form(request)
        state = ctx.load_state()
        decision = form.get("decision")
        if decision not in ("approve", "reject"):
            raise HTTPException(status_code=422)
        actor = ctx.actor()
        # The self-approval rule is checked before the code is spent, and again in decide().
        with engine.connect() as conn:
            mine = any(
                p.id == approval_id and p.mine
                for p in control_views.pending_rows(conn, clock, tenant(state), actor)
            )
        if mine:
            return approvals_page(
                "You made this request. A different administrator must decide it.", 403
            )
        if not ctx.step_up_ok(form):
            return ctx.step_up_refused()
        try:
            with engine.begin() as conn:
                approvals.decide(
                    conn, clock, tenant_id=tenant(state), approval_id=approval_id, actor=actor,
                    approve=decision == "approve",
                )  # fmt: skip
        except approvals.ApprovalError as exc:
            return approvals_page(str(exc), 403 if exc.code == "SELF_APPROVAL" else 409)
        return RedirectResponse("/approvals#decisions-title", status_code=303)

    @app.post("/approvals/{approval_id}/cancel")
    async def two_person_cancel(approval_id: uuid.UUID, request: Request):
        state = ctx.load_state()
        try:
            with engine.begin() as conn:
                approvals.cancel(
                    conn, clock, tenant_id=tenant(state), approval_id=approval_id,
                    actor=ctx.actor(),
                )  # fmt: skip
        except approvals.ApprovalError as exc:
            return approvals_page(str(exc), 409)
        return RedirectResponse("/approvals#pending-title", status_code=303)

    # --- Lifting a block: two people (FR-18, SEC-07, SEC-15) ---------------------------

    def lift_form(subject_type: str, subject_id: str, reason: str = "", error: str | None = None):
        page, state = ctx.page_context("gateway")
        with engine.connect() as conn:
            registry = views.load_registry(conn, tenant(state))
            eligible = approvals.eligible_approvers(conn, state.tenant_id, ctx.actor().id)
        if subject_type == "vendor":
            subject = next((v for v in registry.vendors if v.id == subject_id), None)
            blocked = subject is not None and subject.status.value == "BLOCKED"
            vendor_blocked = None
        elif subject_type == "model":
            subject = next((m for m in registry.models if m.id == subject_id), None)
            blocked = subject is not None and subject.own_status.value == "BLOCKED"
            vendor_blocked = (
                subject.vendor_id
                if subject is not None and subject.effective.value == "BLOCKED_BY_VENDOR"
                else None
            )
        else:
            subject, blocked, vendor_blocked = None, False, None
        if subject is None or not blocked:
            raise HTTPException(status_code=404)
        return ctx.render(
            "lift_request.html", status_code=422 if error else 200, page=page, state=state,
            subject_type=subject_type, subject_id=subject_id, reason=reason, error=error,
            eligible=eligible, vendor_blocked=vendor_blocked,
        )  # fmt: skip

    @app.get("/gateway/lift", response_class=HTMLResponse)
    def lift_get(type: str, id: str) -> HTMLResponse:
        return lift_form(type, id)

    @app.post("/gateway/lift")
    async def lift_post(request: Request):
        form = await ctx.read_form(request)
        subject_type, subject_id = form.get("type", ""), form.get("id", "")
        reason = form.get("reason", "")
        state = ctx.load_state()
        if not ctx.step_up_ok(form):
            return ctx.step_up_refused()
        try:
            with engine.begin() as conn:
                approvals.request_block_lift(
                    conn, clock, ctx.rng, tenant_id=tenant(state), subject_type=subject_type,
                    subject_id=subject_id, actor=ctx.actor(), reason=reason,
                )  # fmt: skip
        except (approvals.ApprovalError, RegistryError) as exc:
            return lift_form(subject_type, subject_id, reason, str(exc))
        return RedirectResponse("/approvals#pending-title", status_code=303)

    # --- Budget owner and policy (FR-17, FR-04) -------------------------------------

    def budget_name(state, budget_id: uuid.UUID) -> str:
        with engine.connect() as conn:
            rows = views.load_budget_rows(conn, tenant(state))
        row = next((r for r in rows if r.id == budget_id), None)
        if row is None:
            raise HTTPException(status_code=404)
        return row.name

    async def budget_change(budget_id: uuid.UUID, request: Request, change):
        form = await ctx.read_form(request)
        state = ctx.load_state()
        name = budget_name(state, budget_id)
        if not ctx.step_up_ok(form):
            return ctx.step_up_refused()
        try:
            with engine.begin() as conn:
                waiting = change(conn, state.tenant_id, name, form)
        except (approvals.ApprovalError, RegistryError) as exc:
            return refused("The change was refused", f"{exc} Nothing was changed.")
        except IntegrityError:
            return refused(
                "The change was refused",
                "A hard limit needs an active owner (FR-17). Nothing was changed.",
            )
        if waiting is not None:
            return RedirectResponse("/approvals#pending-title", status_code=303)
        return RedirectResponse(f"/budgets/{budget_id}#owner-title", status_code=303)

    @app.post("/budgets/{budget_id}/owner")
    async def budget_owner(budget_id: uuid.UUID, request: Request):
        def change(conn, tenant_id, name, form):
            chosen = form.get("user_id", "")
            return approvals.change_owner(
                conn, clock, ctx.rng, tenant_id=tenant_id, budget_id=budget_id, budget_name=name,
                user_id=as_uuid(chosen) if chosen else None, actor=ctx.actor(),
                reason=form.get("reason", ""),
            )  # fmt: skip

        return await budget_change(budget_id, request, change)

    @app.post("/budgets/{budget_id}/policy")
    async def budget_policy(budget_id: uuid.UUID, request: Request):
        def change(conn, tenant_id, name, form):
            return approvals.change_policy(
                conn, clock, ctx.rng, tenant_id=tenant_id, budget_id=budget_id, budget_name=name,
                policy=form.get("policy", ""), actor=ctx.actor(), reason=form.get("reason", ""),
            )  # fmt: skip

        return await budget_change(budget_id, request, change)

    # --- Users (FR-13) ----------------------------------------------------------------

    @app.post("/admin/users", response_class=HTMLResponse)
    async def user_create(request: Request):
        form = await ctx.read_form(request)
        state = ctx.load_state()
        if not ctx.step_up_ok(form):
            return ctx.step_up_refused()
        try:
            with engine.begin() as conn:
                created = iam.create_user(
                    conn, clock, ctx.rng, ctx.box, tenant_id=tenant(state),
                    username=form.get("username", ""), display_name=form.get("display_name", ""),
                    role=form.get("role", ""), actor=ctx.actor(),
                )  # fmt: skip
        except iam.IamError as exc:
            return ctx.admin_page(user_error=str(exc), status_code=422)
        return issued(created, "created")

    def issued(created: iam.NewCredentials, what: str) -> HTMLResponse:
        page, state = ctx.page_context("admin")
        response = ctx.render(
            "user_created.html", page=page, state=state, created=created, what=what
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/admin/users/{user_id}/status")
    async def user_status(user_id: uuid.UUID, request: Request):
        form = await ctx.read_form(request)
        state = ctx.load_state()
        if not ctx.step_up_ok(form):
            return ctx.step_up_refused()
        try:
            with engine.begin() as conn:
                iam.set_status(
                    conn, clock, tenant_id=tenant(state), user_id=user_id,
                    status=form.get("status", ""), actor=ctx.actor(),
                )  # fmt: skip
        except iam.IamError as exc:
            return ctx.admin_page(user_error=str(exc), status_code=409)
        return RedirectResponse("/admin#users-title", status_code=303)

    @app.post("/admin/users/{user_id}/reset", response_class=HTMLResponse)
    async def user_reset(user_id: uuid.UUID, request: Request):
        form = await ctx.read_form(request)
        state = ctx.load_state()
        if not ctx.step_up_ok(form):
            return ctx.step_up_refused()
        try:
            with engine.begin() as conn:
                created = iam.reset_credentials(
                    conn, clock, ctx.rng, ctx.box, tenant_id=tenant(state), user_id=user_id,
                    actor=ctx.actor(),
                )  # fmt: skip
        except iam.IamError as exc:
            return ctx.admin_page(user_error=str(exc), status_code=409)
        return issued(created, "reset")

    # --- Kill switch (FR-22, UX-7) ----------------------------------------------------

    def parse_scope(value: str) -> tuple[str, str]:
        scope_type, _, scope_id = value.partition(":")
        return scope_type.upper(), scope_id

    def kill_preview(scope: str, reason: str = "", error: str | None = None) -> HTMLResponse:
        page, state = ctx.page_context("admin")
        scope_type, scope_id = parse_scope(scope)
        try:
            with engine.connect() as conn:
                impact = killswitch.preview(conn, tenant(state), scope_type, scope_id, clock.now())
        except killswitch.KillSwitchError:
            raise HTTPException(status_code=404) from None
        return ctx.render(
            "kill_confirm.html", status_code=422 if error else 200, page=page, state=state,
            impact=impact, scope=scope, reason=reason, error=error,
        )  # fmt: skip

    @app.get("/admin/kill-switch", response_class=HTMLResponse)
    def kill_get(scope: str) -> HTMLResponse:
        return kill_preview(scope)

    @app.post("/admin/kill-switch")
    async def kill_post(request: Request):
        form = await ctx.read_form(request)
        scope, reason = form.get("scope", ""), form.get("reason", "")
        scope_type, scope_id = parse_scope(scope)
        state = ctx.load_state()
        if not ctx.step_up_ok(form):
            return ctx.step_up_refused()
        try:
            with engine.begin() as conn:
                killswitch.activate(
                    conn, clock, ctx.rng, tenant_id=tenant(state), scope_type=scope_type,
                    scope_id=scope_id, actor=ctx.actor(), reason=reason,
                )  # fmt: skip
        except (killswitch.KillSwitchError, RegistryError) as exc:
            return kill_preview(scope, reason, str(exc))
        return RedirectResponse("/admin#kill-title", status_code=303)

    @app.post("/admin/kill-switch/{switch_id}/off")
    async def kill_off(switch_id: uuid.UUID, request: Request):
        form = await ctx.read_form(request)
        state = ctx.load_state()
        if not ctx.step_up_ok(form):
            return ctx.step_up_refused()
        try:
            with engine.begin() as conn:
                approvals.request_kill_switch_off(
                    conn, clock, ctx.rng, tenant_id=tenant(state), switch_id=switch_id,
                    actor=ctx.actor(), reason=form.get("reason", ""),
                )  # fmt: skip
        except (approvals.ApprovalError, RegistryError) as exc:
            return refused("The request was refused", f"{exc} The kill switch is still on.")
        return RedirectResponse("/approvals#pending-title", status_code=303)
