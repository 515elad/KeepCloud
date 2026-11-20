"""Deterministic demo data (hard rule 2).

Fixed seed and fixed clock: running this twice leaves identical data.
Run with:  python -m keepair.demo.seed

Everything here is fictional: one organization, 3 departments, 6 teams,
12 projects, 2 vendors (vendor-b blocked) and one unregistered model.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Connection, Engine, func, insert, select, text

from keepair.clock import Clock, FixedClock, to_iso
from keepair.config import Settings
from keepair.db import make_engine
from keepair.demo.tree import Node, demo_tree
from keepair.demo.usage_plan import usage_plan
from keepair.gateway.tokens import generate_token, hash_token
from keepair.ids import uuid7
from keepair.money import MICRO_PER_UNIT
from keepair.rng import DEMO_SEED, seeded_rng
from keepair.schema import (
    agents,
    allocation_rules,
    app_meta,
    budgets,
    fx_rates,
    gateway_credentials,
    metadata,
    model_aliases,
    models,
    org_units,
    projects,
    registry_changes,
    reservations,
    tenants,
    unregistered_models,
    usage_events,
    vendor_endpoints,
    vendors,
)

DEMO_CLOCK_AT = datetime(2026, 1, 15, 9, 0, 0, tzinfo=UTC)
DEMO_ACTOR = "demo-admin"
SEEDED_RESERVATION_EXPIRY = datetime(2099, 1, 1, tzinfo=UTC)


def demo_clock() -> FixedClock:
    return FixedClock(DEMO_CLOCK_AT)


def _roll_up(node: Node) -> tuple[int, int, int]:
    """Add each SUBDIVISION child's totals to its parent. Returns the node's totals."""
    node.direct_reserved = node.reserved  # what is held on this scope itself
    for child in node.children:
        committed, reserved, extra = _roll_up(child)
        if child.mode == "SUBDIVISION":
            node.committed += committed
            node.reserved += reserved
            node.extra_micros += extra
    return node.committed, node.reserved, node.extra_micros


def agent_name(project_name: str) -> str:
    slug = project_name.lower().replace(" ", "-")
    return slug if slug.endswith("-agent") else slug + "-agent"


def demo_token(agent: str, seed_value: int = DEMO_SEED) -> str:
    """The demo credential for an agent. Derived from the seed, so the traffic
    generator can present it without the token being stored anywhere.

    Demo material only: the gateway refuses to start on demo data in production.
    """
    digest = int.from_bytes(hashlib.sha256(f"{seed_value}:{agent}".encode()).digest()[:8], "big")
    return generate_token(seeded_rng(digest))


def issue_demo_credentials(conn: Connection, seed_value: int = DEMO_SEED) -> int:
    """Give every demo agent a credential valid for 90 days from now (database clock).

    Not part of ``seed``: a credential's lifetime is real time, and the seeded data
    set must be identical on every run.
    """
    rng = seeded_rng(seed_value + 1)
    clock = demo_clock()
    conn.execute(text("DELETE FROM gateway_credentials WHERE label = 'demo'"))
    rows = conn.execute(
        select(agents.c.id, agents.c.tenant_id, agents.c.name).order_by(agents.c.name)
    )
    count = 0
    for row in rows:
        conn.execute(
            insert(gateway_credentials).values(
                id=uuid7(clock, rng),
                tenant_id=row.tenant_id,
                token_hash=hash_token(demo_token(row.name, seed_value)),
                agent_id=row.id,
                label="demo",
                created_at=func.now(),
                expires_at=func.now() + text("interval '90 days'"),
            )
        )
        count += 1
    return count


def seed(
    conn: Connection,
    clock: Clock,
    seed_value: int = DEMO_SEED,
    mock_provider_url: str = "http://mock-provider:8090",
) -> None:
    rng = seeded_rng(seed_value)
    now = clock.now()
    tables = ", ".join(t.name for t in metadata.sorted_tables)
    conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))

    tenant_id = uuid7(clock, rng)
    conn.execute(insert(tenants).values(id=tenant_id, name="Northwind Labs (demo tenant)"))
    conn.execute(
        insert(app_meta),
        [
            {"key": "demo", "value": "true"},
            {"key": "demo_seed", "value": str(seed_value)},
            {"key": "demo_clock", "value": to_iso(now)},
            {"key": "tenant_id", "value": str(tenant_id)},
        ],
    )

    org, terms = demo_tree()
    _roll_up(org)

    open_reservations: list[dict] = []

    def insert_node(
        node: Node,
        parent_unit: uuid.UUID | None,
        parent_budget: uuid.UUID | None,
        term: tuple[str, str, date],
        parent_path: tuple[uuid.UUID, ...] = (),
    ) -> None:
        term = terms.get(node.name, term)
        currency, period, period_start = term
        scope_id = uuid7(clock, rng)
        if node.kind == "PROJECT":
            conn.execute(
                insert(projects).values(
                    id=scope_id,
                    tenant_id=tenant_id,
                    team_id=parent_unit,
                    name=node.name,
                    created_at=now - timedelta(days=30),
                )
            )
        else:
            conn.execute(
                insert(org_units).values(
                    id=scope_id,
                    tenant_id=tenant_id,
                    parent_id=parent_unit,
                    kind=node.kind,
                    name=node.name,
                )
            )
        budget_id = uuid7(clock, rng)
        conn.execute(
            insert(budgets).values(
                id=budget_id,
                tenant_id=tenant_id,
                parent_id=parent_budget,
                scope_type=node.kind,
                scope_id=scope_id,
                cap_micros=node.cap * MICRO_PER_UNIT,
                currency=currency,
                period=period,
                period_start=period_start,
                mode=node.mode,
                policy=node.policy,
                fail_mode="FAIL_CLOSED" if node.policy in ("HARD", "APPROVAL") else "FAIL_OPEN",
                committed_micros=node.committed * MICRO_PER_UNIT + node.extra_micros,
                reserved_micros=node.reserved * MICRO_PER_UNIT,
            )
        )
        path = (budget_id, *(parent_path if node.mode == "SUBDIVISION" else ()))
        agent_id = None
        if node.kind == "PROJECT":
            agent_id = uuid7(clock, rng)
            conn.execute(
                insert(agents).values(
                    id=agent_id,
                    tenant_id=tenant_id,
                    project_id=scope_id,
                    name=agent_name(node.name),
                    created_at=now - timedelta(days=30),
                )
            )
        if node.direct_reserved:
            # Every reserved amount is backed by an open reservation. These stand
            # for long-running requests and are never swept (fixed far expiry).
            open_reservations.append(
                {
                    "id": uuid7(clock, rng),
                    "tenant_id": tenant_id,
                    "request_id": uuid7(clock, rng),
                    "agent_id": agent_id,
                    "budget_id": budget_id,
                    "budget_path": list(path),
                    "state": "RESERVED",
                    "model_id": "vendor-a/model-1",
                    "reserved_micros": node.direct_reserved * MICRO_PER_UNIT,
                    "currency": currency,
                    "expires_at": SEEDED_RESERVATION_EXPIRY,
                    "created_at": now - timedelta(minutes=5),
                    "dispatched_at": now - timedelta(minutes=5),
                }
            )
        for child in node.children:
            insert_node(child, scope_id, budget_id, term, path)

    insert_node(org, None, None, terms[org.name])

    # Registry: vendor-a allowed, vendor-b blocked (so its models are blocked too).
    conn.execute(
        insert(vendors),
        [
            {"tenant_id": tenant_id, "id": "vendor-a", "status": "ALLOWED", "updated_at": now - timedelta(days=30)},
            {"tenant_id": tenant_id, "id": "vendor-b", "status": "BLOCKED", "updated_at": now - timedelta(days=2), "version": 2},
        ],
    )  # fmt: skip
    model_rows = [
        # id, status, input and output price in micro-units per 1,000 tokens, max output tokens
        ("vendor-a/model-1", "ALLOWED", 3_000, 15_000, 4_096),
        ("vendor-a/model-2", "ALLOWED", 250, 1_250, 4_096),
        ("vendor-a/model-3", "BLOCKED", 10_000, 30_000, 8_192),
        ("vendor-b/model-1", "ALLOWED", 2_500, 10_000, 8_192),
        ("vendor-b/model-2", "BLOCKED", 500, 1_500, 4_096),
    ]
    conn.execute(
        insert(models),
        [
            {
                "tenant_id": tenant_id,
                "id": mid,
                "vendor_id": mid.split("/")[0],
                "status": status,
                "input_price_micros_per_1k": price_in,
                "output_price_micros_per_1k": price_out,
                "price_currency": "USD",
                "max_output_tokens": max_out,
                "updated_at": now - timedelta(days=30),
                "version": 2 if status == "BLOCKED" else 1,
            }
            for mid, status, price_in, price_out, max_out in model_rows
        ],
    )
    conn.execute(
        insert(model_aliases),
        [
            {"tenant_id": tenant_id, "alias": "model-1", "model_id": "vendor-a/model-1"},
            {"tenant_id": tenant_id, "alias": "va-fast", "model_id": "vendor-a/model-2"},
            {"tenant_id": tenant_id, "alias": "vb-large", "model_id": "vendor-b/model-1"},
        ],
    )
    conn.execute(
        insert(registry_changes),
        [
            {
                "tenant_id": tenant_id, "subject_type": "model", "subject_id": "vendor-a/model-3",
                "before_status": "ALLOWED", "after_status": "BLOCKED", "actor": DEMO_ACTOR,
                "reason": "Price change under review by finance.",
                "changed_at": now - timedelta(days=9),
            },
            {
                "tenant_id": tenant_id, "subject_type": "model", "subject_id": "vendor-b/model-2",
                "before_status": "ALLOWED", "after_status": "BLOCKED", "actor": DEMO_ACTOR,
                "reason": "Model retired by the vendor.",
                "changed_at": now - timedelta(days=20),
            },
            {
                "tenant_id": tenant_id, "subject_type": "vendor", "subject_id": "vendor-b",
                "before_status": "ALLOWED", "after_status": "BLOCKED", "actor": DEMO_ACTOR,
                "reason": "Contract review in progress. Blocked until legal sign-off.",
                "changed_at": now - timedelta(days=2),
            },
        ],
    )  # fmt: skip
    conn.execute(
        insert(vendor_endpoints),
        [
            {"tenant_id": tenant_id, "vendor_id": v, "base_url": mock_provider_url}
            for v in ("vendor-a", "vendor-b")
        ],
    )
    conn.execute(insert(reservations), open_reservations)
    conn.execute(
        insert(fx_rates).values(
            base="USD", quote="EUR", effective_date=date(2026, 1, 1), rate_micros=920_000,
            source="demo (invented rate)",
        )
    )  # fmt: skip
    # Gateway usage history (estimates) for 1 to 14 January, matching the budgets' committed
    # amounts. The demo billing files are generated from the same plan.
    agent_ids = dict(conn.execute(select(agents.c.name, agents.c.id)).all())
    conn.execute(
        insert(usage_events),
        [
            {
                "id": uuid7(clock, rng),
                "tenant_id": tenant_id,
                "provider": "vendor-a",
                "model_id": row.model,
                "agent_id": agent_ids.get(agent_name(row.project)) if row.project else None,
                "team": row.team,
                "project": row.project,
                "agent": agent_name(row.project) if row.project else None,
                "input_tokens": row.price_micros // 30,
                "output_tokens": row.price_micros // 60,
                "actual_micros": row.cost_micros,
                "currency": row.currency,
                "usage_known": True,
                "price_micros": row.price_micros,
                "price_currency": "USD",
                "source": "GATEWAY",
                "occurred_at": datetime(row.day.year, row.day.month, row.day.day, 12, tzinfo=UTC),
                "ingested_at": datetime(row.day.year, row.day.month, row.day.day, 12, tzinfo=UTC),
            }
            for row in usage_plan(seed_value)
        ],
    )
    # One allocation rule: shared platform cost is split between the team's two projects.
    conn.execute(
        insert(allocation_rules).values(
            id=uuid7(clock, rng),
            tenant_id=tenant_id,
            name="Platform shared cost",
            priority=10,
            effective_from=date(2026, 1, 1),
            match={"project": "shared-platform"},
            split=[
                {"project": "Build Assistant", "weight_bp": 6000},
                {"project": "Log Summarizer", "weight_bp": 4000},
            ],
        )
    )
    conn.execute(
        insert(unregistered_models).values(
            tenant_id=tenant_id,
            requested_name="vendor-a/model-9",
            first_seen_at=now - timedelta(days=3),
            last_seen_at=now - timedelta(hours=1),
            seen_count=14,
        )
    )
    # No heartbeats are seeded: every component shows Unknown until phase 2.


def run(engine: Engine, settings: Settings) -> int:
    with engine.begin() as conn:
        seed(conn, demo_clock(), mock_provider_url=settings.mock_provider_url)
        return issue_demo_credentials(conn)


if __name__ == "__main__":
    _settings = Settings()
    _count = run(make_engine(_settings), _settings)
    print(f"Demo data loaded (seed {DEMO_SEED}, clock {to_iso(DEMO_CLOCK_AT)}).")
    print(f"{_count} demo gateway credentials issued, valid for 90 days.")
