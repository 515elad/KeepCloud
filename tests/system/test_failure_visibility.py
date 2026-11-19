"""Hard rule 5 / SEC-36: every failure path leaves a metric, an alert record and a UI row.

``INJECTORS`` must cover every code in FAILURE_CODES; the first test fails if a
new failure path is added without a test here.
"""

import pytest
from sqlalchemy import select

from keepair.failures import ALERT_FALLBACK_TOTAL, FAILURE_CODES, FAILURES_TOTAL
from keepair.schema import alerts
from tests.system.conftest import make_ui

pytestmark = pytest.mark.req("SEC-36", "FR-21", "Hard rule 5")


def inject_database_unreachable(settings, engine, unreachable_engine, monkeypatch):
    ui = make_ui(settings, unreachable_engine)
    assert ui.client.get("/budgets").status_code == 200
    return ui


def inject_unhandled_error(settings, engine, unreachable_engine, monkeypatch):
    ui = make_ui(settings, engine)

    def boom(*args, **kwargs):
        raise RuntimeError("secret-detail-that-must-not-leak")

    monkeypatch.setattr("keepair.web.app.read_health", boom)
    response = ui.client.get("/reports")
    assert response.status_code == 500
    assert "secret-detail" not in response.text
    assert "DEMO" in response.text
    monkeypatch.undo()
    return ui


INJECTORS = {
    "DATABASE_UNREACHABLE": inject_database_unreachable,
    "UNHANDLED_ERROR": inject_unhandled_error,
}


def test_every_registered_failure_code_has_an_injector():
    assert set(INJECTORS) == set(FAILURE_CODES)


@pytest.mark.parametrize("code", sorted(FAILURE_CODES))
def test_every_fail_path_emits_metric_alert_and_ui_row(
    code, settings, engine, unreachable_engine, monkeypatch
):
    ui = INJECTORS[code](settings, engine, unreachable_engine, monkeypatch)
    severity, component = FAILURE_CODES[code]

    # 1. Metric.
    assert ui.metrics.value(FAILURES_TOTAL, code=code) >= 1
    assert f'{FAILURES_TOTAL}{{code="{code}"}}' in ui.client.get("/metrics").text

    # 2 and 3. Alert record, shown as a row in the UI.
    row = ui.soup("/").select_one(f'table[data-table=alerts] tr[data-alert-code="{code}"]')
    assert row is not None, "no alert row in the UI"
    cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
    assert severity in cells[1] and cells[2] == code and cells[3] == component
    assert "secret-detail" not in cells[4]


def test_database_outage_shows_unknown_health_and_a_visible_notice(ui_db_down):
    soup = ui_db_down.soup("/")
    assert {c.get_text(strip=True) for c in soup.select(".health .status")} == {"?Unknown"}
    assert "database cannot be reached" in soup.select_one(".notice--bad").get_text()
    assert "Not loaded" in soup.select_one('[data-field-id="demo.clock"]').get_text()
    assert "Held in memory" in soup.select_one("tr[data-alert-code]").get_text()
    assert ui_db_down.metrics.value(ALERT_FALLBACK_TOTAL) >= 1


def test_alert_is_stored_in_the_database_when_it_is_reachable(settings, engine, monkeypatch):
    inject_unhandled_error(settings, engine, None, monkeypatch)
    with engine.connect() as conn:
        rows = conn.execute(select(alerts.c.code, alerts.c.severity, alerts.c.raised_at)).all()
    assert [(r.code, r.severity) for r in rows] == [("UNHANDLED_ERROR", "SEV3")]
    assert rows[0].raised_at.utcoffset() is not None


def test_alerts_held_during_an_outage_are_written_once_the_database_returns(
    settings, engine, unreachable_engine
):
    from datetime import timedelta

    from keepair.demo.seed import demo_clock
    from keepair.failures import AlertStore, FailureReporter
    from keepair.metrics import Metrics

    clock, metrics = demo_clock(), Metrics()
    store = AlertStore(unreachable_engine, clock, metrics)
    reporter = FailureReporter(store, metrics, clock)
    reporter.report("DATABASE_UNREACHABLE", "first")
    reporter.report("DATABASE_UNREACHABLE", "second")  # same failure: one row, latest text
    held = store.recent()
    assert [(a.message, a.held_in_memory) for a in held] == [("second", True)]
    assert metrics.value(FAILURES_TOTAL, code="DATABASE_UNREACHABLE") == 2

    store._engine = engine  # the database comes back
    clock.advance(timedelta(seconds=6))
    after = store.recent()
    assert [(a.message, a.held_in_memory) for a in after] == [("second", False)]
    assert store.recent() == after  # written once, not duplicated


def test_unregistered_failure_code_is_refused(ui):
    with pytest.raises(ValueError, match="unregistered failure code"):
        ui.client.app.state.reporter.report("MADE_UP", "x")
