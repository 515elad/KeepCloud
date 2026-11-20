"""Fail-open banner (UX-7), report (FR-12) and the demo console."""

import pytest
from bs4 import BeautifulSoup

from tests.system.conftest import ALL_PATHS, make_ui

ORIGIN = {"Origin": "http://testserver"}
SOFT = "Ticket Triage"


def banner(ui, path="/"):
    return ui.soup(path).select_one("[data-fail-open-banner]")


def stop(ui):
    return ui.client.post(
        "/admin/demo/ledger", data={"action": "stop"}, headers=ORIGIN, follow_redirects=False
    )


def restore(ui):
    return ui.client.post(
        "/admin/demo/ledger", data={"action": "restore"}, headers=ORIGIN, follow_redirects=False
    )


@pytest.mark.req("UX-7")
def test_no_banner_when_nothing_failed_open(ui_traffic):
    for path in ALL_PATHS:
        assert banner(ui_traffic, path) is None
    assert ui_traffic.client.get("/api/fail-open").json() == {"signature": "0:0:0"}


@pytest.mark.req("UX-7 (fail-open banner)", "SEC-06")
def test_banner_is_on_every_page_while_active_and_cannot_be_dismissed(ui_traffic):
    ui = ui_traffic
    assert stop(ui).status_code == 303
    ui.gw.chat(SOFT), ui.gw.chat(SOFT)
    for path in [*ALL_PATHS, "/gateway/fail-open"]:
        b = banner(ui, path)
        assert b is not None, path
        assert b["role"] == "alert" and "failopen--active" in b["class"]
        text = b.get_text(" ", strip=True)
        assert "Fail-open is active" in text and "since 2026-01-15 09:00:00 UTC" in text
        assert b.select_one("[data-fail-open-count]").get_text() == "2"
        assert "Hard limits, approval budgets and every block still refuse" in text
        assert b.find("a", string="Open the fail-open report")["href"] == "/gateway/fail-open"
        button = b.find("button", string="Acknowledge")
        assert button.has_attr("disabled") and not b.find("form")
        assert "once the ledger is back" in b.find(id=button["aria-describedby"]).get_text()
    # The server refuses an acknowledgement too, not only the page.
    assert ui.client.post("/gateway/fail-open/acknowledge", headers=ORIGIN).status_code == 409
    assert banner(ui) is not None
    assert ui.client.get("/api/fail-open").json() == {"signature": "1:2:0"}


@pytest.mark.req("UX-7 (acknowledge)", "SEC-06 (replay)")
def test_banner_stays_after_recovery_until_acknowledged(ui_traffic):
    ui = ui_traffic
    stop(ui)
    ui.gw.chat(SOFT), ui.gw.chat("Reply Drafts"), ui.gw.chat(SOFT)
    assert restore(ui).status_code == 303  # the gateway replays the spool at once
    for path in ALL_PATHS:
        b = banner(ui, path)
        assert b is not None and b["role"] == "status" and "failopen--active" not in b["class"]
        text = b.get_text(" ", strip=True)
        assert "not acknowledged" in text and "They are now in the ledger" in text
        assert b.select_one("[data-fail-open-count]").get_text() == "3"
    form = banner(ui).find("form")
    assert form["action"] == "/gateway/fail-open/acknowledge" and not form.find("button").has_attr(
        "disabled"
    )
    assert ui.client.post(form["action"], headers={}).status_code == 403  # cross-site refused
    assert banner(ui) is not None
    assert ui.client.post(form["action"], headers=ORIGIN, follow_redirects=False).status_code == 303
    for path in ALL_PATHS:
        assert banner(ui, path) is None
    [row] = ui.gw.rows(
        "SELECT count(*), min(acknowledged_by) FROM fail_events WHERE acknowledged_at IS NOT NULL"
    )
    assert tuple(row) == (3, "demo-operator")


