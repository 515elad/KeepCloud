"""Navigation and the roadmap shown on each page (UX-1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    phase: int
    reqs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Page:
    slug: str
    title: str
    summary: str
    sections: tuple[Section, ...]

    @property
    def path(self) -> str:
        return "/" if self.slug == "overview" else f"/{self.slug}"


PAGES: tuple[Page, ...] = (
    Page(
        "overview",
        "Overview",
        "Where spend stands, what is unowned, and whether the controls are working.",
        (
            Section("Executive summary", 4, ("FR-12",)),
            Section("Unowned spend bucket", 5, ("FR-17",)),
        ),
    ),
    Page(
        "budgets",
        "Budgets",
        "The budget hierarchy, each budget's cap, and what is left after parent limits.",
        (
            Section("Live committed and reserved amounts from the gateway", 2, ("FR-05",)),
            Section("Owner assignment", 5, ("FR-17",)),
        ),
    ),
    Page(
        "gateway",
        "Gateway",
        "Which vendors and models are allowed, and what the gateway denied and why.",
        (
            Section("Projects and gateway credentials", 2, ("FR-05", "SEC-12")),
            Section("Denials feed", 2, ("FR-05", "UX-5")),
            Section("Fail-open report", 3, ("FR-05", "FR-12", "UX-7")),
        ),
    ),
    Page(
        "approvals",
        "Approvals",
        "Held requests and actions that are waiting for a second person.",
        (
            Section("HELD queue", 5, ("FR-11", "UX-11")),
            Section("Two-person pending items", 5, ("FR-18", "SEC-15")),
        ),
    ),
    Page(
        "reconciliation",
        "Reconciliation",
        "Estimates compared with provider records and invoices, by period.",
        (
            Section("Finalization by period", 4, ("FR-07", "UX-8")),
            Section("Unallocated and unmatched queue", 4, ("FR-03", "FR-06")),
        ),
    ),
    Page(
        "reports",
        "Reports",
        "Showback reports and exports.",
        (Section("Showback report and CSV export", 6, ("FR-12", "SEC-29")),),
    ),
    Page(
        "admin",
        "Admin",
        "Users, roles and emergency controls.",
        (
            Section("Users, roles and MFA", 5, ("FR-13", "FR-17")),
            Section("Kill switch", 5, ("FR-22", "UX-7")),
        ),
    ),
    Page(
        "audit-log",
        "Audit log",
        "Every administrative action, in a chain that shows tampering.",
        (Section("Audit log viewer and chain verification", 6, ("FR-12", "SEC-31", "SEC-32")),),
    ),
)
PAGES_BY_SLUG = {p.slug: p for p in PAGES}
