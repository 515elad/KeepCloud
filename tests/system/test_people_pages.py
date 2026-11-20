"""Owners, approvals, two-person actions, users and the kill switch, through the pages (phase 5)."""

from datetime import timedelta

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from keepair.schema import budgets, kill_switches, users, vendors

REASON = "Agreed in the weekly review."


def row_text(row) -> str:
    return row.get_text(" ", strip=True)


def budget_href(ui, name: str) -> str:
    for row in ui.soup("/budgets").select("tr[data-budget-id]"):
        if row.find("a").get_text() == name:
            return row.find("a")["href"]
    raise AssertionError(name)


def held_row(ui):
    [row] = ui.soup("/approvals").select("tr[data-held]")
    return row


# --- Held requests (FR-11, UX-11, UX-D2) ---------------------------------------------


@pytest.mark.req("FR-11", "UX-11", "UX-D2", "D-07")
def test_held_queue_shows_metadata_impact_expiry_and_what_approving_does(ui_traffic):
    ui = ui_traffic
    page = ui.soup("/approvals")
    section = page.find(id="held-title").find_parent("section")
    assert "Approving allows one matching resubmission within 15 minutes" in row_text(section)
    assert section.select_one('[data-pending="D-07"]') and section.select_one(
        '[data-pending="UX-D2"]'
    )
    row = held_row(ui)
    cells = [row_text(td) for td in row.find_all("td")]
    assert cells[1] == "research-agent Research Agent" and cells[2] == "vendor-a/model-1"
    assert cells[3].endswith("USD Reserved, not spent")
    assert cells[4] == "Research Agent" and "USD After this hold" in cells[5]
    assert "2026" in cells[6] and "Hold ends" in cells[6]
    approve = row.select_one("button[value=approve]")
    assert approve.get_text() == "Approve one resubmission"
    assert "one matching resubmission within 15 minutes" in approve["aria-label"]
    assert "hello" not in str(page)  # the request text is not stored or shown (D-07)


@pytest.mark.req("FR-11", "UX-D2")
def test_approve_then_the_same_request_goes_through_once(ui_traffic):
    ui = ui_traffic
    row = held_row(ui)
    done = ui.post(f"/approvals/held/{row['data-held']}", {"decision": "approve", "note": "ok"})
    assert done.status_code == 303 and done.headers["location"] == "/approvals#held-title"
    waiting = held_row(ui)
    assert waiting["data-held-state"] == "APPROVED"
    assert "Waiting for the agent to send the same request again" in row_text(waiting)
    assert "Resubmission window ends" in row_text(waiting) and not waiting.select("form")
    [decision] = ui.soup("/approvals").select("table[data-table=decisions] tbody tr")
    assert "Held request" in row_text(decision) and "Approved alice.admin" in row_text(decision)

    assert ui.gw.chat("Research Agent").status_code == 200  # the same request again
    assert not ui.soup("/approvals").select("tr[data-held]")
    assert ui.gw.chat("Research Agent").status_code == 202  # a third time is held again


@pytest.mark.req("FR-11 (requester cannot approve own request)", "UX-11 (disabled with a reason)")
def test_self_approval_is_disabled_with_a_reason_and_refused_if_forced(ui_traffic):
    omar = ui_traffic.as_user("omar.owner")  # owns the Research Agent budget
    row = held_row(omar)
    button = row.find("button")
    assert button.has_attr("disabled") and not row.select("form")
    why = row.find(id=button["aria-describedby"])
    assert "your own project" in why.get_text()
    forced = omar.post(f"/approvals/held/{row['data-held']}", {"decision": "approve"})
    assert forced.status_code == 403 and "your own project" in forced.text
    assert held_row(omar)["data-held-state"] == "HELD"

    ava = ui_traffic.as_user("ava.auditor")  # read-only role
    assert held_row(ava).find("button").has_attr("disabled")
    assert (
        ava.post(f"/approvals/held/{row['data-held']}", {"decision": "approve"}).status_code == 403
    )
    fiona = ui_traffic.as_user("fiona.finance")  # owns the Agents team budget above it
    assert held_row(fiona).select_one("button[value=approve]")
    rejected = fiona.post(f"/approvals/held/{row['data-held']}", {"decision": "reject"})
    assert rejected.status_code == 303 and not fiona.soup("/approvals").select("tr[data-held]")