@pytest.mark.req("FR-12 (fail-open activity report)")
def test_fail_open_report_matches_fail_events(ui_traffic):
    ui = ui_traffic
    empty = ui.soup("/gateway/fail-open")
    assert "No request has been sent without a budget check" in empty.get_text()
    assert (
        empty.select_one('[data-field-id="failopen.state"] dd').get_text(strip=True)
        == "✓Not active"
    )
    stop(ui)
    (
        ui.gw.chat(SOFT),
        ui.gw.chat("Reply Drafts"),
        ui.gw.chat("Build Assistant"),
    )  # the last is refused
    during = ui.soup("/gateway/fail-open")
    assert (
        during.select_one('[data-field-id="failopen.state"] .status--failing')
        .get_text(strip=True)
        .endswith("Active")
    )
    assert during.select_one('[data-field-id="failopen.waiting"] dd').get_text(strip=True) == "2"
    assert during.select_one('[data-field-id="failopen.events"] dd').get_text(strip=True) == "0"
    restore(ui)

    soup = ui.soup("/gateway/fail-open")
    events = ui.gw.rows("SELECT * FROM fail_events ORDER BY project")
    rows = soup.select("table[data-table=fail-open] tbody tr")
    assert len(rows) == len(events) == 2
    shown = sorted(
        (r.find_all("td")[1].get_text(" ", strip=True), r.find_all("td")[2].get_text(strip=True),
         r.find_all("td")[3].get_text(strip=True)) for r in rows
    )  # fmt: skip
    assert shown == [("reply-drafts-agent Reply Drafts", "Reply Drafts", "vendor-a/model-1"),
                     ("ticket-triage-agent Ticket Triage", "Ticket Triage", "vendor-a/model-1")]  # fmt: skip
    for r in rows:
        cells = r.find_all("td")
        assert cells[4].get_text(strip=True).endswith("USD")
        assert cells[5].get_text(strip=True) == "Reported by the vendor"
        assert "Not yet" in cells[7].get_text()
    kpis = {
        k["data-field-id"]: k.find("dd").get_text(strip=True)
        for k in soup.select("dl [data-kpi][data-field-id^='failopen.']")
    }
    assert (kpis["failopen.events"], kpis["failopen.unacknowledged"], kpis["failopen.waiting"]) == (
        "2",
        "2",
        "0",
    )
    assert soup.select_one('[data-pending="SD-04"]')
    assert "Build Assistant" not in soup.select_one("table[data-table=fail-open]").get_text()
    ui.client.post("/gateway/fail-open/acknowledge", headers=ORIGIN)
    after = ui.soup("/gateway/fail-open")
    assert "demo-operator" in after.select_one("table[data-table=fail-open]").get_text()
    assert (
        after.select_one('[data-field-id="failopen.unacknowledged"] dd').get_text(strip=True) == "0"
    )


@pytest.mark.req("UX-7", "UX-6 (Unknown is never shown as healthy)")
def test_banner_is_shown_even_when_the_ui_cannot_read_its_database(
    settings, engine, unreachable_engine
):
    from tests.gateway_harness import make_gateway

    gw = make_gateway(settings, engine)
    gw.app.state.ledger_state.set_fault(True)
    gw.chat(SOFT)
    ui = make_ui(
        settings, unreachable_engine, gateway_client=gw.client
    )  # the UI's database is gone
    soup = ui.soup("/budgets")
    assert "database cannot be reached" in soup.select_one(".notice--bad").get_text()
    b = soup.select_one("[data-fail-open-banner]")
    assert (
        b is not None
        and "Fail-open is active" in b.get_text()
        and b.select_one("[data-fail-open-count]").get_text() == "1"
    )
    # And with no gateway to ask, the report says Unknown, not "Not active".
    alone = make_ui(settings, engine)
    state = alone.soup("/gateway/fail-open").select_one('[data-field-id="failopen.state"] dd')
    assert "Unknown" in state.get_text() and "does not answer" in state.get_text()


