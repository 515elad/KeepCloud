"""Allocation of billing records to projects (FR-03) and join confidence (FR-06).

Pure functions. Order of precedence for one record:

  1. a manual assignment                         -> ALLOCATED, MANUAL
  2. tags name a team and one of its projects    -> ALLOCATED, DIRECT   (confidence 90 to 100)
  3. an allocation rule matches (shared cost)    -> ALLOCATED, INFERRED (split by weights)
  4. tags name a project but no team             -> REVIEW,    INFERRED (confidence 70)
  5. tags are present but match nothing          -> UNMATCHED
  6. no tags                                     -> UNALLOCATED

Nothing is guessed: a record that matches no project is listed, never assigned.

Join confidence (FR-06):
    exact match on team and project = 100 - 5 per missing optional key, never below 90
    fallback (project only)          = 70
    no match                         = 0
Treatment: 90 to 100 accepted; 70 to 89 accepted and flagged for review; below 70 unmatched.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

MANDATORY_KEYS = ("team", "project")
OPTIONAL_KEYS = ("customer", "application", "agent", "environment")
ALLOWED_TAG_KEYS = MANDATORY_KEYS + OPTIONAL_KEYS
AUTO_ACCEPT, REVIEW_FLOOR, FALLBACK_CONFIDENCE = 90, 70, 70
TOTAL_BP = 10_000


def norm(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def treatment(confidence: int) -> str:
    """Launch thresholds (FR-06)."""
    if confidence >= AUTO_ACCEPT:
        return "ACCEPTED"
    if confidence >= REVIEW_FLOOR:
        return "REVIEW"
    return "UNMATCHED"


def exact_confidence(tags: dict[str, str]) -> int:
    missing = sum(1 for k in OPTIONAL_KEYS if not norm(tags.get(k)))
    return max(AUTO_ACCEPT, 100 - 5 * missing)


def split_amount(amount_micros: int, weights_bp: list[int]) -> list[int]:
    """Split an amount by weights with the largest-remainder method.

    The parts are whole micro-units and always add up to the amount exactly.
    """
    if amount_micros < 0 or not weights_bp or any(w < 0 for w in weights_bp):
        raise ValueError("amount and weights must not be negative")
    total = sum(weights_bp)
    if total <= 0:
        raise ValueError("weights must add up to more than zero")
    shares = [amount_micros * w // total for w in weights_bp]
    remainders = [(amount_micros * w) % total for w in weights_bp]
    left = amount_micros - sum(shares)
    for index in sorted(range(len(shares)), key=lambda i: (-remainders[i], i))[:left]:
        shares[index] += 1
    return shares


@dataclass(frozen=True, slots=True)
class ProjectRef:
    id: uuid.UUID
    name: str
    team: str


@dataclass(frozen=True, slots=True)
class Rule:
    id: uuid.UUID
    name: str
    priority: int
    effective_from: date
    effective_to: date | None
    match: dict[str, str]  # tag key -> required value
    split: tuple[tuple[str, int], ...]  # (project name, weight in basis points)
    version: int = 1

    def applies(self, tags: dict[str, str], on: date) -> bool:
        if on < self.effective_from or (self.effective_to and on > self.effective_to):
            return False
        return bool(self.match) and all(norm(tags.get(k)) == norm(v) for k, v in self.match.items())


@dataclass(frozen=True, slots=True)
class Fact:
    project_id: uuid.UUID | None
    amount_micros: int
    state: str  # ALLOCATED, REVIEW, UNMATCHED, UNALLOCATED
    confidence: str | None  # DIRECT, INFERRED, MANUAL
    join_confidence: int
    explanation: str
    rule_id: uuid.UUID | None = None
    rule_version: int | None = None


def allocate(
    *,
    amount_micros: int,
    tags: dict[str, Any],
    charge_date: date,
    projects: list[ProjectRef],
    rules: list[Rule],
    manual_project_id: uuid.UUID | None = None,
) -> list[Fact]:
    """The allocation facts for one record. Their amounts always add up to the record's."""
    tags = {k: v for k, v in tags.items() if k in ALLOWED_TAG_KEYS and isinstance(v, str)}
    by_id = {p.id: p for p in projects}
    if manual_project_id is not None and manual_project_id in by_id:
        return [Fact(manual_project_id, amount_micros, "ALLOCATED", "MANUAL", 100,
                     "Assigned by hand.")]  # fmt: skip

    team, project = norm(tags.get("team")), norm(tags.get("project"))
    named = [p for p in projects if norm(p.name) == project] if project else []
    if team and project:
        exact = [p for p in named if norm(p.team) == team]
        if len(exact) == 1:
            confidence = exact_confidence(tags)
            return [Fact(exact[0].id, amount_micros, "ALLOCATED", "DIRECT", confidence,
                         "Tags name the team and the project.")]  # fmt: skip

    for rule in sorted(rules, key=lambda r: (r.priority, str(r.id))):  # deterministic order
        if not rule.applies(tags, charge_date):
            continue
        by_name = {norm(p.name): p for p in projects}
        targets = [(by_name.get(norm(name)), weight) for name, weight in rule.split]
        if any(p is None for p, _ in targets):
            continue  # a rule that names an unknown project is not applied
        parts = split_amount(amount_micros, [w for _, w in targets])
        return [
            Fact(
                p.id,
                part,
                "ALLOCATED",
                "INFERRED",
                100,
                f"Split by rule '{rule.name}': {w / 100:g}% of the record.",
                rule.id,
                rule.version,
            )
            for (p, w), part in zip(targets, parts, strict=True)
        ]

    if project and not team and len(named) == 1:
        return [Fact(named[0].id, amount_micros, "REVIEW", "INFERRED", FALLBACK_CONFIDENCE,
                     "Tags name the project but no team. Accepted, to be reviewed.")]  # fmt: skip
    if tags:
        why = "Tags name a team that does not own this project." if named else (
            "Tags do not match any project.")  # fmt: skip
        return [Fact(None, amount_micros, "UNMATCHED", None, 0, why)]
    return [Fact(None, amount_micros, "UNALLOCATED", None, 0, "The record has no tags.")]
