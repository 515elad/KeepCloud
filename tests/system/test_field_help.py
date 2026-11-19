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
FIELD_SELECTOR = "th, label, input, select, textarea, [data-kpi]"
PARTS = ["unit", "source", "formula", "example", "range", "validation", "prd"]


def fields_on(soup: BeautifulSoup) -> list:
    return soup.select(FIELD_SELECTOR)


@pytest.mark.parametrize("path", ALL_PATHS)
def test_every_field_column_and_kpi_has_a_registry_entry_and_an_i_button(ui, path):
    soup = ui.soup(path)
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


def test_the_walk_actually_finds_fields(ui):
    seen = {el["data-field-id"] for p in ALL_PATHS for el in fields_on(ui.soup(p))}
    assert "health.status" in seen and "alert.code" in seen
    # Every registry entry is in use somewhere: no dead help text.
    assert seen == REGISTRY.ids()


def test_walk_fails_for_a_field_without_help():
    soup = BeautifulSoup("<table><tr><th>Orphan</th></tr></table>", "html.parser")
    assert [el.get("data-field-id") for el in fields_on(soup)] == [None]


def test_popover_shows_every_required_part(ui):
    soup = ui.soup("/")
    for popover in soup.select(".help[popover]"):
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
    soup = ui.soup("/")
    amount = soup.select_one('[data-field-id="demo.placeholder_amount"] dd').get_text(strip=True)
    assert amount == REGISTRY.get("demo.placeholder_amount").worked_example.result
    clock = soup.select_one('[data-field-id="demo.clock"] dd').get_text(strip=True)
    assert clock == REGISTRY.get("demo.clock").worked_example.result


def test_templates_do_not_hard_code_help_text():
    templates = "".join(p.read_text() for p in (REPO_ROOT / "ui" / "templates").glob("*.html"))
    for entry in REGISTRY.all():
        assert entry.meaning not in templates
        assert entry.validation not in templates
