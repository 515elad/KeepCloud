"""The demo organization: one tree of scopes with their budgets. All fictional."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


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
    extra_micros: int = 0  # extra committed spend below one whole unit
    children: list[Node] = field(default_factory=list)
    direct_reserved: int = 0


def demo_tree() -> tuple[Node, dict[str, tuple[str, str, date]]]:
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
                # 0.15 EUR left: the demo traffic exhausts this hard limit.
                Node("PROJECT", "Summaries EU", "HARD", 25_000, committed=23_499, reserved=1_500,
                     extra_micros=850_000),
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
