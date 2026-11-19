"""Vendor and model registry page: block cascade and the block action (FR-18, UX-3, UX-4)."""

import pytest
from sqlalchemy import func, select

from keepair.failures import FAILURES_TOTAL
from keepair.schema import registry_changes, vendors
from tests.system.conftest import make_ui

ORIGIN = {"Origin": "http://testserver"}
GOOD_REASON = "Security incident under investigation."


def model_rows(ui):
    return {r["data-model"]: r for r in ui.soup("/gateway").select("tr[data-model]")}


def post_block(ui, subject_type, subject_id, reason=GOOD_REASON, headers=ORIGIN):
    return ui.client.post(
        "/gateway/block",
        data={"type": subject_type, "id": subject_id, "reason": reason},
        headers=headers,
        follow_redirects=False,
    )


def assert_cascaded(row, vendor_id):
    """UX-3: lock, "Blocked by vendor X", disabled switch with the reason, never Allowed."""
    status = row.select_one("[data-status-cell]")
    assert row["data-effective-status"] == "BLOCKED_BY_VENDOR"
    assert f"Blocked by vendor {vendor_id}" in status.get_text(" ", strip=True)
    assert status.select_one("[aria-hidden=true]").get_text() == "🔒"
    assert not row.select(".reg--allowed")
    switch = row.select_one("button[role=switch]")
    assert switch.has_attr("disabled") and switch["aria-checked"] == "false"
    why = row.find(id=switch["aria-describedby"]).get_text(" ", strip=True)
    assert f"Controlled by vendor {vendor_id}" in why and "cannot be allowed" in why
    assert vendor_id in switch.find_parent(class_="switch-wrap")["title"]  # the tooltip
    assert not row.select("form")  # nothing to submit


@pytest.mark.req("UX-3", "FR-18", "SEC-05")
def test_cascade_rendering_for_models_of_a_blocked_vendor(ui):
    rows = model_rows(ui)
    assert_cascaded(rows["vendor-b/model-1"], "vendor-b")  # own setting allowed, still blocked
    assert_cascaded(rows["vendor-b/model-2"], "vendor-b")
    assert "allowed, overridden by the vendor block" in rows["vendor-b/model-1"].get_text(" ")
    assert rows["vendor-a/model-1"]["data-effective-status"] == "ALLOWED"
    assert rows["vendor-a/model-1"].select_one("button[role=switch]")["aria-checked"] == "true"
    blocked = rows["vendor-a/model-3"]
    assert blocked["data-effective-status"] == "BLOCKED" and "🔒" not in blocked.get_text()


@pytest.mark.req("UX-3", "FR-18")
def test_no_model_ever_renders_allowed_under_a_blocked_vendor(ui):
    """Checked for the seeded state and again after every vendor is blocked."""

    def check():
        soup = ui.soup("/gateway")
        blocked_vendors = {
            r["data-vendor"]
            for r in soup.select("tr[data-vendor]")
            if r.select_one(".reg--blocked")
        }
        for row in soup.select("tr[data-model]"):
            vendor = row.find_all("td")[1].get_text(strip=True)
            if vendor in blocked_vendors:
                assert_cascaded(row, vendor)
        return blocked_vendors

    assert check() == {"vendor-b"}
    assert post_block(ui, "vendor", "vendor-a").status_code == 303
    assert check() == {"vendor-a", "vendor-b"}
    assert not ui.soup("/gateway").select("tr[data-model] .reg--allowed")


@pytest.mark.req("UX-3 (last change shows who, when and why)")
def test_last_change_shows_who_when_and_why(ui):
    row = ui.soup("/gateway").select_one('tr[data-vendor="vendor-b"]')
    text = row.get_text(" ", strip=True)
    assert "2026-01-13 09:00:00 UTC" in text and "demo-admin" in text and "Contract review" in text
    assert row.find("time")["datetime"].startswith("2026-01-13T09:00:00")


@pytest.mark.req("FR-18 (lifting needs two administrators)", "SD-03", "UX-9 (disabled with reason)")
def test_lifting_a_block_is_shown_disabled_with_the_reason_and_has_no_route(ui):
    row = ui.soup("/gateway").select_one('tr[data-vendor="vendor-b"]')
    switch = row.select_one("button[role=switch]")
    assert switch.has_attr("disabled")
    why = row.find(id=switch["aria-describedby"])
    assert "two administrators" in why.get_text() and why.select_one('[data-pending="SD-03"]')
    for path in ("/gateway/unblock", "/gateway/lift", "/gateway/allow"):
        assert ui.client.post(
            path, data={"type": "vendor", "id": "vendor-b"}, headers=ORIGIN
        ).status_code in (404, 405)
    assert ui.client.get("/gateway/block?type=vendor&id=vendor-b").status_code == 200
    assert post_block(ui, "vendor", "vendor-b").status_code == 422  # already blocked: nothing to do


