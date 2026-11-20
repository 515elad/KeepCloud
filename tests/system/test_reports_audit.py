"""Showback report, CSV export, audit log viewer and chain verification (phase 6)."""

import csv
import io

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from keepair.demo.seed import DEMO_PASSWORD
from keepair.demo.tamper import tamper
from keepair.failures import FAILURES_TOTAL
from keepair.schema import audit_log
from keepair.web.access import ROUTE_PERMS
from tests.system.conftest import upload

REASON = "Agreed in the weekly review."
WRONG = "wrong-password-x"  # pragma: allowlist secret


def cells(row) -> list[str]:
    return [td.get_text(" ", strip=True) for td in row.find_all("td")]


def export(ui, query: str = "") -> list[list[str]]:
    response = ui.client.get(f"/reports/showback.csv{query}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"\xef\xbb\xbf")  # UTF-8 mark for spreadsheets
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


def audit_actions(engine) -> list[str]:
    with engine.connect() as conn:
        return list(conn.execute(select(audit_log.c.action).order_by(audit_log.c.seq)).scalars())


# --- Showback (FR-12) ------------------------------------------------------------------


@pytest.mark.req("FR-12 (showback)", "FR-07", "UX-8 (never sum across states)")
def test_showback_lists_every_project_with_one_state_per_column(ui_traffic):
    soup = ui_traffic.soup("/reports")
    rows = {r["data-project"]: cells(r) for r in soup.select("table[data-table=showback] tbody tr")}
    assert len(rows) == 13  # 12 projects and the Platform team's shared cost
    assert rows["Build Assistant"] == [
        "Engineering", "Platform", "Build Assistant", "Omar Haddad",
        "22,000.00 USD", "32,671.20 USD", "No data",
    ]  # fmt: skip
    assert rows["Call Notes"][3] == "? Unowned"
    assert rows["Shared by the team"][:4] == ["Engineering", "Platform", "Shared by the team",
                                              "Omar Haddad"]  # fmt: skip
    total = soup.select_one("tr[data-total]")
    states = [c["data-finalization"] for c in total.select("[data-finalization]")]
    assert states == ["ESTIMATED", "PROVIDER_REPORTED", "INVOICED"]
    figures = cells(total)
    assert figures[1].startswith("182,373.32 USD") and figures[3].startswith("No data")
    # The provider column holds what is allocated; the rest is named, not hidden.
    assert figures[2].startswith("182,363.46 USD")
    assert soup.select_one("[data-not-allocated]").get_text().startswith("59.75 USD")
    assert "never added to each other" in soup.get_text()


@pytest.mark.req("FR-12", "FR-07")
def test_showback_without_billing_data_shows_no_data_not_zero(ui):
    soup = ui.soup("/reports")
    row = cells(soup.select_one('tr[data-project="Translation"]'))
    assert row[4].endswith("USD") and row[5] == "No data" and row[6] == "No data"


@pytest.mark.req("FR-12 (CSV export)", "SEC-29")
def test_csv_export_has_the_same_rows_with_exact_amounts(ui_traffic, engine):
    table = export(ui_traffic, "?period=2026-01")
    assert table[0] == [
        "Period", "Department", "Team", "Project", "Owner", "Currency",
        "Estimated (gateway, not a charge)", "Provider-reported (allocated)",
        "Invoiced (allocated)",
    ]  # fmt: skip
    body = {r[3]: r for r in table[1:]}
    assert len(body) == 13
    assert body["Build Assistant"] == [
        "2026-01", "Engineering", "Platform", "Build Assistant", "Omar Haddad", "USD",
        "22000.000000", "32671.196765", "",
    ]  # fmt: skip
    assert body["Call Notes"][4] == "Unowned"
    # SEC-29: every export is recorded.
    assert audit_actions(engine)[-1] == "report.exported"
    with engine.connect() as conn:
        last = conn.execute(select(audit_log).order_by(audit_log.c.seq.desc()).limit(1)).one()
    assert last.actor == "alice.admin" and last.after == {"period": "2026-01", "rows": 13,
                                                           "format": "csv"}  # fmt: skip


@pytest.mark.req("SEC-29 (CSV formula neutralization)", "S-19")
@pytest.mark.parametrize("start", ["=", "+", "-", "@", "\uff20"])
def test_csv_formula_neutralized_in_the_export(ui, start):
    """A person's name that starts like a formula reaches the file as plain text."""
    payload = f'{start}HYPERLINK("http://evil.example","click")'
    made = ui.post("/admin/users", {"username": "mallory.m", "display_name": payload,
                                    "role": "FINANCE", "totp": ui.code()})  # fmt: skip
    assert made.status_code == 200
    href = next(r.find("a")["href"] for r in ui.soup("/budgets").select("tr[data-budget-id]")
                if r.find("a").get_text() == "Call Notes")  # fmt: skip
    option = next(o["value"] for o in ui.soup(href).select("select[name=user_id] option")
                  if "mallory.m" in o.get_text())  # fmt: skip
    assert ui.post(f"{href}/owner", {"user_id": option, "reason": REASON,
                                     "totp": ui.code()}).status_code == 303  # fmt: skip
    raw = ui.client.get("/reports/showback.csv").content.decode("utf-8-sig")
    row = next(r for r in csv.reader(io.StringIO(raw)) if r[3] == "Call Notes")
    assert row[4] == "'" + payload  # the apostrophe makes a spreadsheet show it as text
    for line in raw.splitlines():
        for value in next(csv.reader([line])):
            assert not value.startswith(("=", "+", "@", "\uff20")), value
            assert not value.startswith("-") or value.replace("-", "").replace(".", "").isdigit()
    # On the page it is escaped text, not markup.
    assert payload in ui.soup("/reports").select_one('tr[data-project="Call Notes"]').get_text()


@pytest.mark.req("FR-13", "SEC-29 (exports are restricted)")
def test_who_may_download(ui):
    for name, may in (("fiona.finance", True), ("ava.auditor", True), ("omar.owner", False)):
        person = ui.as_user(name)
        page = person.soup("/reports")
        assert bool(page.select_one("a[data-export]")) is may
        assert (person.client.get("/reports/showback.csv").status_code == 200) is may
    assert ui.client.get("/reports/showback.csv?period=1999-01").status_code == 200  # falls back
    assert ui.anonymous().client.get(
        "/reports/showback.csv", follow_redirects=False
    ).status_code == 303  # fmt: skip


# --- Audit log (FR-12, SEC-31, SEC-32) --------------------------------------------------


@pytest.mark.req("FR-12 (audit log viewer)", "SEC-31")
def test_audit_log_shows_who_did_what_when_and_why(ui):
    soup = ui.soup("/audit-log")
    assert soup.select_one("[data-audit-count]").get_text() == "8"
    rows = soup.select("table[data-table=audit] tbody tr")
    assert [int(r["data-seq"]) for r in rows] == list(range(8, 0, -1))  # newest first
    newest = cells(rows[0])
    assert newest[1] == "2026-01-13 09:00:00 UTC" and newest[2] == "alice.admin"
    assert newest[3] == "registry.blocked" and newest[4] == "vendor vendor-b"
    assert newest[5] == "Contract review in progress. Blocked until legal sign-off."
    assert newest[6] == 'Before {"status": "ALLOWED"} After {"status": "BLOCKED"}'
    assert len(newest[7]) == 12 and int(newest[7], 16) >= 0
    assert soup.select_one('form[action="/audit-log/verify"] button')
    assert not soup.select('form[action*="delete"], form[action*="edit"]')


@pytest.mark.req("SEC-32", "FR-12")
def test_verify_button_recomputes_the_chain_and_shows_the_result(ui, engine):
    response = ui.post("/audit-log/verify")
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    result = soup.select_one("[data-verify]")
    assert result["data-verify"] == "ok"
    assert "Chain verified. 8 records were recomputed" in result.get_text(" ", strip=True)
    assert ui.metrics.value("keepair_audit_verify_total", result="ok") == 1
    assert audit_actions(engine)[-1] == "audit.verified"  # the check itself is recorded
    assert not ui.soup("/").select('tr[data-alert-code="AUDIT_CHAIN_BROKEN"]')


@pytest.mark.req("SEC-32 (tamper evidence)", "Hard rule 5", "FR-21 (SEV1)")
def test_tampering_is_shown_as_a_verify_failure_and_a_sev1_alert(ui, engine):
    with engine.begin() as conn:
        seq = tamper(conn)  # what ./run.sh tamper does, as the owner of the tables
    shown = cells(ui.soup("/audit-log").select_one(f'tr[data-seq="{seq}"]'))
    assert shown[5] == "Edited outside the application."  # the page alone cannot tell
    response = ui.post("/audit-log/verify")
    assert response.status_code == 409
    result = BeautifulSoup(response.text, "html.parser").select_one("[data-verify]")
    text = result.get_text(" ", strip=True)
    assert result["data-verify"] == "broken" and f"Chain broken at record {seq}." in text
    assert "was changed after it was written" in text and "7 records before it are intact" in text
    assert "AUDIT_CHAIN_BROKEN" in text
    assert ui.metrics.value(FAILURES_TOTAL, code="AUDIT_CHAIN_BROKEN") == 1
    alert = ui.soup("/").select_one('tr[data-alert-code="AUDIT_CHAIN_BROKEN"]')
    assert "SEV1" in alert.get_text() and f"record {seq}" in alert.get_text()


@pytest.mark.req("FR-13", "SEC-31")
def test_only_administrators_and_auditors_see_the_audit_log(ui):
    ava = ui.as_user("ava.auditor")
    assert ava.soup("/audit-log").select_one("table[data-table=audit]")
    assert ava.post("/audit-log/verify").status_code == 200
    for name in ("fiona.finance", "omar.owner"):
        person = ui.as_user(name)
        assert person.client.get("/audit-log").status_code == 403
        assert person.post("/audit-log/verify").status_code == 403
        assert "/audit-log" not in [a["href"] for a in person.soup("/").select("nav.nav a")]


@pytest.mark.req("FR-12")
def test_audit_log_pages_through_older_records(ui, engine):
    from keepair import audit
    from keepair.demo.seed import demo_clock

    with engine.begin() as conn:
        for n in range(120):
            audit.record(conn, demo_clock(), tenant_id=None, actor="tester", action="test.fill",
                         subject_type="thing", subject_id=str(n))  # fmt: skip
    first = ui.soup("/audit-log")
    assert first.select_one("[data-audit-count]").get_text() == "128"
    rows = first.select("table[data-table=audit] tbody tr")
    assert len(rows) == 100 and rows[0]["data-seq"] == "128"
    older = first.find("a", string="Older records")["href"]
    second = ui.soup(older).select("table[data-table=audit] tbody tr")
    assert [r["data-seq"] for r in second][:2] == ["28", "27"] and second[-1]["data-seq"] == "1"
    ui.soup("/audit-log?before=not-a-number", status=404)


# --- Every administrative action is recorded (SEC-31) ------------------------------------


def _block(ui):
    return ui.post("/gateway/block", {"type": "model", "id": "vendor-a/model-2",
                                      "reason": REASON, "totp": ui.code()})  # fmt: skip


def _lift(ui):
    return ui.post("/gateway/lift", {"type": "vendor", "id": "vendor-b", "reason": REASON,
                                     "totp": ui.code()})  # fmt: skip


def _pending_id(ui) -> str:
    return ui.soup("/approvals").select_one("tr[data-pending-id]")["data-pending-id"]


def _decide(ui):
    _lift(ui)
    bob = ui.as_user("bob.admin")
    return bob.post(f"/approvals/{_pending_id(bob)}/decide",
                    {"decision": "reject", "totp": bob.code()})  # fmt: skip


def _cancel(ui):
    _lift(ui)
    return ui.post(f"/approvals/{_pending_id(ui)}/cancel")


def _budget(ui, name="Call Notes") -> str:
    return next(r.find("a")["href"] for r in ui.soup("/budgets").select("tr[data-budget-id]")
                if r.find("a").get_text() == name)  # fmt: skip


def _owner(ui):
    href = _budget(ui)
    user = ui.soup(href).select("select[name=user_id] option")[1]["value"]
    return ui.post(f"{href}/owner", {"user_id": user, "reason": REASON, "totp": ui.code()})


def _policy(ui):
    return ui.post(f"{_budget(ui)}/policy", {"policy": "SOFT", "reason": REASON,
                                             "totp": ui.code()})  # fmt: skip


def _user_form(ui, name="ava.auditor") -> str:
    row = next(r for r in ui.soup("/admin").select("tr[data-user-row]")
               if r["data-user-row"] == name)  # fmt: skip
    return row.find("form")["action"]


def _kill(ui):
    return ui.post("/admin/kill-switch", {"scope": "VENDOR:vendor-a", "reason": REASON,
                                          "totp": ui.code()})  # fmt: skip


def _kill_off(ui):
    _kill(ui)
    switch = ui.soup("/admin").select_one("tr[data-kill]")["data-kill"]
    return ui.post(f"/admin/kill-switch/{switch}/off", {"reason": REASON, "totp": ui.code()})


def _held(ui):
    held = ui.soup("/approvals").select_one("tr[data-held]")["data-held"]
    return ui.post(f"/approvals/held/{held}", {"decision": "approve"})


def _credential(ui):
    agent = ui.soup("/gateway").select_one("select[name=agent_id] option")["value"]
    return ui.post("/gateway/credentials", {"agent_id": agent, "label": "audit test"})


def _revoke(ui):
    form = ui.soup("/gateway").select_one("tr[data-credential] form")
    return ui.post(form["action"])


def _assign(ui):
    row = next(r for r in ui.soup("/spend").select("table[data-table=queue] tbody tr")
               if r.select_one("form"))  # fmt: skip
    form = row.select_one("form")
    project = form.select("select option")[-1]["value"]
    return ui.post("/spend/assign", {"record_id": form.find("input")["value"],
                                     "project_id": project, "reason": REASON})  # fmt: skip


def _ack(ui):
    ui.post("/admin/demo/ledger", {"action": "stop"})
    ui.gw.chat("Ticket Triage")
    ui.post("/admin/demo/ledger", {"action": "restore"})
    return ui.post("/gateway/fail-open/acknowledge")


def _bad_sign_in(ui):
    return ui.anonymous().post("/login", {"username": "bob.admin", "password": WRONG})


# POST route -> (how to perform it, the audit action it must leave).
AUDITED = {
    "/login": (_bad_sign_in, "auth.sign_in_failed"),
    "/login/code": (None, "auth.sign_in"),  # covered by test_access (full sign-in)
    "/logout": (lambda ui: ui.as_user("bob.admin").post("/logout"), "auth.sign_out"),
    "/gateway/block": (_block, "registry.blocked"),
    "/gateway/lift": (_lift, "block_lift.requested"),
    "/approvals/{approval_id}/decide": (_decide, "block_lift.rejected"),
    "/approvals/{approval_id}/cancel": (_cancel, "block_lift.cancelled"),
    "/approvals/held/{reservation_id}": (_held, "held_request.approved"),
    "/budgets/{budget_id}/owner": (_owner, "budget.owner_changed"),
    "/budgets/{budget_id}/policy": (_policy, "budget.policy_changed"),
    "/admin/users": (lambda ui: ui.post("/admin/users", {
        "username": "nina.new", "display_name": "Nina New", "role": "FINANCE",
        "totp": ui.code()}), "user.created"),
    "/admin/users/{user_id}/status": (lambda ui: ui.post(_user_form(ui), {
        "status": "DISABLED", "totp": ui.code()}), "user.disabled"),
    "/admin/users/{user_id}/reset": (lambda ui: ui.post(
        _user_form(ui).replace("/status", "/reset"), {"totp": ui.code()}),
        "user.credentials_reset"),
    "/admin/kill-switch": (_kill, "kill_switch.activated"),
    "/admin/kill-switch/{switch_id}/off": (_kill_off, "kill_switch_off.requested"),
    "/admin/demo/ledger": (lambda ui: ui.post("/admin/demo/ledger", {"action": "stop"}),
                           "demo.ledger_fault"),
    "/admin/demo/requests": (None, None),  # sends ordinary gateway requests, changes no setting
    "/gateway/credentials": (_credential, "credential.created"),
    "/gateway/credentials/{credential_id}/revoke": (_revoke, "credential.revoked"),
    "/gateway/fail-open/acknowledge": (_ack, "fail_open.acknowledged"),
    "/spend/upload": (lambda ui: upload(ui, "vendor-a-usage-2026-01-correction.csv"),
                      "billing.file_loaded"),
    "/spend/assign": (_assign, "billing.record_assigned"),
    "/audit-log/verify": (lambda ui: ui.post("/audit-log/verify"), "audit.verified"),
}  # fmt: skip


@pytest.mark.req("SEC-31")
def test_every_post_route_has_an_audit_expectation():
    posts = {path for (method, path) in ROUTE_PERMS if method == "POST"}
    assert posts == set(AUDITED)


@pytest.mark.req("SEC-31 (every admin, policy, budget, owner, override and kill switch action)")
@pytest.mark.parametrize("path", sorted(p for p, (run, _) in AUDITED.items() if run))
def test_every_admin_action_audited(ui_traffic, engine, path):
    run, expected = AUDITED[path]
    before = len(audit_actions(engine))
    response = run(ui_traffic)
    assert response.status_code in (200, 303, 401), (path, response.status_code)
    new = audit_actions(engine)[before:]
    assert expected in new, (path, new)
    with engine.connect() as conn:
        row = conn.execute(
            select(audit_log).where(audit_log.c.action == expected)
            .order_by(audit_log.c.seq.desc()).limit(1)
        ).one()  # fmt: skip
    assert (
        row.actor
        and row.subject_type
        and row.subject_id
        and row.occurred_at.utcoffset() is not None
    )
    recorded = f"{row.before} {row.after} {row.reason}"
    for secret in (WRONG, DEMO_PASSWORD, "kair_"):
        assert secret not in recorded  # no password, code or token is ever written here
    from keepair import audit

    with engine.connect() as conn:
        assert audit.verify(conn).ok  # the chain holds after every kind of action


@pytest.mark.req("SEC-31", "SEC-29")
def test_refused_billing_file_is_recorded_too(ui, engine):
    assert upload(ui, "broken-example.csv").status_code == 422
    assert audit_actions(engine)[-1] == "billing.file_refused"
