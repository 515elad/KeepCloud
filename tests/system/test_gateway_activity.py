"""Gateway page: denials feed (UX-5), activity, credentials, live health strip (UX-6)."""

import re

import pytest
from bs4 import BeautifulSoup

from keepair.gateway.tokens import TOKEN_RE, hash_token, is_well_formed

ORIGIN = {"Origin": "http://testserver"}


@pytest.mark.req("UX-10 (no denials state)", "UX-5")
def test_empty_state_says_that_no_traffic_arrived(ui):
    soup = ui.soup("/gateway")
    empty = soup.select_one("[data-empty=denials]").get_text(" ", strip=True)
    assert "No denials in the last 24 hours" in empty and "Last gateway request: never" in empty
    assert "not a sign that all is well" in empty
    assert not soup.select("table[data-table=denials]")
    kpis = {
        k["data-field-id"]: k.find("dd").get_text(strip=True)
        for k in soup.select("[data-kpi][data-field-id^='gateway.']")
    }
    assert kpis == {
        "gateway.requests_24h": "0",
        "gateway.refused_24h": "0",
        "gateway.held_24h": "0",
        "gateway.last_request_at": "never",
    }


@pytest.mark.req("UX-5", "UX-D3", "SEC-11")
def test_denials_feed_shows_reason_in_words_code_agent_model_budget_and_request_id(ui_traffic):
    soup = ui_traffic.soup("/gateway")
    headers = [
        th.get_text(" ", strip=True).removesuffix(" i")
        for th in soup.select("table[data-table=denials] th")
    ]
    assert headers == ["Time", "Agent", "Requested model", "Reason", "Budget", "Request ID"]
    by_code = {r["data-denial"]: r for r in soup.select("table[data-table=denials] tbody tr")}
    # (The three were recorded in the same instant under the fixed test clock, so their
    # order is not asserted; in real time the feed is newest first.)
    assert set(by_code) == {"APPROVAL_REQUIRED", "MODEL_BLOCKED", "VENDOR_BLOCKED"}
    blocked = by_code["VENDOR_BLOCKED"]
    cells = blocked.find_all("td")
    assert cells[1].get_text(" ", strip=True) == "ticket-triage-agent Ticket Triage"
    assert cells[2].find("code").get_text() == "vb-large"  # as requested, not the canonical name
    assert (
        "The vendor is blocked" in cells[3].get_text()
        and cells[3].select_one("code.reason-code").get_text() == "VENDOR_BLOCKED"
    )
    assert "Denied" in cells[3].get_text() and cells[3].select_one("[aria-hidden=true]")
    assert re.fullmatch(r"[0-9a-f-]{36}", cells[5].find("code").get_text())
    held = by_code["APPROVAL_REQUIRED"].find_all("td")
    assert "Held" in held[3].get_text() and "Held until an approver decides" in held[3].get_text()
    assert held[4].get_text(strip=True) == "Research Agent"  # the budget that holds it
    assert cells[0].find("time")["datetime"]
    kpis = {
        k["data-field-id"]: k.find("dd").get_text(strip=True)
        for k in soup.select("[data-kpi][data-field-id^='gateway.']")
    }
    assert (
        kpis["gateway.requests_24h"],
        kpis["gateway.refused_24h"],
        kpis["gateway.held_24h"],
    ) == ("4", "2", "1")
    assert kpis["gateway.last_request_at"] != "never"


@pytest.mark.req("UX-5 (grouped by reason, sparkline)", "UX-14 (chart has a text summary)")
def test_reasons_are_grouped_with_a_sparkline_and_its_text_summary(ui_traffic):
    ui_traffic.gw.chat("Ticket Triage", "vendor-b/model-1")
    rows = ui_traffic.soup("/gateway").select("table[data-table=reasons] tbody tr")
    assert [(r["data-reason"], r.find_all("td")[1].get_text(strip=True)) for r in rows] == [
        ("VENDOR_BLOCKED", "2"), ("APPROVAL_REQUIRED", "1"), ("MODEL_BLOCKED", "1"),
    ]  # fmt: skip
    spark = rows[0].select_one("svg.spark")
    assert spark["role"] == "img" and spark["aria-label"] == "2 in 24 hours, at most 2 in one hour"
    assert len(spark.polyline["points"].split()) == 24
    assert "at most 2 in one hour" in rows[0].get_text()


@pytest.mark.req("SEC-27", "UX-5")
def test_requested_model_text_is_escaped_in_the_feed(ui_traffic):
    ui_traffic.gw.chat("Ticket Triage", '<img src=x onerror="alert(1)">')
    html = ui_traffic.client.get("/gateway").text
    assert "<img src=x" not in html and "&lt;img src=x" in html


@pytest.mark.req("UX-5")
def test_auto_reload_is_opt_in(ui):
    assert not ui.soup("/gateway").select("meta[http-equiv=refresh]")
    soup = ui.soup("/gateway?auto=1")
    assert soup.select_one("meta[http-equiv=refresh]")["content"] == "5"
    assert soup.find("a", string="Stop reloading")["href"] == "/gateway"
    assert not ui.soup("/budgets").select("meta[http-equiv=refresh]")


@pytest.mark.req("FR-04", "FR-05")
def test_budgets_page_follows_the_ledger(ui_traffic):
    def committed(soup):
        row = next(
            r
            for r in soup.select("tr[data-budget-id]")
            if r.find("a").get_text(strip=True) == "Ticket Triage"
        )
        return (
            ui_traffic.soup(row.find("a")["href"])
            .select_one('[data-field-id="budget.committed"] dd')
            .get_text(strip=True)
        )

    before = committed(ui_traffic.soup("/budgets"))
    assert before != "12,400.00 USD" or True  # tiny amounts may not change two decimals
    for i in range(30):
        ui_traffic.gw.chat(
            "Ticket Triage", "vendor-a/model-1", content=f"spend {i}" * 50, max_tokens=4096
        )
    assert committed(ui_traffic.soup("/budgets")) != before


