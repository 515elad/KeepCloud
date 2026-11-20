"""Spend and Reconciliation pages (FR-03, FR-06, FR-07, FR-19, UX-8)."""

import re

import pytest
from bs4 import BeautifulSoup

from keepair.demo import billing as demo
from tests.system.conftest import ALL_PATHS, upload

ORIGIN = {"Origin": "http://testserver"}


def totals(soup):
    return {
        k["data-state"]: k.find("dd").get_text(strip=True)
        for k in soup.select("[data-totals] [data-kpi]")
    }


def batch_counts(soup):
    """Rows, new, revised and unchanged of every batch in the ingestion history."""
    return [
        [td.get_text(strip=True) for td in row.find_all("td")][3:]
        for row in soup.select("table[data-table=batches] tbody tr")
    ]


def queue_rows(ui):
    return ui.soup("/spend").select("table[data-table=queue] tbody tr")


@pytest.mark.req("FR-07", "UX-10 (states)")
def test_before_any_upload_only_the_estimate_exists(ui):
    soup = ui.soup("/spend")
    assert totals(soup) == {
        "ESTIMATED": "182,373.32 USD",
        "PROVIDER_REPORTED": "No data",
        "INVOICED": "No data",
    }
    assert soup.select_one("[data-empty=allocation]") and soup.select_one("[data-empty=queue]")
    assert (
        "No billing file has been loaded" in soup.select_one("table[data-table=batches]").get_text()
    )
    assert (
        len(soup.select("figure.multiple")) == 3
    )  # the gateway's own estimates are already charted
    assert not soup.select(".chart__bar--provider_reported, .chart__bar--invoiced")
    recon = ui.soup("/reconciliation")
    assert (
        recon.select_one('[data-field-id="recon.difference"] dd').get_text(strip=True)
        == "No provider data"
    )
    assert (
        not recon.select("[data-uncontrolled]")
        and "Cannot tell without provider data" in recon.get_text()
    )


@pytest.mark.req("Owner brief phase 4 (demo)", "FR-01", "FR-03")
def test_upload_updates_totals_allocation_and_history(ui):
    assert upload(ui, demo.USAGE_FILE).status_code == 303
    soup = ui.soup("/spend")
    assert totals(soup) == {
        "ESTIMATED": "182,373.32 USD",
        "PROVIDER_REPORTED": "182,423.21 USD",
        "INVOICED": "No data",
    }
    table = soup.select_one("table[data-table=allocation]")
    assert table["data-state"] == "PROVIDER_REPORTED" and len(table.select("tbody tr")) == 12
    build = [
        td.get_text(" ", strip=True)
        for td in table.select_one('tr[data-project="Build Assistant"]').find_all("td")
    ]
    assert build == [
        "Build Assistant Platform",
        "21,915.33 USD",
        "10,755.86 USD",
        "0.00 USD",
        "32,671.20 USD",
    ]
    foot = {
        tr["data-total"]: tr.find_all("td")[-1].get_text(" ", strip=True)
        for tr in table.select("tfoot tr")
    }
    assert foot["unmatched"].startswith("42.50 USD") and foot["unallocated"].startswith("17.25 USD")
    assert foot["records"] == "182,423.21 USD 100.00%"
    shares = [
        float(re.search(r"([\d.]+)%", foot[k]).group(1))
        for k in ("allocated", "unmatched", "unallocated")
    ]
    assert abs(sum(shares) - 100) < 0.03  # allocated, unmatched and unallocated make up all of it
    [batch] = soup.select("table[data-table=batches] tbody tr")
    cells = [td.get_text(" ", strip=True) for td in batch.find_all("td")]
    assert batch["data-batch-status"] == "LOADED" and cells[1:] == [
        "vendor-a-usage-2026-01.csv vendor-a usage export",
        "✓ Loaded",
        "431",
        "431",
        "0",
        "0",
    ]

    assert upload(ui, demo.USAGE_FILE).status_code == 303  # the same file again
    again = ui.soup("/spend")
    assert totals(again) == totals(soup)  # nothing doubled
    counts = batch_counts(again)  # (both loads happened in the same instant of the test clock)
    assert sorted(counts) == [["431", "0", "0", "431"], ["431", "431", "0", "0"]]


