"""The "i" information system: every field has help, and the help is true."""

import pytest
from bs4 import BeautifulSoup

from keepair.config import REPO_ROOT
from keepair.demo.seed import demo_clock
from keepair.formulas import FORMULAS
from keepair.help_registry import HelpRegistry
from tests.system.conftest import ALL_PATHS

pytestmark = pytest.mark.req("Information system (owner brief)", "UX-14")

REGISTRY = HelpRegistry.load(REPO_ROOT / "ui" / "help" / "field_help.yaml")
FIELD_SELECTOR = "th, label, input:not([type=hidden]), select, textarea, [data-kpi]"
PARTS = ["unit", "source", "formula", "example", "range", "validation", "prd"]


def fields_on(soup: BeautifulSoup) -> list:
    return soup.select(FIELD_SELECTOR)


def walk_paths(ui) -> list[str]:
    """Every page of the app: the navigation pages plus each detail and form page."""
    budget_links = [a["href"] for a in ui.soup("/budgets").select("table[data-table=budgets] a")]
    forms = [
        "/gateway/block?type=vendor&id=vendor-a",
        "/gateway/block?type=model&id=vendor-a/model-1",
    ]
    return [*ALL_PATHS, *budget_links, *forms]


def test_every_field_column_and_kpi_has_a_registry_entry_and_an_i_button(ui_traffic):
    ui = ui_traffic
    paths = walk_paths(ui)
    assert len(paths) == len(ALL_PATHS) + 22 + 2
    for path in paths:
        check_fields(ui.soup(path), path)


def test_pages_reached_only_by_post_also_have_help_on_every_field(ui):
    agent_id = ui.soup("/gateway").select_one("select[name=agent_id] option")["value"]
    response = ui.client.post(
        "/gateway/credentials",
        data={"agent_id": agent_id, "label": "walk"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    check_fields(soup, "POST /gateway/credentials")
    assert soup.select_one('[data-kpi][data-field-id="credential.token"]')


def check_fields(soup, path):
    for el in fields_on(soup):
        field_id = el.get("data-field-id")
        assert field_id, f"{path}: <{el.name}> has no field ID: {str(el)[:80]}"
        assert field_id in REGISTRY.ids(), f"{path}: '{field_id}' is not in the registry"
        scope = el if el.select_one(".info") else el.find_parent(["section", "div"])
        button = scope.select_one(f'.info[data-help-for="{field_id}"]')
        assert button is not None, f"{path}: no i button for '{field_id}'"
        assert button["aria-label"] == f"About {REGISTRY.get(field_id).name}"
        popover = soup.find(id=button["popovertarget"])
        assert popover is not None and popover.has_attr("popover")
        assert popover["data-help-id"] == field_id


def test_the_walk_actually_finds_fields(ui_traffic):
    ui = ui_traffic
    seen = {el["data-field-id"] for p in walk_paths(ui) for el in fields_on(ui.soup(p))}
    assert "health.status" in seen and "alert.code" in seen
    # Every registry entry is in use somewhere: no dead help text.
    # (credential.token is on a page reached by POST only; it has its own test.)
    assert seen == REGISTRY.ids() - {"credential.token"}


def test_walk_fails_for_a_field_without_help():
    soup = BeautifulSoup("<table><tr><th>Orphan</th></tr></table>", "html.parser")
    assert [el.get("data-field-id") for el in fields_on(soup)] == [None]


def test_popover_shows_every_required_part(ui_traffic):
    ui = ui_traffic
    popovers = [
        p
        for path in walk_paths(ui)[:9] + walk_paths(ui)[-2:]
        for p in ui.soup(path).select(".help[popover]")
    ]
    assert {p["data-help-id"] for p in popovers} == REGISTRY.ids() - {"credential.token"}
    for popover in popovers:
        entry = REGISTRY.get(popover["data-help-id"])
        assert popover.find("h2").get_text() == entry.name
        assert entry.meaning in popover.get_text()
        for part in PARTS:
            cell = popover.select_one(f'[data-help-part="{part}"]')
            assert cell is not None and cell.get_text(strip=True), f"{entry.id}: {part} is empty"
        assert entry.prd_ref in popover.select_one('[data-help-part="prd"]').get_text()


def test_registry_entries_are_complete():
    for entry in REGISTRY.all():
        assert entry.unit.strip(), f"{entry.id}: unit missing"
        if entry.source == "calculated":
            assert entry.formula and entry.formula_fn, f"{entry.id}: formula missing"
            assert entry.formula_fn in FORMULAS, f"{entry.id}: unknown formula function"


CALCULATED = [e for e in REGISTRY.all() if e.source == "calculated"]


@pytest.mark.parametrize("entry", CALCULATED, ids=lambda e: e.id)
def test_worked_example_matches_the_code_on_demo_data(engine, entry):
    with engine.connect() as conn:
        actual = FORMULAS[entry.formula_fn](conn, demo_clock())
    assert actual.inputs == entry.worked_example.inputs
    assert actual.result == entry.worked_example.result


def test_worked_example_check_catches_drift(engine):
    """If the demo data changes, the registry example must be seen to be wrong."""
    from keepair.health import record_heartbeat

    entry = REGISTRY.get("health.status")
    with engine.connect() as conn:
        record_heartbeat(conn, "gateway", demo_clock())
        actual = FORMULAS[entry.formula_fn](conn, demo_clock())
        conn.rollback()
    assert actual.result == "Healthy" != entry.worked_example.result


def test_displayed_values_match_the_worked_examples(ui):
    """The numbers in the help text are the numbers on the page."""
    example = REGISTRY.get
    assert ui.soup("/").select_one('[data-field-id="demo.clock"] dd').get_text(strip=True) == (
        example("demo.clock").worked_example.result
    )
    row = next(
        r
        for r in ui.soup("/budgets").select("tr[data-budget-id]")
        if "Research Agent" in r.get_text()
    )
    assert example("budget.effective_remaining").worked_example.result in row.get_text()
    assert example("budget.remaining").worked_example.result in row.get_text()
    detail = ui.soup(row.find("a")["href"])
    for field in (
        "budget.cap",
        "budget.committed",
        "budget.reserved",
        "budget.remaining",
        "budget.period",
    ):
        shown = detail.select_one(f'[data-kpi][data-field-id="{field}"] dd').get_text(
            " ", strip=True
        )
        assert shown == example(field).worked_example.result, field
    assert example("budget.usage").worked_example.result in detail.get_text()
    gateway = ui.soup("/gateway").get_text(" ", strip=True)
    for field in ("model.input_price", "model.output_price", "unregistered.first_seen_at"):
        assert example(field).worked_example.result in gateway, field


def test_templates_do_not_hard_code_help_text():
    templates = "".join(p.read_text() for p in (REPO_ROOT / "ui" / "templates").glob("*.html"))
    for entry in REGISTRY.all():
        assert entry.meaning not in templates
        assert entry.validation not in templates