# --- Two-person lift of a block (FR-18, SEC-07, SEC-15, UX-11) -----------------------


@pytest.mark.req("SEC-07", "SEC-15", "UX-11", "SD-03")
def test_block_lift_needs_a_second_administrator_through_the_pages(ui, engine):
    alice, bob = ui, ui.as_user("bob.admin")
    link = alice.soup("/gateway").select_one('tr[data-vendor="vendor-b"] a[data-lift]')
    form_page = alice.soup(link["href"])
    assert "second administrator approves within 24 hours" in row_text(form_page)
    assert form_page.select_one('[data-pending="SD-03"]')
    assert form_page.select_one("[data-eligible]").get_text(strip=True) == "bob.admin"
    short = alice.post("/gateway/lift", {"type": "vendor", "id": "vendor-b", "reason": "no",
                                         "totp": alice.code()})  # fmt: skip
    assert short.status_code == 422 and "Give a reason of 10 to 300 characters." in short.text
    asked = alice.post("/gateway/lift", {"type": "vendor", "id": "vendor-b", "reason": REASON,
                                         "totp": alice.code()})  # fmt: skip
    assert asked.status_code == 303 and asked.headers["location"] == "/approvals#pending-title"

    # The requester sees "pending second approver", the expiry and who is eligible.
    [mine] = alice.soup("/approvals").select("tr[data-pending-id]")
    text = row_text(mine)
    assert "Lift a block" in text and "Lift the block on vendor vendor-b" in text
    assert "Pending second approver" in text and "you cannot approve it" in text
    assert "2026-01-16" in text and "bob.admin" in text and REASON in text
    assert not mine.select("button[value=approve]")
    forced = alice.post(f"/approvals/{mine['data-pending-id']}/decide",
                        {"decision": "approve", "totp": alice.code()})  # fmt: skip
    assert forced.status_code == 403 and "different administrator" in forced.text
    waiting = alice.soup("/gateway").select_one('tr[data-vendor="vendor-b"] [data-awaiting]')
    assert "Awaiting second approver" in waiting.get_text()

    # The second administrator: a different person, with a fresh code.
    [theirs] = bob.soup("/approvals").select("tr[data-pending-id]")
    assert theirs.select_one("button[value=approve]") and theirs.select_one("input[name=totp]")
    no_code = bob.post(f"/approvals/{theirs['data-pending-id']}/decide", {"decision": "approve"})
    assert no_code.status_code == 403 and "Authenticator code not accepted" in no_code.text
    with engine.connect() as conn:
        assert conn.execute(
            select(vendors.c.status).where(vendors.c.id == "vendor-b")
        ).scalar_one() == "BLOCKED"  # fmt: skip
    approved = bob.post(f"/approvals/{theirs['data-pending-id']}/decide",
                        {"decision": "approve", "totp": bob.code()})  # fmt: skip
    assert approved.status_code == 303
    row = bob.soup("/gateway").select_one('tr[data-vendor="vendor-b"]')
    assert "Allowed" in row_text(row) and "alice.admin + bob.admin" in row_text(row)
    assert not bob.soup("/approvals").select("tr[data-pending-id]")
    [decided] = bob.soup("/approvals").select("table[data-table=decisions] tbody tr")
    assert "Lift a block" in row_text(decided) and "Approved bob.admin" in row_text(decided)


