"""Sign-in, sessions and the permission of every route (FR-13, SEC-13, SEC-14)."""

import re
import uuid

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import func, select

from keepair import iam
from keepair.demo.seed import DEMO_PASSWORD, agent_name, demo_token
from keepair.failures import FAILURES_TOTAL
from keepair.permissions import STEP_UP, Perm, allowed
from keepair.schema import audit_log
from keepair.startup import DemoDataInProduction
from keepair.web.access import PAGE_PERMS, ROUTE_PERMS
from keepair.web.app import create_app
from keepair.web.pages import PAGES
from tests.system.conftest import ORIGIN, make_ui

pytestmark = pytest.mark.req("FR-13", "SEC-14")

ROLE_USERS = {"ADMIN": "alice.admin", "FINANCE": "fiona.finance", "ENGINEERING": "omar.owner",
              "AUDITOR": "ava.auditor"}  # fmt: skip
NOT_ALLOWED = "Your role does not allow this"
QUERY = {"/gateway/block": "?type=vendor&id=vendor-a", "/gateway/lift": "?type=vendor&id=vendor-b",
         "/admin/kill-switch": "?scope=GLOBAL:"}  # fmt: skip


def concrete(path: str) -> str:
    """A route template with its parameters filled in by an ID that does not exist."""
    return re.sub(r"\{[a-z_]+\}", str(uuid.UUID(int=7)), path)


def routes(ui) -> set[tuple[str, str]]:
    found = set()
    for route in ui.client.app.routes:
        if isinstance(route, APIRoute):
            found |= {(m, route.path) for m in route.methods if m != "HEAD"}
    return found


def call(ui, method: str, path: str):
    if method == "GET":
        return ui.client.get(concrete(path) + QUERY.get(path, ""), follow_redirects=False)
    return ui.post(concrete(path), {})


def test_every_route_names_a_permission_and_no_entry_is_stale(ui):
    assert routes(ui) == set(ROUTE_PERMS)
    assert set(PAGE_PERMS) == {p.slug for p in PAGES}


def test_a_route_without_a_permission_entry_is_refused(ui, monkeypatch):
    """Default deny: forgetting the table entry makes the route unreachable, not open."""
    monkeypatch.delitem(ROUTE_PERMS, ("GET", "/budgets"))
    response = ui.client.get("/budgets")
    assert response.status_code == 403 and "no permission entry" in response.text


@pytest.mark.req("FR-13 (complete authorization checks)", "TB-9")
def test_anonymous_visitor_reaches_nothing_but_sign_in(ui, engine):
    visitor = ui.anonymous()
    with engine.connect() as conn:
        before = conn.execute(select(func.count()).select_from(audit_log)).scalar_one()
    for (method, path), perm in sorted(ROUTE_PERMS.items()):
        response = call(visitor, method, path)
        if perm is Perm.PUBLIC:
            assert (
                response.status_code != 303
                or response.headers["location"] != "/login"
                or (path.startswith("/login"))
            ), path
            continue
        assert response.status_code == 303 and response.headers["location"] == "/login", (
            method, path, response.status_code,
        )  # fmt: skip
        assert "DEMO" not in response.text and "Northwind" not in response.text
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(audit_log)).scalar_one() == before


@pytest.mark.req("FR-13 (permission matrix)", "SEC-14 (role separation)")
@pytest.mark.parametrize("role", sorted(ROLE_USERS))
def test_every_route_follows_the_permission_matrix(ui, role):
    person = ui.as_user(ROLE_USERS[role])
    for (method, path), perm in sorted(ROUTE_PERMS.items()):
        if (method, path) == ("POST", "/logout"):
            continue  # checked in its own test: it would end this walk
        response = call(person, method, path)
        refused = response.status_code == 403 and NOT_ALLOWED in response.text
        assert refused is not allowed(role, perm), (role, method, path, response.status_code)
    nav = [a["href"] for a in person.soup("/").select("nav.nav a")]
    assert nav == [p.path for p in PAGES if allowed(role, PAGE_PERMS[p.slug])]
    if role != "ADMIN":
        assert ui.metrics.value("keepair_authz_denied_total", permission="block") >= 1


STEP_UP_FORMS = {
    "/gateway/block": {"type": "vendor", "id": "vendor-a", "reason": "A good enough reason."},
    "/gateway/lift": {"type": "vendor", "id": "vendor-b", "reason": "A good enough reason."},
    "/admin/kill-switch": {"scope": "GLOBAL:", "reason": "A good enough reason."},
    "/admin/users": {"username": "new.person", "display_name": "New Person", "role": "FINANCE"},
}


