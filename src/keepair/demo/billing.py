"""Demo billing files in a FOCUS-style layout (hard rules 1 and 2).

Generated from the same plan as the seeded gateway usage, with a fixed seed.
Nothing here comes from a real provider. Run with:

    python -m keepair.demo.billing --out demo/billing

The generated files are committed in ``demo/billing/`` so that they can be
uploaded from a browser without running anything. A test checks that the
committed files are exactly what this module generates.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from keepair.billing.focus import COLUMNS
from keepair.demo.seed import agent_name
from keepair.demo.usage_plan import FIRST_DAY, usage_plan
from keepair.money import MICRO_PER_UNIT
from keepair.rng import DEMO_SEED, seeded_rng

USAGE_FILE = "vendor-a-usage-2026-01.csv"
CORRECTION_FILE = "vendor-a-usage-2026-01-correction.csv"
INVOICE_FILE = "vendor-a-invoice-2026-01.csv"
BROKEN_FILE = "broken-example.csv"
UNCONTROLLED_PROJECT = "Lead Scoring"  # the provider saw 30% more than the gateway did
REVIEW_PROJECT = "Red Team"  # one record tagged with the project only
INVOICED_DAYS = 7


def _slug(text: str) -> str:
    return text.lower().replace(" ", "-").replace("/", "-")


def _money(micros: int) -> str:
    return f"{Decimal(micros) / MICRO_PER_UNIT:.6f}"


def _row(key, day: date, model, billed_micros, tags, revision=1, state="PROVIDER_REPORTED"):
    return {
        "BillingAccountId": "demo-account-001",
        "BillingPeriodStart": "2026-01-01T00:00:00Z",
        "BillingPeriodEnd": "2026-02-01T00:00:00Z",
        "ChargePeriodStart": f"{day.isoformat()}T00:00:00Z",
        "ChargePeriodEnd": f"{(day + timedelta(days=1)).isoformat()}T00:00:00Z",
        "ChargeCategory": "Usage",
        "ProviderName": "vendor-a",
        "ServiceName": "Model inference",
        "SkuId": model,
        "ConsumedQuantity": str(billed_micros // 45),
        "ConsumedUnit": "Tokens",
        "BilledCost": _money(billed_micros),
        "BillingCurrency": "USD",
        "Tags": json.dumps(tags, separators=(",", ":"), sort_keys=True) if tags else "",
        "x_RecordKey": key,
        "x_Revision": str(revision),
        "x_FinalizationState": state,
    }


def usage_rows(seed_value: int = DEMO_SEED) -> list[dict[str, str]]:
    rng = seeded_rng(seed_value + 4)
    grouped: dict[tuple, int] = defaultdict(int)
    for item in usage_plan(seed_value):
        grouped[(item.day, item.team, item.project, item.model)] += item.price_micros
    rows = []
    for (day, team, project, model), estimate in sorted(grouped.items(), key=lambda kv: str(kv[0])):
        # The provider's own figure is a little below the gateway's estimate.
        billed = estimate * rng.randrange(9_930, 9_991) // 10_000
        if project is None:
            # Cost the team runs for all its projects: tagged for the split rule.
            key, tags = (
                f"va-{day}-{_slug(team)}-shared-{_slug(model)}",
                {"project": "shared-platform"},
            )
        else:
            key = f"va-{day}-{_slug(project)}-{_slug(model)}"
            tags = {"team": team, "project": project, "agent": agent_name(project),
                    "environment": "production"}  # fmt: skip
            if project == UNCONTROLLED_PROJECT:
                billed = estimate * 13 // 10
            if (
                project == REVIEW_PROJECT
                and day == FIRST_DAY + timedelta(days=13)
                and model.endswith("model-1")
            ):
                tags = {"project": project}  # no team: a fallback join, confidence 70
        rows.append(_row(key, day, model, billed, tags))
    last = FIRST_DAY + timedelta(days=13)
    rows.append(_row(f"va-{last}-shadow-experiment-vendor-a-model-1", last, "vendor-a/model-1",
                     42_500_000, {"team": "Growth", "project": "shadow-experiment"}))  # fmt: skip
    rows.append(
        _row(f"va-{last}-untagged-vendor-a-model-2", last, "vendor-a/model-2", 17_250_000, {})
    )
    return rows


def correction_rows(seed_value: int = DEMO_SEED) -> list[dict[str, str]]:
    """The provider restates one project's figures for 10 January: revision 2, 5% higher."""
    day = (FIRST_DAY + timedelta(days=9)).isoformat()
    out = []
    for row in usage_rows(seed_value):
        if row["x_RecordKey"].startswith(f"va-{day}-ticket-triage-"):
            billed = int(Decimal(row["BilledCost"]) * MICRO_PER_UNIT) * 105 // 100
            out.append(row | {"BilledCost": _money(billed), "x_Revision": "2"})
    return out


def invoice_rows(seed_value: int = DEMO_SEED) -> list[dict[str, str]]:
    """The invoice covers the first week. Same charges, now final."""
    limit = (FIRST_DAY + timedelta(days=INVOICED_DAYS)).isoformat()
    return [
        row | {"x_RecordKey": "inv-" + row["x_RecordKey"][3:], "x_FinalizationState": "INVOICED"}
        for row in usage_rows(seed_value)
        if row["ChargePeriodStart"][:10] < limit
    ]


def broken_rows(seed_value: int = DEMO_SEED) -> list[dict[str, str]]:
    """A file that must be refused as a whole. Each row is wrong in a different way."""
    good = usage_rows(seed_value)[:5]
    return [
        good[0],
        good[1] | {"BilledCost": "-12.50"},
        good[2] | {"ChargePeriodStart": "10/01/2026"},
        good[3] | {"Tags": '=HYPERLINK("http://example.invalid","click")'},
        good[4] | {"BilledCost": "0.1234567"},
    ]


FILES = {
    USAGE_FILE: usage_rows,
    CORRECTION_FILE: correction_rows,
    INVOICE_FILE: invoice_rows,
    BROKEN_FILE: broken_rows,
}


def render(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def generate(seed_value: int = DEMO_SEED) -> dict[str, bytes]:
    return {name: render(make(seed_value)) for name, make in FILES.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the demo billing files.")
    parser.add_argument("--out", default="demo/billing")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in generate().items():
        (out / name).write_bytes(data)
        print(f"{name}: {data.count(b'\n') - 1} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
