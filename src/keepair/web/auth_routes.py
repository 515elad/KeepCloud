"""Sign-in and sign-out (FR-13, SEC-13). Two steps: password, then authenticator code."""

from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from keepair import iam
from keepair.demo.seed import DEMO_PASSWORD
from keepair.permissions import ROLE_LABEL, Role
from keepair.schema import app_meta, users

SIGN_IN_FAILED_TOTAL = "keepair_sign_in_failed_total"
FAILED_TEXT = (
    "Sign-in failed. Check the user name and password. After 5 failed attempts an account "
    "is locked for 15 minutes."
)


def register(ctx) -> None:
    app, engine, clock = ctx.app, ctx.engine, ctx.clock
    ctx.metrics.describe(SIGN_IN_FAILED_TOTAL, "Failed sign-in attempts, by step.")
    secure = ctx.settings.env == "prod"  # the demo runs on http://localhost

    def set_cookie(response, token: str) -> None:
        response.set_cookie(
            iam.COOKIE, token, max_age=iam.ABSOLUTE_S, httponly=True, samesite="strict",
            secure=secure, path="/",
        )  # fmt: skip

    def demo_accounts(conn) -> list | None:
        """Demo mode only: the seeded accounts, so the demo needs no setup."""
        is_demo = conn.execute(select(app_meta.c.value).where(app_meta.c.key == "demo")).scalar()
        if not ctx.demo_enabled or is_demo != "true":
            return None
        rows = conn.execute(
            select(users.c.username, users.c.display_name, users.c.role, users.c.created_by)
            .where(users.c.status == "ACTIVE")
            .order_by(users.c.role, users.c.username)
        )
        return [(r.username, r.display_name, ROLE_LABEL[Role(r.role)])
                for r in rows if r.created_by == "seed"]  # fmt: skip

    def report_if_locked(username: str) -> None:
        with engine.connect() as conn:
            locked = bool(username) and iam.is_locked(conn, clock, username)
        if locked:
            ctx.reporter.report(
                "ACCOUNT_LOCKED",
                "An account was locked for 15 minutes after 5 failed sign-in attempts. "
                "See the audit record for the account.",
                dedupe_s=60,
            )

    def login_page(request: Request, error: str | None = None, status: int = 200):
        try:
            with engine.connect() as conn:
                accounts = demo_accounts(conn)
                any_user = conn.execute(select(users.c.id).limit(1)).first() is not None
        except SQLAlchemyError:
            accounts, any_user, error, status = None, True, (
                "The database cannot be reached, so nobody can be signed in right now."
            ), 503  # fmt: skip
            ctx.reporter.report(
                "DATABASE_UNREACHABLE",
                "The database could not be reached from the sign-in page.",
                dedupe_s=60,
            )
        return ctx.render(
            "login.html", status_code=status, error=error, accounts=accounts, any_user=any_user,
            demo_password=DEMO_PASSWORD if accounts else None,
        )  # fmt: skip

    @app.get("/login", response_class=HTMLResponse)
    def login(request: Request):
        return login_page(request)

    @app.post("/login")
    async def login_submit(request: Request):
        form = await ctx.read_form(request)
        try:
            with engine.begin() as conn:
                token = iam.sign_in_password(
                    conn, clock, ctx.rng, form.get("username", ""), form.get("password", "")
                )
        except SQLAlchemyError:
            return login_page(request)
        if token is None:
            ctx.metrics.inc(SIGN_IN_FAILED_TOTAL, step="password")
            report_if_locked(form.get("username", ""))
            return login_page(request, FAILED_TEXT, 401)
        response = RedirectResponse("/login/code", status_code=303)
        set_cookie(response, token)
        return response

    def code_page(request: Request, error: str | None = None, status: int = 200):
        token = request.cookies.get(iam.COOKIE)
        with engine.connect() as conn:
            username = iam.pending_username(conn, clock, token)
            if username is None:
                return RedirectResponse("/login", status_code=303)
            code = None
            if demo_accounts(conn) is not None:
                user_id = conn.execute(
                    select(users.c.id).where(users.c.username == username)
                ).scalar_one()
                code = iam.demo_code(conn, clock, ctx.box, user_id)
        return ctx.render(
            "login_code.html", status_code=status, error=error, username=username,
            pending_code=code,
        )  # fmt: skip

    @app.get("/login/code", response_class=HTMLResponse)
    def login_code(request: Request):
        return code_page(request)

    @app.post("/login/code")
    async def login_code_submit(request: Request):
        form = await ctx.read_form(request)
        token = request.cookies.get(iam.COOKIE)
        with engine.begin() as conn:
            actor = iam.sign_in_code(conn, clock, ctx.box, token, form.get("totp", ""))
        if actor is None:
            ctx.metrics.inc(SIGN_IN_FAILED_TOTAL, step="code")
            with engine.connect() as conn:
                pending = iam.pending_username(conn, clock, token)
            report_if_locked(pending or "")
            return code_page(
                request, "That code was not accepted. Enter the code your authenticator shows now.",
                401,
            )  # fmt: skip
        return RedirectResponse("/", status_code=303)

    @app.get("/api/demo-code")
    def demo_code_api(request: Request) -> JSONResponse:
        """Demo mode only: the code the caller's authenticator would show now, so that a
        form can show the next code without a reload. The caller is the signed-in user,
        or the user who has just given the right password."""
        token = request.cookies.get(iam.COOKIE)
        with engine.begin() as conn:
            if demo_accounts(conn) is None:
                raise HTTPException(status_code=404)
            actor = iam.authenticate(conn, clock, token)
            username = actor.username if actor else iam.pending_username(conn, clock, token)
            if username is None:
                raise HTTPException(status_code=404)
            user_id = conn.execute(
                select(users.c.id).where(users.c.username == username)
            ).scalar_one()
            code = iam.demo_code(conn, clock, ctx.box, user_id)
        return JSONResponse({"code": code}, headers={"Cache-Control": "no-store"})

    @app.post("/logout")
    async def logout(request: Request):
        with engine.begin() as conn:
            iam.sign_out(conn, clock, request.cookies.get(iam.COOKIE), ctx.actor())
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(iam.COOKIE, path="/")
        return response