@pytest.mark.req("SEC-13 (step-up for policy changes)")
def test_admin_policy_change_requires_step_up(ui, engine):
    """Every route whose permission is in STEP_UP refuses without a fresh code."""
    posts = sorted(p for (m, p), perm in ROUTE_PERMS.items() if m == "POST" and perm in STEP_UP)
    assert len(posts) == 10
    with engine.connect() as conn:
        users_before = conn.execute(select(func.count()).select_from(iam.users)).scalar_one()
    for n, path in enumerate(posts):
        form = dict(STEP_UP_FORMS.get(path, {"reason": "A good enough reason.",
                                             "decision": "approve", "status": "DISABLED"}))  # fmt: skip
        if n % 2:
            form["totp"] = "000000"  # a wrong code; the others send none at all
        response = ui.post(concrete(path), form)
        if "{budget_id}" in path:
            assert response.status_code == 404  # no such budget: nothing to change
            continue
        assert response.status_code == 403, (path, response.status_code)
        assert "Authenticator code not accepted" in response.text
    with engine.connect() as conn:
        done = set(conn.execute(select(audit_log.c.action)).scalars())
        users_after = conn.execute(select(func.count()).select_from(iam.users)).scalar_one()
    assert users_after == users_before
    assert not {a for a in done if a.split(".")[0] in ("registry", "kill_switch", "budget")} - {
        "registry.blocked"  # the three seeded blocks
    }
    assert not ui.soup("/").select_one("[data-kill-band]")
    # Five bad codes lock the account, and that is visible (hard rule 5).
    assert ui.metrics.value(FAILURES_TOTAL, code="ACCOUNT_LOCKED") >= 1
    assert ui.soup("/").select_one('tr[data-alert-code="ACCOUNT_LOCKED"]')
    assert ui.post("/gateway/block", {**STEP_UP_FORMS["/gateway/block"],
                                      "totp": ui.code()}).status_code == 403  # locked  # fmt: skip


@pytest.mark.req("FR-13", "SEC-13")
def test_sign_in_with_password_and_code_through_the_pages(ui):
    visitor = ui.anonymous()
    first = visitor.client.get("/budgets", follow_redirects=False)
    assert first.status_code == 303 and first.headers["location"] == "/login"
    page = visitor.soup("/login")
    assert page.select_one("[data-demo-label]")  # hard rule 2: DEMO on every page
    assert page.select_one("[data-demo-password]").get_text() == DEMO_PASSWORD
    assert "alice.admin" in page.select_one("[data-demo-accounts]").get_text()
    assert page.select_one("input[name=password]")["type"] == "password"
    assert not page.select("nav.nav")  # nothing to navigate to yet

    for username, password in (
        ("alice.admin", "wrong-password-x"),
        ("no.such.user", DEMO_PASSWORD),
    ):
        wrong = visitor.post("/login", {"username": username, "password": password})
        assert wrong.status_code == 401 and "Sign-in failed" in wrong.text
        assert "set-cookie" not in wrong.headers
    assert ui.metrics.value("keepair_sign_in_failed_total", step="password") == 2

    ok = visitor.post("/login", {"username": "alice.admin", "password": DEMO_PASSWORD})
    assert ok.status_code == 303 and ok.headers["location"] == "/login/code"
    cookie = ok.headers["set-cookie"].lower()
    assert cookie.startswith(f"{iam.COOKIE}=") and "httponly" in cookie
    assert "samesite=strict" in cookie and "path=/" in cookie
    # The password alone opens nothing.
    assert visitor.client.get("/budgets", follow_redirects=False).headers["location"] == "/login"

    code_page = visitor.soup("/login/code")
    assert "alice.admin" in code_page.get_text()
    shown = code_page.select_one("[data-demo-code]")["data-demo-code"]
    assert len(shown) == 6 and shown.isdigit()
    bad = visitor.post("/login/code", {"totp": "000000" if shown != "000000" else "111111"})
    assert bad.status_code == 401 and "not accepted" in bad.text
    done = visitor.post("/login/code", {"totp": shown})
    assert done.status_code == 303 and done.headers["location"] == "/"
    home = visitor.soup("/")
    bar = home.select_one("form.userbar")
    assert bar["data-user"] == "alice.admin" and "Alice Okafor" in bar.get_text()
    assert "Administrator" in bar.get_text()
    # The code that signed in cannot be used again for a sensitive action.
    replay = visitor.post("/gateway/block", {**STEP_UP_FORMS["/gateway/block"], "totp": shown})
    assert replay.status_code == 403 and "already used" in replay.text


@pytest.mark.req("FR-13", "SEC-13")
def test_sign_out_ends_the_session_on_the_server(ui):
    token = ui.client.cookies.get(iam.COOKIE)
    out = ui.post("/logout")
    assert out.status_code == 303 and out.headers["location"] == "/login"
    assert f'{iam.COOKIE}=""' in out.headers["set-cookie"] or "max-age=0" in (
        out.headers["set-cookie"].lower()
    )
    again = ui.anonymous()
    again.client.cookies.set(iam.COOKIE, token)  # a copy of the old cookie
    assert again.client.get("/", follow_redirects=False).status_code == 303