@pytest.mark.req("UX-4", "D-03")
def test_unregistered_is_a_separate_label_with_its_own_action(ui):
    soup = ui.soup("/gateway")
    row = soup.select_one('tr[data-unregistered="vendor-a/model-9"]')
    assert row.select_one(".reg--unregistered").get_text(strip=True) == "?Unregistered"
    assert not row.select(".reg--blocked, .reg--allowed")
    button = row.find("button")
    assert button.get_text(strip=True) == "Register model" and button.has_attr("disabled")
    assert "phase 2" in row.find(id=button["aria-describedby"]).get_text()
    assert not soup.select('tr[data-model="vendor-a/model-9"]')  # no registry row for unknown
    assert soup.select_one('[data-pending="D-03"]')


@pytest.mark.req("FR-18 (emergency block)", "UX-7 (impact preview)")
def test_block_flow_previews_impact_then_blocks_with_a_reason(ui, engine):
    switch_form = ui.soup("/gateway").select_one('tr[data-vendor="vendor-a"] form')
    assert switch_form["method"] == "get" and switch_form["action"] == "/gateway/block"
    confirm = ui.soup("/gateway/block?type=vendor&id=vendor-a")
    impact = [li.find("code").get_text() for li in confirm.select("[data-impact] li")]
    assert impact == ["vendor-a/model-1", "vendor-a/model-2", "vendor-a/model-3"]
    assert confirm.select_one("form[method=post] textarea[name=reason][required]")

    response = post_block(ui, "vendor", "vendor-a")
    assert response.status_code == 303 and response.headers["location"].startswith("/gateway")
    row = ui.soup("/gateway").select_one('tr[data-vendor="vendor-a"]')
    text = row.get_text(" ", strip=True)
    assert "Blocked" in text and "demo-operator" in text and GOOD_REASON in text
    with engine.connect() as conn:
        status = conn.execute(
            select(vendors.c.status).where(vendors.c.id == "vendor-a")
        ).scalar_one()
    assert status == "BLOCKED"


@pytest.mark.req("FR-18", "SEC-27")
@pytest.mark.parametrize("reason", ["", "too short", "x" * 301])
def test_block_without_a_valid_reason_changes_nothing(ui, engine, reason):
    response = post_block(ui, "model", "vendor-a/model-1", reason=reason)
    assert response.status_code == 422
    assert "Give a reason of 10 to 300 characters." in response.text
    assert 'aria-invalid="true"' in response.text
    assert model_rows(ui)["vendor-a/model-1"]["data-effective-status"] == "ALLOWED"
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(registry_changes)).scalar_one() == 3


@pytest.mark.req("TB-9 (CSRF)", "SEC-13")
@pytest.mark.parametrize(
    "headers", [{}, {"Origin": "http://evil.example"}, {"Referer": "http://evil.example/x"}]
)
def test_cross_site_form_post_is_refused(ui, headers):
    assert post_block(ui, "vendor", "vendor-a", headers=headers).status_code == 403
    assert not ui.soup("/gateway").select_one('tr[data-vendor="vendor-a"] .reg--blocked')


@pytest.mark.req("SEC-27 (output encoding)")
def test_reason_text_is_escaped_when_shown(ui):
    reason = '<script>alert("x")</script> <b>bold</b> reason'
    assert post_block(ui, "model", "vendor-a/model-2", reason=reason).status_code == 303
    html = ui.client.get("/gateway").text
    assert "<script>alert" not in html and "&lt;script&gt;alert" in html


@pytest.mark.req("SEC-28 (size limits)")
def test_oversized_form_is_refused(ui):
    assert post_block(ui, "vendor", "vendor-a", reason="x" * 5000).status_code == 413


@pytest.mark.req("UX-1")
@pytest.mark.parametrize(
    "query", ["type=vendor&id=nope", "type=budget&id=vendor-a", "type=model&id=vendor-a"]
)
def test_block_form_for_unknown_item_is_a_404(ui, query):
    ui.soup(f"/gateway/block?{query}", status=404)


@pytest.mark.req("SEC-36", "Hard rule 5")
def test_block_during_a_database_outage_fails_visibly_and_changes_nothing(
    settings, engine, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    ui = make_ui(settings, engine)

    def down(*args, **kwargs):
        raise OperationalError("UPDATE", {}, Exception("connection lost"))

    monkeypatch.setattr("keepair.web.app.add_block", down)
    response = post_block(ui, "vendor", "vendor-a")
    assert response.status_code == 503 and "Nothing was changed" in response.text
    assert "connection lost" not in response.text
    monkeypatch.undo()
    assert ui.metrics.value(FAILURES_TOTAL, code="DATABASE_UNREACHABLE") == 1
    ui.clock.advance(__import__("datetime").timedelta(seconds=6))
    assert ui.soup("/").select_one('tr[data-alert-code="DATABASE_UNREACHABLE"]')
    assert not ui.soup("/gateway").select_one('tr[data-vendor="vendor-a"] .reg--blocked')