@pytest.mark.req("UX-11", "SEC-15")
def test_requester_can_cancel_and_other_roles_cannot_decide(ui):
    ui.post("/gateway/lift", {"type": "model", "id": "vendor-a/model-3", "reason": REASON,
                              "totp": ui.code()})  # fmt: skip
    [row] = ui.soup("/approvals").select("tr[data-pending-id]")
    fiona = ui.as_user("fiona.finance")
    [seen] = fiona.soup("/approvals").select("tr[data-pending-id]")
    assert "Only an administrator can decide this" in row_text(seen) and not seen.select("form")
    assert fiona.post(f"/approvals/{row['data-pending-id']}/decide",
                      {"decision": "approve"}).status_code == 403  # fmt: skip
    assert ui.post(f"/approvals/{row['data-pending-id']}/cancel").status_code == 303
    assert not ui.soup("/approvals").select("tr[data-pending-id]")
    assert "Cancelled by the requester" in row_text(ui.soup("/approvals"))
    model = ui.soup("/gateway").select_one('tr[data-model="vendor-a/model-3"]')
    assert model["data-effective-status"] == "BLOCKED" and model.select_one("a[data-lift]")


# --- Kill switch (FR-22, UX-7) --------------------------------------------------------


@pytest.mark.req("FR-22", "UX-7", "SEC-08")
def test_kill_switch_preview_activation_indicator_and_two_person_off(ui_traffic, engine):
    alice, bob, gw = ui_traffic, ui_traffic.as_user("bob.admin"), ui_traffic.gw
    admin = alice.soup("/admin")
    form = admin.select_one('form[action="/admin/kill-switch"]')
    assert form["method"] == "get"  # the first step only previews
    options = [o["value"] for o in form.select("option")]
    assert options[0] == "GLOBAL:" and "VENDOR:vendor-a" in options and len(options) == 15
    preview = alice.soup("/admin/kill-switch?scope=GLOBAL:")
    impact = {
        k["data-field-id"]: k.find("dd").get_text()
        for k in preview.select("[data-impact] [data-kpi]")
    }
    assert impact == {"kill.impact_projects": "12", "kill.impact_agents": "12",
                      "kill.impact_requests": "4"}  # fmt: skip
    assert "KILL_SWITCH" in row_text(preview) and "within 5 seconds" in row_text(preview)
    assert not alice.soup("/").select_one("[data-kill-band]")  # previewing switched nothing on
    alice.soup("/admin/kill-switch?scope=VENDOR:nope", status=404)

    on = alice.post("/admin/kill-switch", {"scope": "GLOBAL:", "reason": REASON,
                                           "totp": alice.code()})  # fmt: skip
    assert on.status_code == 303 and on.headers["location"] == "/admin#kill-title"
    for path in ("/", "/budgets", "/gateway", "/approvals", "/audit-log"):
        band = alice.soup(path).select_one("[data-kill-band]")
        assert band["role"] == "alert" and "All traffic" in band.get_text()
    gw.clock.advance(timedelta(seconds=5))
    refused = gw.chat("Ticket Triage", "va-fast")
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "KILL_SWITCH"
    feed = alice.soup("/gateway").select_one('tr[data-denial="KILL_SWITCH"]')
    assert "A kill switch is on for this traffic" in row_text(feed)
    again = alice.post("/admin/kill-switch", {"scope": "GLOBAL:", "reason": REASON,
                                              "totp": alice.code()})  # fmt: skip
    assert again.status_code == 422 and "already on" in again.text

    [active] = alice.soup("/admin").select("tr[data-kill]")
    assert "All traffic" in row_text(active) and "alice.admin" in row_text(active)
    off = alice.post(f"/admin/kill-switch/{active['data-kill']}/off",
                     {"reason": REASON, "totp": alice.code()})  # fmt: skip
    assert off.status_code == 303 and off.headers["location"] == "/approvals#pending-title"
    [active] = alice.soup("/admin").select("tr[data-kill]")
    assert "Awaiting second approver" in active.select_one("[data-awaiting]").get_text()
    assert alice.soup("/").select_one("[data-kill-band]")  # still on
    [pending] = bob.soup("/approvals").select("tr[data-pending-id]")
    assert "Switch a kill switch off" in row_text(pending)
    assert bob.post(f"/approvals/{pending['data-pending-id']}/decide",
                    {"decision": "approve", "totp": bob.code()}).status_code == 303  # fmt: skip
    assert not bob.soup("/").select_one("[data-kill-band]")
    [past] = bob.soup("/admin").select("table[data-table=kill-history] tbody tr")
    assert "alice.admin + bob.admin" in row_text(past)
    gw.clock.advance(timedelta(seconds=5))
    assert gw.chat("Ticket Triage", "va-fast").status_code == 200
    with engine.connect() as conn:
        assert conn.execute(select(kill_switches.c.deactivated_at)).scalar_one() is not None


