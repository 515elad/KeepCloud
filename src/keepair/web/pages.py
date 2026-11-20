"""Navigation and the roadmap shown on each page (UX-1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    phase: int | None  # None: not part of the MVP phases
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
        (Section("Forecast and anomaly alerts", None, ("FR-08",)),),
    ),
    Page(
        "spend",
        "Spend",
        "What was spent, by model and by project, and how sure each figure is.",
        (
            Section("Allocation rule editor", None, ("FR-03",)),
            Section("Cloud billing connectors (AWS, Azure, GCP)", None, ("FR-01",)),
        ),
    ),
    Page(
        "budgets",
        "Budgets",
        "The budget hierarchy, each budget's cap and owner, and what is left after parent limits.",
        (Section("Creating budgets and changing caps", None, ("FR-04",)),),
    ),
    Page(
        "gateway",
        "Gateway",
        "Which vendors and models are allowed, and what the gateway denied and why.",
        (Section("Streaming responses", None, ("FR-05",)),),
    ),
    Page(
        "approvals",
        "Approvals",
        "Held requests and actions that are waiting for a second person.",
        (Section("Approval chains and delegation", None, ("FR-11",)),),
    ),
    Page(
        "reconciliation",
        "Reconciliation",
        "Estimates compared with provider records and invoices, by period.",
        (
            Section("Invoice PDF upload and review queue", None, ("FR-07",)),
            Section("Period close and locking", None, ("FR-12",)),
        ),
    ),
    Page(
        "reports",
        "Reports",
        "Showback by project, with a download.",
        (Section("Scheduled reports and chargeback to a finance system", None, ("FR-12",)),),
    ),
    Page(
        "admin",
        "Admin",
        "Users, roles and emergency controls.",
        (Section("Single sign-on and user provisioning", None, ("FR-13",)),),
    ),
    Page(
        "audit-log",
        "Audit log",
        "Every administrative action, in a chain that shows tampering.",
        (Section("Signed chain head stored outside the database", None, ("SEC-32",)),),
    ),
)
PAGES_BY_SLUG = {p.slug: p for p in PAGES}