@pytest.mark.req("Owner brief phase 4 (demo)", "FR-06", "FR-03 (unallocated buckets)")
def test_queue_shows_one_unmatched_one_unallocated_and_one_join_in_the_review_band(ui):
    upload(ui, demo.USAGE_FILE)
    rows = {r["data-queue-state"]: r for r in queue_rows(ui)}
    assert sorted(rows) == ["REVIEW", "UNALLOCATED", "UNMATCHED"] and len(queue_rows(ui)) == 3
    review = [td.get_text(" ", strip=True) for td in rows["REVIEW"].find_all("td")]
    assert "red-team" in review[0] and review[2] == "project=Red Team" and review[5] == "70"
    assert "To review" in review[4] and "no team" in review[4]
    assert rows["REVIEW"].select_one("option[selected]").get_text() == "Red Team"  # the suggestion
    assert rows["REVIEW"].find("button").get_text() == "Confirm"
    unmatched = rows["UNMATCHED"]
    assert (
        "project=shadow-experiment" in unmatched.get_text() and "42.50 USD" in unmatched.get_text()
    )
    assert unmatched.select_one("option").get_text() == "Choose a project"  # nothing is preselected
    assert unmatched.select_one(".fin")["data-finalization"] == "PROVIDER_REPORTED"
    assert (
        "No tags" in rows["UNALLOCATED"].get_text()
        and rows["UNALLOCATED"].find_all("td")[5].get_text(strip=True) == "0"
    )
    for row in rows.values():  # state is an icon and a word, never colour alone
        assert row.select_one(".qstate [aria-hidden=true]")


@pytest.mark.req("FR-03 (manual assignment)", "TB-9 (CSRF)")
def test_manual_assignment_moves_a_record_out_of_the_queue(ui):
    upload(ui, demo.USAGE_FILE)
    row = next(r for r in queue_rows(ui) if r["data-queue-state"] == "UNMATCHED")
    form = {"record_id": row.select_one("input[name=record_id]")["value"]}
    lead = next(o["value"] for o in row.select("option") if o.get_text() == "Lead Scoring")

    def post(data, headers=ORIGIN):
        response = ui.client.post(
            "/spend/assign", data=data, headers=headers, follow_redirects=False
        )
        return response.status_code

    assert post(form | {"project_id": lead, "reason": "Belongs to the growth pilot."}, {}) == 403
    assert post(form | {"project_id": lead, "reason": "short"}) == 422
    assert post(form | {"project_id": "", "reason": "Belongs to the growth pilot."}) == 404
    assert len(queue_rows(ui)) == 3
    assert post(form | {"project_id": lead, "reason": "Belongs to the growth pilot."}) == 303
    assert [r["data-queue-state"] for r in queue_rows(ui)] == ["REVIEW", "UNALLOCATED"]
    table = ui.soup("/spend").select_one("table[data-table=allocation]")
    cells = [
        td.get_text(" ", strip=True)
        for td in table.select_one('tr[data-project="Lead Scoring"]').find_all("td")
    ]
    assert cells[3] == "42.50 USD"  # the Manual column
    assert (
        table.select_one('tfoot tr[data-total="unmatched"]')
        .find_all("td")[-1]
        .get_text(" ", strip=True)
        .startswith("0.00 USD")
    )
    # Confirming the review join makes it manual too.
    review = queue_rows(ui)[0]
    confirm = {"record_id": review.select_one("input[name=record_id]")["value"],
               "project_id": review.select_one("option[selected]")["value"], "reason": "Confirmed with the team lead."}  # fmt: skip
    assert post(confirm) == 303 and [r["data-queue-state"] for r in queue_rows(ui)] == [
        "UNALLOCATED"
    ]


@pytest.mark.req("FR-07", "UX-8 (finalization chip, hatched estimates)")
def test_estimates_are_never_labelled_invoiced_on_any_page(ui):
    upload(ui, demo.USAGE_FILE), upload(ui, demo.INVOICE_FILE)
    for path in ("/", "/spend", "/reconciliation"):
        soup = ui.soup(path)
        shown = totals(soup)
        assert shown == {
            "ESTIMATED": "182,373.32 USD",
            "PROVIDER_REPORTED": "182,423.21 USD",
            "INVOICED": "92,457.80 USD",
        }
        for kpi in soup.select("[data-totals] [data-kpi]"):  # each total sits next to its own chip
            assert kpi.select_one(".fin")["data-finalization"] == kpi["data-state"]
            assert (
                kpi.select_one(".fin").get_text(strip=True)
                == {
                    "ESTIMATED": "Estimated",
                    "PROVIDER_REPORTED": "Provider-reported",
                    "INVOICED": "Invoiced",
                }[kpi["data-state"]]
            )
        assert "never added together" in soup.get_text()
        text = soup.get_text(" ", strip=True)
        for wrong in ("274,831.01", "274,881.01", "457,254.33"):  # no sum across states anywhere
            assert wrong not in text
    spend = ui.soup("/spend")
    estimated_bars = spend.select(".chart__bar--estimated")
    assert estimated_bars and all(b.get("fill") == "url(#hatch)" for b in estimated_bars)  # hatched
    assert spend.select_one("pattern#hatch") and not spend.select(
        '.chart__bar--invoiced[fill="url(#hatch)"]'
    )
    assert [t["data-state"] for t in spend.select("table[data-table=allocation]")] == [
        "PROVIDER_REPORTED",
        "INVOICED",
    ]