# --- Owners (FR-17) -------------------------------------------------------------------


@pytest.mark.req("FR-17", "UX-8 (unowned bucket)")
def test_owner_is_shown_and_unowned_spend_is_a_bucket_on_overview(ui):
    rows = {r.find("a").get_text(): r for r in ui.soup("/budgets").select("tr[data-budget-id]")}
    assert rows["Research Agent"].select_one("[data-owner]").get_text() == "Omar Haddad"
    assert rows["Call Notes"].select_one("[data-owner]").get_text(strip=True) == "?Unowned"
    home = ui.soup("/")
    assert home.select_one("[data-unowned-spend]").get_text() == "11,971.30 USD"
    assert home.select_one("[data-unowned-count]").get_text() == "4"
    section = home.find(id="unowned-title").find_parent("section")
    assert section.select_one("[data-finalization]")["data-finalization"] == "ESTIMATED"
    assert [a.get_text() for a in section.select("[data-unowned-list] a")] == [
        "Benchmark Runs", "Call Notes", "Evaluation", "Sales Assist",
    ]  # fmt: skip


@pytest.mark.req("FR-17 (owner required before a hard limit)", "FR-04")
def test_hard_limit_needs_an_owner_through_the_pages(ui, engine):
    href = budget_href(ui, "Call Notes")
    page = ui.soup(href)
    assert page.select_one("dd[data-owner]").get_text(strip=True) == "?Unowned"
    refused = ui.post(f"{href}/policy", {"policy": "HARD", "reason": REASON, "totp": ui.code()})
    assert refused.status_code == 409
    assert "cannot be switched on without an active owner" in refused.text
    assert "Nothing was changed" in refused.text
    bob = next(o["value"] for o in page.select("select[name=user_id] option")
               if "bob.admin" in o.get_text())  # fmt: skip
    assigned = ui.post(f"{href}/owner", {"user_id": bob, "reason": REASON, "totp": ui.code()})
    assert assigned.status_code == 303 and assigned.headers["location"].startswith(href)
    assert ui.soup(href).select_one("dd[data-owner]").get_text() == "Bob Lindqvist"
    assert ui.post(f"{href}/policy", {"policy": "HARD", "reason": REASON,
                                      "totp": ui.code()}).status_code == 303  # fmt: skip
    after = ui.soup(href)
    assert "Hard limit" in after.select_one('[data-field-id="budget.policy"] dd').get_text()
    assert ui.soup("/").select_one("[data-unowned-count]").get_text() == "3"
    # "No owner" is not offered for a hard limit, and changing its owner waits for bob.
    assert "" not in [o["value"] for o in after.select("select[name=user_id] option")]
    alice_id = next(o["value"] for o in after.select("select[name=user_id] option")
                    if "alice.admin" in o.get_text())  # fmt: skip
    change = ui.post(f"{href}/owner", {"user_id": alice_id, "reason": REASON, "totp": ui.code()})
    assert change.headers["location"] == "/approvals#pending-title"
    assert "Awaiting second approver" in ui.soup(href).select_one("[data-awaiting]").get_text()
    with engine.connect() as conn:
        owner = conn.execute(
            select(users.c.username)
            .select_from(budgets.join(users, users.c.id == budgets.c.owner_user_id))
            .where(budgets.c.policy == "HARD", budgets.c.cap_micros == 6_000_000_000)
        ).scalar_one()
    assert owner == "bob.admin"  # unchanged until the second administrator confirms


@pytest.mark.req("FR-13", "FR-17")
def test_other_roles_see_no_owner_or_policy_forms(ui):
    fiona = ui.as_user("fiona.finance")
    page = fiona.soup(budget_href(fiona, "Call Notes"))
    assert not page.select('form[action$="/owner"], form[action$="/policy"]')
    assert "Only an administrator can change the owner or the policy" in row_text(page)