@pytest.mark.req("Owner brief phase 3 (demo console)", "SEC-06")
def test_demo_console_shows_what_an_outage_changes(ui_traffic):
    ui = ui_traffic

    def run():
        response = ui.client.post("/admin/demo/requests", headers=ORIGIN)
        assert response.status_code == 200
        soup = BeautifulSoup(response.text, "html.parser")
        return {
            (
                r.find_all("td")[0].get_text(" ", strip=True).split()[0],
                r.find_all("td")[2].get_text(strip=True),
            ): r["data-code"]
            for r in soup.select("table[data-table=console] tbody tr")
        }

    admin = ui.soup("/admin")
    assert admin.select_one("[data-ledger-state]").get_text(strip=True) == "✓Running"
    assert admin.find("button", string="Stop the ledger")
    normal = run()
    assert normal == {
        ("ticket-triage-agent", "model-1"): "ALLOWED",
        ("reply-drafts-agent", "va-fast"): "ALLOWED",
        ("build-assistant-agent", "model-1"): "ALLOWED",
        ("log-summarizer-agent", "model-1"): "ALLOWED",
        ("research-agent", "model-1"): "APPROVAL_REQUIRED",
        ("ticket-triage-agent", "vb-large"): "VENDOR_BLOCKED",
        ("reply-drafts-agent", "vendor-a/model-3"): "MODEL_BLOCKED",
        ("call-notes-agent", "vendor-a/model-9"): "UNKNOWN_MODEL",
    }
    assert stop(ui).status_code == 303
    stopped = ui.soup("/admin")
    assert "Stopped" in stopped.select_one("[data-ledger-state]").get_text()
    assert stopped.find("button", string="Restore the ledger") and banner(ui, "/admin") is not None
    outage = run()
    assert outage == normal | {
        ("ticket-triage-agent", "model-1"): "FAIL_OPEN",  # soft path: continues, spooled
        ("reply-drafts-agent", "va-fast"): "FAIL_OPEN",  # monitor path: continues, spooled
        ("build-assistant-agent", "model-1"): "BUDGET_FAIL_CLOSED",  # hard limit: denied
        ("log-summarizer-agent", "model-1"): "BUDGET_FAIL_CLOSED",  # soft, but under hard limits
        ("research-agent", "model-1"): "BUDGET_FAIL_CLOSED",  # approval: denied
    }  # the three blocked or unknown models are refused exactly as before
    assert restore(ui).status_code == 303
    assert "Running" in ui.soup("/admin").select_one("[data-ledger-state]").get_text()
    assert len(ui.gw.rows("SELECT 1 FROM fail_events")) == 2  # replayed
    assert run() == normal


@pytest.mark.req("SEC-23", "TB-9 (CSRF)")
def test_demo_console_exists_only_in_demo_mode_and_refuses_cross_site(settings, engine, ui_traffic):
    assert stop(ui_traffic).status_code == 303
    restore(ui_traffic)
    assert ui_traffic.client.post("/admin/demo/ledger", data={"action": "stop"}).status_code == 403
    assert (
        ui_traffic.client.post(
            "/admin/demo/ledger", data={"action": "explode"}, headers=ORIGIN
        ).status_code
        == 422
    )
    off = make_ui(
        settings.model_copy(update={"demo_mode": False}),
        engine,
        gateway_client=ui_traffic.gw.client,
    )
    assert not off.soup("/admin").select("#console-title")
    assert (
        off.client.post("/admin/demo/ledger", data={"action": "stop"}, headers=ORIGIN).status_code
        == 404
    )
    assert off.client.post("/admin/demo/requests", headers=ORIGIN).status_code == 404
    assert not ui_traffic.gw.app.state.ledger_state.fault_injected


@pytest.mark.req("UX-10 (states)", "SEC-36")
def test_demo_console_says_so_when_the_gateway_does_not_answer(ui):
    response = ui.client.post("/admin/demo/ledger", data={"action": "stop"}, headers=ORIGIN)
    assert response.status_code == 502 and "The gateway did not answer" in response.text
    assert "Unknown" in ui.soup("/admin").select_one("[data-ledger-state]").get_text()