@pytest.mark.req("SEC-14 (credentials of one listener are refused by the other)", "B-n9")
def test_cross_route_credentials_rejected(ui_traffic):
    ui, gw = ui_traffic, ui_traffic.gw
    agent_token = demo_token(agent_name("Ticket Triage"))
    visitor = ui.anonymous()
    as_header = visitor.client.get(
        "/admin", headers={"Authorization": f"Bearer {agent_token}"}, follow_redirects=False
    )
    assert as_header.status_code == 303  # a gateway token is not a session
    visitor.client.cookies.set(iam.COOKIE, agent_token)
    assert visitor.client.get("/admin", follow_redirects=False).status_code == 303
    assert visitor.post("/admin/kill-switch", {"scope": "GLOBAL:"}).status_code == 303

    session = ui.client.cookies.get(iam.COOKIE)
    body = {"model": "model-1", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 8}
    for headers in (
        {"Authorization": f"Bearer {session}", "Idempotency-Key": "x-1"},
        {"Cookie": f"{iam.COOKIE}={session}", "Idempotency-Key": "x-2"},
    ):
        refused = gw.client.post("/v1/chat/completions", json=body, headers=headers)
        assert refused.status_code == 401  # a session is not a gateway token
    for path in ("/admin", "/login", "/approvals", "/audit-log"):
        assert gw.client.get(path).status_code == 404  # the gateway serves no such route


@pytest.mark.req("Hard rule 2 (demo material is labelled)", "SEC-23")
def test_demo_helpers_exist_only_in_demo_mode(settings, engine):
    plain = make_ui(settings.model_copy(update={"demo_mode": False}), engine)
    login = plain.anonymous().soup("/login")
    assert not login.select("[data-demo-accounts], [data-demo-password], [data-demo-label]")
    assert DEMO_PASSWORD not in str(login)
    form = plain.soup("/gateway/block?type=vendor&id=vendor-a")
    assert form.select_one("input[name=totp]") and not form.select("[data-demo-code], .demo-code")
    visitor = plain.anonymous()
    visitor.post("/login", {"username": "alice.admin", "password": DEMO_PASSWORD})
    assert not visitor.soup("/login/code").select("[data-demo-code]")
    assert plain.soup("/admin").select_one("#console-title") is None
    # And production refuses to start on demo data at all.
    with pytest.raises(DemoDataInProduction):
        create_app(settings.model_copy(update={"env": "prod"}), engine=engine)
    with pytest.raises(iam.MissingMfaKey):
        iam.load_mfa_key(None, "prod")


@pytest.mark.req("SEC-36", "Hard rule 5")
def test_sign_in_page_says_so_when_the_database_is_down(ui_db_down):
    page = ui_db_down.soup("/login", status=503)
    assert "database cannot be reached" in page.select_one(".notice--bad").get_text()
    refused = ui_db_down.post("/login", {"username": "alice.admin", "password": DEMO_PASSWORD})
    assert refused.status_code == 503 and "set-cookie" not in refused.headers
    assert ui_db_down.metrics.value(FAILURES_TOTAL, code="DATABASE_UNREACHABLE") >= 1
    outage = ui_db_down.soup("/admin", status=503)
    assert outage.find("h1").get_text() == "The database cannot be reached"
    assert outage.select_one("[data-demo-label]")
    assert outage.select_one('tr[data-alert-code="DATABASE_UNREACHABLE"]')
    assert ORIGIN  # imported for the helpers of this module


@pytest.mark.req("Hard rule 2 (demo material)", "SEC-23")
def test_demo_code_endpoint_serves_only_the_caller_and_only_in_demo_mode(settings, engine):
    ui = make_ui(settings, engine)
    answer = ui.client.get("/api/demo-code")
    assert answer.status_code == 200 and answer.headers["cache-control"] == "no-store"
    code = answer.json()["code"]
    assert (
        code
        == ui.soup("/gateway/block?type=vendor&id=vendor-a").select_one("[data-demo-code]")[
            "data-demo-code"
        ]
    )
    blocked = ui.post("/gateway/block", {**STEP_UP_FORMS["/gateway/block"], "totp": code})
    assert blocked.status_code == 303
    assert ui.client.get("/api/demo-code").json()["code"] not in (code, None)  # it moved on
    assert ui.anonymous().client.get("/api/demo-code").status_code == 404  # nobody: nothing
    half = ui.anonymous()
    half.post("/login", {"username": "bob.admin", "password": DEMO_PASSWORD})
    assert len(half.client.get("/api/demo-code").json()["code"]) == 6  # for the code step
    plain = make_ui(settings.model_copy(update={"demo_mode": False}), engine)
    assert plain.client.get("/api/demo-code").status_code == 404
