"""A gateway wired to a respx-mocked provider. No network, no real provider (hard rule 1)."""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field

import httpx
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from keepair.config import Settings
from keepair.demo.seed import agent_name, demo_clock, demo_token
from keepair.gateway.app import create_gateway_app
from keepair.metrics import Metrics
from keepair.mockprovider.app import mock_usage
from keepair.rng import seeded_rng
from keepair.schema import budgets, org_units, projects

PROVIDER_URL = "http://mock-provider:8090/v1/chat/completions"
FIXTURES = Settings().fixtures_dir


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def mock_provider_answer(request: httpx.Request) -> httpx.Response:
    """What the mock provider server would answer (same template, same usage rule)."""
    body = json.loads(request.content)
    prompt_tokens, completion_tokens = mock_usage(body.get("messages"), body.get("max_tokens"))
    answer = copy.deepcopy(fixture("chat_completion.json"))
    answer["model"] = body["model"]
    answer["usage"] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    return httpx.Response(200, json=answer)


@dataclass
class Gw:
    client: TestClient
    app: object
    engine: object
    metrics: Metrics
    clock: object
    router: respx.Router
    provider: respx.Route
    counter: list = field(default_factory=lambda: [0])

    @property
    def gateway(self):
        return self.app.state.gateway

    def chat(self, project="Build Assistant", model="model-1", *, key=None, max_tokens=256,
             content="hello", headers=None, token=None, path="/v1/chat/completions", body=None):  # fmt: skip
        self.counter[0] += 1
        all_headers = {
            "Authorization": f"Bearer {token or demo_token(agent_name(project))}",
            "Idempotency-Key": key or f"test-{self.counter[0]}-{uuid.uuid4()}",
        }
        all_headers.update(headers or {})
        all_headers = {k: v for k, v in all_headers.items() if v is not None}
        if body is None:
            body = {
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": max_tokens,
            }
        if isinstance(body, bytes | str):
            return self.client.post(
                path, content=body, headers={**all_headers, "Content-Type": "application/json"}
            )
        return self.client.post(path, json=body, headers=all_headers)

    def budget(self, name: str):
        with self.engine.connect() as conn:
            scope = (
                conn.execute(
                    select(projects.c.id).where(projects.c.name == name)
                ).scalar_one_or_none()
                or conn.execute(select(org_units.c.id).where(org_units.c.name == name)).scalar_one()
            )
            return conn.execute(select(budgets).where(budgets.c.scope_id == scope)).one()

    def rows(self, sql: str, **params):
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params).all()

    def execute(self, sql: str, **params):
        with self.engine.begin() as conn:
            conn.execute(text(sql), params)


def make_gateway(settings, engine, *, clock=None, timeout_s: float = 120.0) -> Gw:
    router = respx.Router(assert_all_called=False)
    provider = router.post(PROVIDER_URL).mock(side_effect=mock_provider_answer)
    http = httpx.Client(transport=httpx.MockTransport(router.handler))
    metrics, clock = Metrics(), clock or demo_clock()
    app = create_gateway_app(
        settings.model_copy(update={"provider_timeout_s": timeout_s}),
        engine=engine, clock=clock, metrics=metrics, rng=seeded_rng(99), http=http,
        run_maintenance=False,
    )  # fmt: skip
    return Gw(
        TestClient(app, raise_server_exceptions=False),
        app,
        engine,
        metrics,
        clock,
        router,
        provider,
    )
