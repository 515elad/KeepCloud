"""Deterministic demo data (hard rule 2).

Fixed seed and fixed clock: running this twice leaves identical data.
Run with:  python -m keepair.demo.seed

Everything here is fictional: one organization, 3 departments, 6 teams,
12 projects, 2 vendors (vendor-b blocked) and one unregistered model.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Connection, Engine, insert, text

from keepair.clock import Clock, FixedClock, to_iso
from keepair.config import Settings
from keepair.db import make_engine
from keepair.ids import uuid7
from keepair.money import MICRO_PER_UNIT
from keepair.rng import DEMO_SEED, seeded_rng
from keepair.schema import (
    app_meta,
    budgets,
    metadata,
    model_aliases,
    models,
    org_units,
    projects,
    registry_changes,
    tenants,
    unregistered_models,
    vendors,
)

DEMO_CLOCK_AT = datetime(2026, 1, 15, 9, 0, 0, tzinfo=UTC)
DEMO_ACTOR = "demo-admin"


def demo_clock() -> FixedClock:
    return FixedClock(DEMO_CLOCK_AT)


@dataclass
class Node:
    """One scope with its budget. Amounts are whole currency units."""

    kind: str
    name: str
    policy: str
    cap: int
    mode: str = "SUBDIVISION"
    committed: int = 0  # spend recorded directly on this scope
    reserved: int = 0
    children: list[Node] = field(default_factory=list)


def _tree() -> tuple[Node, dict[str, tuple[str, str, date]]]:
    """The demo hierarchy, and (currency, period, period_start) per department subtree."""
    p = lambda name, policy, cap, committed, reserved, mode="SUBDIVISION": Node(  # noqa: E731
        "PROJECT", name, policy, cap, mode, committed, reserved
    )
    org = Node("ORG", "Northwind Labs", "SOFT", 220_000, "INDEPENDENT", children=[
        Node("DEPT", "Engineering", "HARD", 120_000, children=[
            Node("TEAM", "Platform", "HARD", 70_000, committed=18_000, children=[
                p("Build Assistant", "HARD", 40_000, 22_000, 1_200),
                p("Log Summarizer", "SOFT", 30_000, 26_400, 600),
            ]),
            Node("TEAM", "Agents", "APPROVAL", 60_000, children=[
                p("Research Agent", "APPROVAL", 35_000, 14_000, 1_750),
                p("Code Review Agent", "HARD", 30_000, 24_300, 1_200),
            ]),
        ]),
        Node("DEPT", "Customer Operations", "SOFT", 60_000, children=[
            Node("TEAM", "Support Automation", "SOFT", 35_000, children=[
                p("Ticket Triage", "SOFT", 20_000, 12_400, 400),
                p("Reply Drafts", "MONITOR", 15_000, 5_250, 150),
            ]),
            Node("TEAM", "Sales Assist", "MONITOR", 20_000, children=[
                p("Lead Scoring", "MONITOR", 12_000, 2_400, 120),
                p("Call Notes", "MONITOR", 6_000, 7_080, 0, mode="INDEPENDENT"),
            ]),
        ]),
        Node("DEPT", "Research Europe", "HARD", 80_000, "INDEPENDENT", children=[
            Node("TEAM", "Language Models", "HARD", 50_000, children=[
                p("Translation", "HARD", 30_000, 15_000, 1_200),
                p("Summaries EU", "HARD", 25_000, 22_750, 1_500),
            ]),
            Node("TEAM", "Evaluation", "MONITOR", 15_000, "INDEPENDENT", children=[
                p("Benchmark Runs", "MONITOR", 10_000, 4_500, 0),
                p("Red Team", "SOFT", 5_000, 3_500, 100),
            ]),
        ]),
    ])  # fmt: skip
    month, quarter = ("MONTH", date(2026, 1, 1)), ("QUARTER", date(2026, 1, 1))
    terms = {
        "Northwind Labs": ("USD", *month),
        "Engineering": ("USD", *month),
        "Customer Operations": ("USD", *month),
        "Research Europe": ("EUR", *quarter),
    }
    return org, terms


def _roll_up(node: Node) -> tuple[int, int]:
    """Add each SUBDIVISION child's totals to its parent. Returns the node's totals."""
    for child in node.children:
        committed, reserved = _roll_up(child)
        if child.mode == "SUBDIVISION":
            node.committed += committed
            node.reserved += reserved
    return node.committed, node.reserved


def seed(conn: Connection, clock: Clock, seed_value: int = DEMO_SEED) -> None:
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

    org, terms = _tree()
    _roll_up(org)

    def insert_node(
        node: Node,
        parent_unit: uuid.UUID | None,
        parent_budget: uuid.UUID | None,
        term: tuple[str, str, date],
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
                committed_micros=node.committed * MICRO_PER_UNIT,
                reserved_micros=node.reserved * MICRO_PER_UNIT,
            )
        )
        for child in node.children:
            insert_node(child, scope_id, budget_id, term)

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
        insert(unregistered_models).values(
            tenant_id=tenant_id,
            requested_name="vendor-a/model-9",
            first_seen_at=now - timedelta(days=3),
            last_seen_at=now - timedelta(hours=1),
            seen_count=14,
        )
    )
    # No heartbeats are seeded: every component shows Unknown until phase 2.


def run(engine: Engine) -> None:
    with engine.begin() as conn:
        seed(conn, demo_clock())


if __name__ == "__main__":
    run(make_engine(Settings()))
    print(f"Demo data loaded (seed {DEMO_SEED}, clock {to_iso(DEMO_CLOCK_AT)}).")