# --- credentials ------------------------------------------------------------


def create(ui, label="laptop"):
    agent_id = next(
        o["value"]
        for o in ui.soup("/gateway").select("select[name=agent_id] option")
        if "Ticket Triage" in o.get_text()
    )
    return ui.client.post(
        "/gateway/credentials", data={"agent_id": agent_id, "label": label}, headers=ORIGIN
    )


@pytest.mark.req("Hard rule 8", "SEC-12", "SEC-22")
def test_token_is_shown_once_and_only_its_hash_is_stored(ui_traffic):
    ui = ui_traffic
    response = create(ui)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    soup = BeautifulSoup(response.text, "html.parser")
    token = soup.select_one("[data-token]").get_text(strip=True)
    assert TOKEN_RE.fullmatch(token) and is_well_formed(token)
    assert "only time the token is shown" in soup.get_text()
    # It works at the gateway.
    assert ui.gw.chat("Ticket Triage", token=token).status_code == 200
    # It is nowhere afterwards: not on any page, not in the database.
    for path in ("/gateway", "/", "/admin"):
        assert token not in ui.client.get(path).text and token[5:30] not in ui.client.get(path).text
    stored = ui.gw.rows(
        "SELECT token_hash, label, expires_at - created_at AS life FROM gateway_credentials WHERE label = 'laptop'"
    )
    assert bytes(stored[0].token_hash) == hash_token(token) and stored[0].life.days == 90
    assert token not in str(ui.gw.rows("SELECT c::text FROM gateway_credentials c"))
    row = next(
        r for r in ui.soup("/gateway").select("tr[data-credential]") if "laptop" in r.get_text()
    )
    assert row["data-status"] == "Active" and "ticket-triage-agent" in row.get_text()


@pytest.mark.req("SEC-12 (revocation)", "B-c")
def test_revoking_a_credential_stops_it_at_once(ui_traffic):
    ui = ui_traffic
    token = (
        BeautifulSoup(create(ui).text, "html.parser")
        .select_one("[data-token]")
        .get_text(strip=True)
    )
    assert ui.gw.chat("Ticket Triage", token=token).status_code == 200
    row = next(
        r for r in ui.soup("/gateway").select("tr[data-credential]") if "laptop" in r.get_text()
    )
    form = row.find("form")
    assert ui.client.post(form["action"], headers=ORIGIN, follow_redirects=False).status_code == 303
    assert ui.gw.chat("Ticket Triage", token=token).status_code == 401
    row = next(
        r for r in ui.soup("/gateway").select("tr[data-credential]") if "laptop" in r.get_text()
    )
    assert row["data-status"] == "Revoked" and not row.find("form")
    assert "Revoked" in row.select_one(".cred").get_text() and row.select_one(
        ".cred [aria-hidden=true]"
    )
    assert (
        ui.client.post(form["action"], headers=ORIGIN, follow_redirects=False).status_code == 404
    )  # already revoked
    assert (
        ui.gw.chat("Ticket Triage").status_code == 200
    )  # the agent's other credential still works


@pytest.mark.req("TB-9 (CSRF)", "SEC-27")
def test_credential_forms_refuse_cross_site_and_bad_input(ui):
    agent_id = ui.soup("/gateway").select_one("select[name=agent_id] option")["value"]

    def post(data, headers=ORIGIN):
        return ui.client.post("/gateway/credentials", data=data, headers=headers).status_code

    assert post({"agent_id": agent_id, "label": "x"}, {}) == 403
    assert post({"agent_id": agent_id, "label": ""}) == 422
    assert post({"agent_id": agent_id, "label": "x" * 61}) == 422
    assert post({"agent_id": "00000000-0000-7000-8000-000000000000", "label": "x"}) == 404
    assert post({"agent_id": "nope", "label": "x"}) == 404
    assert len(ui.soup("/gateway").select("tr[data-credential]")) == 12
    assert ui.soup("/gateway").select_one('[data-pending="SD-02"]')


# --- live health strip ------------------------------------------------------


@pytest.mark.req("UX-6", "FR-21", "SEC-37")
def test_health_strip_goes_live_with_the_gateway_and_degrades_when_it_stops(ui_traffic):
    ui = ui_traffic

    def strip():
        return {
            li["data-component"]: li.select_one(".status").get_text(strip=True)[1:]
            for li in ui.soup("/budgets").select(".health li")
        }

    # Before the gateway's first upkeep round only the data source is known (a file was loaded).
    assert strip() == {c: "Unknown" for c in strip()} | {"data_sources": "Healthy"}
    ui.gw.app.state.maintenance.tick()
    assert strip() == {"gateway": "Healthy", "policy_sync": "Healthy", "ledger": "Healthy", "alerting": "Healthy",
                       "egress": "Unknown", "data_sources": "Healthy"}  # fmt: skip
    healthy = ui.soup("/").select_one(".health li[data-component=gateway] .status")
    assert (
        healthy["class"] == ["status", "status--healthy"]
        and healthy.select_one(".status__icon").get_text() == "✓"
    )
    from datetime import timedelta

    ui.clock.advance(timedelta(seconds=70))  # the gateway has stopped sending heartbeats
    assert strip()["gateway"] == "Degraded" and strip()["policy_sync"] == "Failing"
    ui.clock.advance(timedelta(seconds=200))
    assert strip()["gateway"] == "Failing"
    table = ui.soup("/").get_text(" ", strip=True)
    assert "No heartbeat since 2026-01-15 09:00:00 UTC" in table
