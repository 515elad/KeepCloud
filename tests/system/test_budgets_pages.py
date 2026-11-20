"""Budgets page and budget detail (FR-04, UX-2, UX-8)."""

import re
import uuid

import pytest


def rows(ui):
    return ui.soup("/budgets").select("table[data-table=budgets] tbody tr")


def row_named(ui, name):
    return next(r for r in rows(ui) if r.find("a").get_text(strip=True) == name)


@pytest.mark.req("FR-04")
def test_hierarchy_lists_every_budget_in_tree_order(ui):
    all_rows = rows(ui)
    kinds = [r["data-scope-type"] for r in all_rows]
    assert (
        kinds.count("ORG"),
        kinds.count("DEPT"),
        kinds.count("TEAM"),
        kinds.count("PROJECT"),
    ) == (1, 3, 6, 12)
    assert kinds[0] == "ORG"
    depth = [int(re.search(r"depth-(\d)", " ".join(r.td["class"])).group(1)) for r in all_rows]
    assert [{"ORG": 0, "DEPT": 1, "TEAM": 2, "PROJECT": 3}[k] for k in kinds] == depth
    text = " ".join(r.get_text(" ") for r in all_rows)
    for word in (
        "USD",
        "EUR",
        "Month",
        "Quarter",
        "Independent",
        "Subdivision",
        "Monitor",
        "Soft limit",
        "Hard limit",
        "Approval",
    ):
        assert word in text


@pytest.mark.req("UX-2", "UX-D1")
def test_every_project_has_a_gateway_routed_badge_and_none_claims_enforced(ui):
    soup = ui.soup("/budgets")
    projects = soup.select("tr[data-scope-type=PROJECT]")
    assert len(projects) == 12
    for row in projects:
        badge = row.select_one(".cov")
        assert badge["data-coverage"] == "Gateway-routed"
        assert badge.select_one("[aria-hidden=true]") and badge.get_text(strip=True).endswith(
            "Gateway-routed"
        )
    assert not soup.select('[data-coverage="Enforced"]')
    assert soup.select_one('[data-pending="UX-D1"]')
    for row in soup.select("tr[data-budget-id]:not([data-scope-type=PROJECT])"):
        assert not row.select(".cov")


@pytest.mark.req("UX-8 (budget bar)")
def test_budget_bar_stacks_committed_and_reserved_with_four_ticks(ui):
    for row in rows(ui):
        bar = row.select_one("[data-bar]")
        assert [t["data-tick"] for t in bar.select(".bar__tick")] == ["50", "80", "90", "100"]
        segments = bar.select(".bar__seg")
        assert [s["data-seg"] for s in segments] == [
            "committed",
            "reserved",
        ]  # stacked in this order
        widths = [int(re.search(r"w-(\d+)", " ".join(s["class"])).group(1)) for s in segments]
        assert 0 <= sum(widths) <= 100  # remaining is the rest of the track
        assert re.search(
            r"[\d.]+% committed, [\d.]+% reserved", bar.select_one(".bar__text").get_text()
        )
    bar = row_named(ui, "Research Agent").select_one("[data-bar]")
    assert "w-40" in bar.select_one("[data-seg=committed]")["class"]
    assert "w-5" in bar.select_one("[data-seg=reserved]")["class"]
    assert not bar.select(".is-reached")
    reached = row_named(ui, "Engineering").select(".bar__tick.is-reached")
    assert [t["data-tick"] for t in reached] == ["50", "80", "90"]  # 91.20% used


@pytest.mark.req("UX-8")
def test_over_cap_budget_is_flagged_in_words_not_only_colour(ui):
    row = row_named(ui, "Call Notes")
    assert "bar--over" in row.select_one("[data-bar]")["class"]
    assert "Over cap by 1,080.00 USD" in row.get_text(" ", strip=True)
    assert row.select_one("[data-effective]").get_text(strip=True) == "No enforced limit"


@pytest.mark.req("FR-04 (effective remaining)", "UX-8 (subdivision warning)")
def test_effective_remaining_shows_the_limiting_parent_and_the_subdivision_warning(ui):
    agent = row_named(ui, "Research Agent")
    assert (
        agent.select_one("[data-effective]").get_text(" ", strip=True).startswith("10,550.00 USD")
    )
    assert agent.select_one("[data-limited-by]").get_text(strip=True) == "Limited by Engineering"
    own = row_named(ui, "Code Review Agent")
    assert own.select_one("[data-effective]").get_text(strip=True) == "4,500.00 USD"
    assert own.select_one("[data-limited-by]") is None
    warned = {
        r.find("a").get_text(strip=True)
        for r in rows(ui)
        if r.select_one("[data-subdivision-warning]")
    }
    assert warned == {"Engineering", "Agents", "Language Models"}
    warning = (
        row_named(ui, "Engineering")
        .select_one("[data-subdivision-warning]")
        .get_text(" ", strip=True)
    )
    assert "exceed this cap by 10,000.00 USD" in warning
    # The warning sits in the same cell as effective remaining (inline, UX-8).
    assert row_named(ui, "Engineering").select_one("[data-effective] [data-subdivision-warning]")


@pytest.mark.req("FR-04", "UX-1 (effective-remaining panel)")
def test_budget_detail_explains_the_path(ui):
    href = row_named(ui, "Research Agent").find("a")["href"]
    soup = ui.soup(href)
    assert soup.find("h1").get_text(strip=True) == "Research Agent"
    path = soup.select("table[data-table=path] tbody tr")
    assert [r.find("a").get_text(strip=True) for r in path] == [
        "Research Agent",
        "Agents",
        "Engineering",
        "Northwind Labs",
    ]
    binding = [r for r in path if r.has_attr("data-binding")]
    assert (
        len(binding) == 1
        and "Engineering" in binding[0].get_text()
        and "Lowest" in binding[0].get_text()
    )
    assert "No, it only reports" in path[3].get_text()
    assert (
        soup.select_one(
            "[data-kpi][data-field-id='budget.effective_remaining'] [data-effective]"
        ).get_text(strip=True)
        == "10,550.00 USD"
    )
    assert soup.select_one(".bar-large [data-bar]") and soup.select_one(".legend")
    assert soup.select_one(".cov")["data-coverage"] == "Gateway-routed"


@pytest.mark.req("FR-04")
def test_independent_budget_path_stops_at_itself(ui):
    soup = ui.soup(row_named(ui, "Call Notes").find("a")["href"])
    assert len(soup.select("table[data-table=path] tbody tr")) == 1


@pytest.mark.req("UX-1")
@pytest.mark.parametrize("bad", [str(uuid.UUID(int=5)), "not-a-uuid"])
def test_unknown_budget_is_a_404_page(ui, bad):
    soup = ui.soup(f"/budgets/{bad}", status=404)
    assert soup.find("h1").get_text() == "Page not found"


@pytest.mark.req("SEC-36", "UX-10 (states)")
def test_budget_pages_say_so_when_the_database_is_down(ui_db_down):
    # Without the database nobody can be signed in: every page is the outage page (503).
    soup = ui_db_down.soup("/budgets", status=503)
    assert "database cannot be reached" in soup.select_one(".notice--bad").get_text()
    assert not soup.select("table[data-table=budgets]")
    detail = ui_db_down.soup(f"/budgets/{uuid.UUID(int=5)}", status=503)
    assert "database cannot be reached" in detail.select_one(".notice--bad").get_text()
