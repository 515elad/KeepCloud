from __future__ import annotations

from dataclasses import dataclass

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

    def soup(self, path: str, status: int = 200) -> BeautifulSoup:
        response = self.client.get(path)
        assert response.status_code == status, f"{path}: {response.status_code}"
        return BeautifulSoup(response.text, "html.parser")


def make_ui(settings, engine) -> Ui:
    metrics, clock = Metrics(), demo_clock()
    app = create_app(settings, engine=engine, clock=clock, metrics=metrics)
    return Ui(TestClient(app, raise_server_exceptions=False), metrics, clock)


@pytest.fixture
def ui(settings, engine) -> Ui:
    return make_ui(settings, engine)


@pytest.fixture
def ui_db_down(settings, unreachable_engine) -> Ui:
    return make_ui(settings, unreachable_engine)


ALL_PATHS = [p.path for p in PAGES]