@pytest.mark.req("UX-8 (small multiples)", "UX-14 (chart has text summary and table view)")
def test_cost_explorer_has_one_chart_per_model_with_summary_and_table(ui):
    upload(ui, demo.USAGE_FILE), upload(ui, demo.INVOICE_FILE)
    charts = ui.soup("/spend").select("figure.multiple")
    assert [c["data-model"] for c in charts] == [
        "vendor-a/model-1",
        "vendor-a/model-2",
        "vendor-a/model-3",
    ]
    first = charts[0]
    svg = first.find("svg")
    assert svg["role"] == "img" and svg["aria-label"].startswith(
        "vendor-a/model-1. 2026-01-01 to 2026-01-14."
    )
    summary = first.select_one(".multiple__summary").get_text()
    assert (
        summary
        == "2026-01-01 to 2026-01-14. Estimated 117,193.46 USD, Provider-reported 117,223.51 USD, Invoiced 57,240.61 USD."
    )
    assert "UTC" in first.select_one(".multiple__axis").get_text()  # timezone on the axis
    rows = first.select("details table tbody tr")
    assert len(rows) == 14 and first.select_one("details summary").get_text() == "Show as table"
    assert (
        len(first.select(".chart__bar--estimated")) == 14
        and len(first.select(".chart__bar--invoiced")) == 7
    )
    assert len(charts[2].select(".chart__bar--estimated")) == 5  # model-3 was blocked on 6 January
    heights = [float(b["height"]) for c in charts for b in c.select(".chart__bar")]
    assert (
        max(heights) <= 80.0
        and max(float(b["height"]) for b in charts[2].select(".chart__bar")) < 20
    )  # one shared scale


@pytest.mark.req("FR-01 (corrected period)", "FR-07")
def test_correction_file_changes_the_total_once(ui):
    upload(ui, demo.USAGE_FILE)
    assert upload(ui, demo.CORRECTION_FILE).status_code == 303
    soup = ui.soup("/spend")
    assert totals(soup)["PROVIDER_REPORTED"] == "182,461.35 USD"
    assert ["2", "0", "2", "0"] in batch_counts(soup)
    upload(ui, demo.CORRECTION_FILE), upload(ui, demo.USAGE_FILE)
    assert totals(ui.soup("/spend"))["PROVIDER_REPORTED"] == "182,461.35 USD"


@pytest.mark.req("SEC-28", "SEC-27", "FR-02 (quarantine)")
def test_broken_file_is_refused_shown_and_loads_nothing(ui):
    response = upload(ui, demo.BROKEN_FILE)
    assert response.status_code == 422
    soup = BeautifulSoup(response.text, "html.parser")
    notice = soup.select_one("[data-upload-result=QUARANTINED]")
    reasons = [li.get_text() for li in notice.select("li")]
    assert reasons == ["Row 3, BilledCost: must be a number, zero or more.", "Row 4, ChargePeriodStart: is not an ISO 8601 time.",
                       "Row 5, Tags: is not JSON.", "Row 6, BilledCost: has more than 6 decimals."]  # fmt: skip
    assert "HYPERLINK" not in response.text  # cell content is not repeated
    after = ui.soup("/spend")
    assert totals(after)["PROVIDER_REPORTED"] == "No data"
    [batch] = after.select("table[data-table=batches] tbody tr")
    assert (
        batch["data-batch-status"] == "QUARANTINED"
        and "Refused" in batch.get_text()
        and len(batch.select(".reasons li")) == 4
    )
    hostile = upload(ui, "<script>alert(1)</script>.csv", data=b"<script>alert(2)</script>\n")
    assert (
        hostile.status_code == 422
        and "<script>alert" not in hostile.text
        and "&lt;script&gt;alert(1)" in hostile.text
    )