# --- Users (FR-13) ---------------------------------------------------------------------


@pytest.mark.req("FR-13 (local accounts)", "Hard rule 8 (shown once)")
def test_add_a_user_shows_the_sign_in_details_once(ui, engine):
    table = ui.soup("/admin").select("tr[data-user-row]")
    assert [r["data-user-row"] for r in table] == [
        "alice.admin", "ava.auditor", "bob.admin", "fiona.finance", "omar.owner",
    ]  # fmt: skip
    mine = next(r for r in table if r["data-user-row"] == "alice.admin")
    assert "You cannot disable or reset your own account" in row_text(mine)
    assert (
        next(r for r in table if r["data-user-row"] == "omar.owner").find_all("td")[4].get_text()
        == "5"
    )

    bad = ui.post("/admin/users", {"username": "X!", "display_name": "N", "role": "FINANCE",
                                   "totp": ui.code()})  # fmt: skip
    assert bad.status_code == 422 and "A user name is 3 to 40 characters" in bad.text
    made = ui.post("/admin/users", {"username": "nina.new", "display_name": "Nina <b>New</b>",
                                    "role": "ENGINEERING", "totp": ui.code()})  # fmt: skip
    assert made.status_code == 200 and made.headers["cache-control"] == "no-store"
    soup = BeautifulSoup(made.text, "html.parser")
    password = soup.select_one("[data-initial-password]").get_text()
    secret = soup.select_one("[data-totp-secret]").get_text()
    assert len(password) == 20 and len(secret) == 32
    listing = ui.client.get("/admin").text
    assert password not in listing and secret not in listing  # never shown again
    assert "Nina &lt;b&gt;New&lt;/b&gt;" in listing and "<b>New</b>" not in listing
    with engine.connect() as conn:
        row = conn.execute(select(users).where(users.c.username == "nina.new")).one()
    assert password not in row.password_hash and secret.encode() not in bytes(row.totp_secret_enc)

    # The new person can sign in with what was shown.
    import base64

    from keepair import totp

    visitor = ui.anonymous()
    assert visitor.post("/login", {"username": "nina.new", "password": password}).status_code == 303
    raw = base64.b32decode(secret)
    assert visitor.post("/login/code", {"totp": totp.code(raw, ui.clock.now())}).status_code == 303
    assert "Nina" in visitor.soup("/").select_one("form.userbar").get_text()


@pytest.mark.req("FR-13 (local-account lifecycle)", "SEC-17", "FR-17")
def test_disable_enable_and_reset_through_the_pages(ui):
    def user_id(name):
        row = next(r for r in ui.soup("/admin").select("tr[data-user-row]")
                   if r["data-user-row"] == name)  # fmt: skip
        return row.find("form")["action"].split("/")[3], row

    ava_id, _ = user_id("ava.auditor")
    ava = ui.as_user("ava.auditor")
    assert ava.client.get("/admin").status_code == 200
    assert ui.post(f"/admin/users/{ava_id}/status", {"status": "DISABLED",
                                                    "totp": ui.code()}).status_code == 303  # fmt: skip
    assert ava.client.get("/admin", follow_redirects=False).status_code == 303  # signed out at once
    _, row = user_id("ava.auditor")
    assert row["data-active"] == "no" and "Disabled" in row_text(row)
    assert ui.post(f"/admin/users/{ava_id}/status", {"status": "ACTIVE",
                                                    "totp": ui.code()}).status_code == 303  # fmt: skip
    reset = ui.post(f"/admin/users/{ava_id}/reset", {"totp": ui.code()})
    assert reset.status_code == 200 and "data-initial-password" in reset.text

    bob_id, _ = user_id("bob.admin")  # owns hard-limit budgets
    kept = ui.post(f"/admin/users/{bob_id}/status", {"status": "DISABLED", "totp": ui.code()})
    assert kept.status_code == 409 and "owns a hard-limit budget" in kept.text
    # An auditor sees the page but gets no forms.
    auditor = ui.as_user("omar.owner")
    assert auditor.client.get("/admin").status_code == 403
