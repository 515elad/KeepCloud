from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from keepair.clock import FixedClock
from keepair.demo.seed import demo_clock
from keepair.metrics import Metrics
from keepair.web.app import create_app
from keepair.web.pages import PAGES


@dataclass
class Ui:
    client: TestClient
    metrics: Metrics
    clock: FixedClock
    gw: object = None

    def soup(self, path: str, status: int = 200) -> BeautifulSoup:
        response = self.client.get(path)
        assert response.status_code == status, f"{path}: {response.status_code}"
        return BeautifulSoup(response.text, "html.parser")


def no_gateway() -> httpx.Client:
    """A gateway that does not answer, for tests of the UI on its own."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no gateway in this test")

    return httpx.Client(transport=httpx.MockTransport(refuse), base_url="http://gateway.test")


def make_ui(settings, engine, gateway_client=None) -> Ui:
    metrics, clock = Metrics(), demo_clock()
    app = create_app(
        settings, engine=engine, clock=clock, metrics=metrics,
        gateway_client=gateway_client or no_gateway(),
    )  # fmt: skip
    return Ui(TestClient(app, raise_server_exceptions=False), metrics, clock)


@pytest.fixture
def ui(settings, engine) -> Ui:
    """The UI on the seeded demo data."""
    return make_ui(settings, engine)


@pytest.fixture
def ui_traffic(settings, engine) -> Ui:
    """The UI after a little gateway traffic of each kind."""
    from tests.gateway_harness import make_gateway

    gw = make_gateway(settings, engine)
    gw.chat("Ticket Triage", "vb-large")  # denied: vendor blocked
    gw.chat("Ticket Triage", "vendor-a/model-3")  # denied: model blocked
    gw.chat("Research Agent")  # held
    gw.chat("Ticket Triage", "va-fast")  # allowed
    ui = make_ui(settings, engine, gateway_client=gw.client)  # the UI talks to this gateway
    ui.gw = gw
    assert upload(ui, "vendor-a-usage-2026-01.csv").status_code == 303  # billing data is loaded too
    return ui


def upload(ui, name: str, source: str | None = None, data: bytes | None = None):
    """Upload a demo billing file through the Spend page's form, as a browser would."""
    from keepair.config import REPO_ROOT

    if data is None:
        data = (REPO_ROOT / "demo" / "billing" / name).read_bytes()
    source = source or ("vendor-a-invoice" if "invoice" in name else "vendor-a-usage")
    return ui.client.post(
        "/spend/upload",
        data={"source": source},
        files={"file": (name, data, "text/csv")},
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )


@pytest.fixture
def ui_db_down(settings, unreachable_engine) -> Ui:
    return make_ui(settings, unreachable_engine)


ALL_PATHS = [p.path for p in PAGES]