@pytest.mark.req("SEC-28 (size and type limits)", "TB-9 (CSRF)", "FR-07")
def test_upload_limits_and_source_rules(ui):
    assert (
        upload(ui, demo.USAGE_FILE, source="vendor-a-invoice").status_code == 422
    )  # wrong state for the source
    assert upload(ui, demo.USAGE_FILE, source="vendor-z").status_code == 422
    assert upload(ui, "big.csv", data=b"x" * (5 * 1024 * 1024 + 70_000)).status_code == 413
    files = {"file": (demo.USAGE_FILE, b"a,b\n", "text/csv")}
    assert (
        ui.client.post("/spend/upload", data={"source": "vendor-a-usage"}, files=files).status_code
        == 403
    )  # cross-site
    assert ui.client.post(
        "/spend/upload", data={"source": "vendor-a-usage"}, headers=ORIGIN
    ).status_code in (413, 422)
    assert totals(ui.soup("/spend"))["PROVIDER_REPORTED"] == "No data"


@pytest.mark.req(
    "FR-19", "UX-2 (coverage badge Uncontrolled)", "UX-8 (gateway-controlled share)", "B-b"
)
def test_uncontrolled_spend_shows_on_reconciliation_and_on_the_coverage_badge(ui):
    upload(ui, demo.USAGE_FILE)
    recon = ui.soup("/reconciliation")
    flagged = recon.select("tr[data-uncontrolled]")
    assert [r["data-project"] for r in flagged] == ["Lead Scoring"]
    cells = [td.get_text(" ", strip=True) for td in flagged[0].find_all("td")]
    assert cells[1:5] == ["2,400.00 USD", "3,120.00 USD", "0.00 USD", "+720.00 USD"]
    assert (
        cells[5] == "76.92%"
        and "Uncontrolled" in cells[6]
        and "720.00 USD more at the provider" in cells[6]
    )
    assert "w-76" in flagged[0].select_one(".share__fill")["class"]
    assert recon.select_one('[data-field-id="recon.findings"] dd').get_text(strip=True) == "1"
    assert (
        recon.select_one('[data-field-id="recon.difference"] dd').get_text(strip=True)
        == "+49.89 USD"
    )
    # A full match is never shown as 100%: the coverage badge cannot be Enforced in the MVP.
    full = recon.select_one('tr[data-project="Build Assistant"] [data-share]')
    assert "99% or more" in full.get_text() and "w-99" in full.select_one(".share__fill")["class"]
    assert "100.00%" not in recon.select_one("table[data-table=reconciliation]").get_text()
    badges = {
        r.find("a").get_text(strip=True): r.select_one(".cov")["data-coverage"]
        for r in ui.soup("/budgets").select("tr[data-scope-type=PROJECT]")
    }
    assert badges["Lead Scoring"] == "Uncontrolled" and set(badges.values()) == {
        "Uncontrolled",
        "Gateway-routed",
    }
    assert list(badges.values()).count("Uncontrolled") == 1
    assert ui.soup("/").select_one('tr[data-alert-code="UNCONTROLLED_SPEND"]')


@pytest.mark.req("UX-6", "FR-21", "v1.4 Section 6 (data freshness)")
def test_data_sources_turns_healthy_after_a_successful_load_only(ui):
    def status():
        return (
            ui.soup("/")
            .select_one(".health li[data-component=data_sources] .status")
            .get_text(strip=True)[1:]
        )

    assert status() == "Unknown"
    upload(ui, demo.BROKEN_FILE)
    assert status() == "Unknown"  # a refused file is not a sign of a working source
    upload(ui, demo.USAGE_FILE)
    assert status() == "Healthy"


@pytest.mark.req("FR-07", "UX-1")
def test_period_links_and_unknown_period(ui_traffic):
    """Live gateway traffic lands in another month; each month is its own page."""
    soup = ui_traffic.soup("/spend")
    assert (
        soup.select_one('[data-field-id="spend.period"] dd .num').get_text(strip=True) == "2026-01"
    )
    assert (
        ui_traffic.soup("/spend?period=1999-01")
        .select_one('[data-field-id="spend.period"] dd .num')
        .get_text(strip=True)
        == "2026-01"
    )
    assert ui_traffic.soup("/spend?period=nonsense").select_one("h1").get_text() == "Spend"
    for path in ALL_PATHS:
        assert ui_traffic.client.get(path).status_code == 200
