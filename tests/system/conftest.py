from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import httpx
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from keepair import iam, totp
from keepair.clock import FixedClock
from keepair.demo.seed import demo_clock, demo_totp_secret
from keepair.metrics import Metrics
from keepair.rng import system_rng
from keepair.schema import users
from keepair.web.app import create_app
from keepair.web.pages import PAGES

ORIGIN = {"Origin": "http://testserver"}


@dataclass
class Ui:
    client: TestClient
    metrics: Metrics
    clock: FixedClock
    gw: object = None
    engine: object = None
    user: str | None = None

    def soup(self, path: str, status: int = 200) -> BeautifulSoup:
        response = self.client.get(path)
        assert response.status_code == status, f"{path}: {response.status_code}"
        return BeautifulSoup(response.text, "html.parser")

    def post(self, path: str, data: dict | None = None, **kwargs):
        """A form post from one of the site's own pages."""
        kwargs.setdefault("follow_redirects", False)
        return self.client.post(path, data=data or {}, headers=ORIGIN, **kwargs)

    def code(self) -> str:
        """A fresh authenticator code for the signed-in demo user.

        A code is accepted once, so each call first moves this UI's clock to the
        next 30-second step.
        """
        self.clock.advance(timedelta(seconds=totp.STEP_S))
        return totp.code(demo_totp_secret(self.user), self.clock.now())

    def sign_in(self, username: str) -> Ui:
        """Give this client a session, as if the user had signed in with both factors."""
        with self.engine.begin() as conn:
            user_id = conn.execute(
                select(users.c.id).where(users.c.username == username)
            ).scalar_one()
            token = iam.create_session(conn, self.clock, system_rng(), user_id)
        self.client.cookies.set(iam.COOKIE, token)
        self.user = username
        return self

    def as_user(self, username: str) -> Ui:
        """The same application seen by another signed-in person (a separate browser)."""
        client = TestClient(self.client.app, raise_server_exceptions=False)
        other = Ui(client, self.metrics, self.clock, self.gw, self.engine)
        return other.sign_in(username)

    def anonymous(self) -> Ui:
        client = TestClient(self.client.app, raise_server_exceptions=False)
        return Ui(client, self.metrics, self.clock, self.gw, self.engine)


def no_gateway() -> httpx.Client:
    """A gateway that does not answer, for tests of the UI on its own."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no gateway in this test")

    return httpx.Client(transport=httpx.MockTransport(refuse), base_url="http://gateway.test")


def make_ui(settings, engine, gateway_client=None, user: str | None = "alice.admin") -> Ui:
    """The UI, signed in as an administrator unless another user (or None) is named."""
    metrics, clock = Metrics(), demo_clock()
    app = create_app(
        settings, engine=engine, clock=clock, metrics=metrics,
        gateway_client=gateway_client or no_gateway(),
    )  # fmt: skip
    ui = Ui(TestClient(app, raise_server_exceptions=False), metrics, clock, engine=engine)
    if user:
        try:
            ui.sign_in(user)
        except SQLAlchemyError:
            pass  # the database of this test is unreachable: nobody can be signed in
    return ui


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
