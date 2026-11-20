"""Parser for billing files in a FOCUS-style column layout (FR-01, FR-02).

A billing file is untrusted input (SEC-28). Everything is checked before
anything is stored, and one invalid row rejects the whole file (quarantine):

- size, row and field limits, checked before and during parsing;
- exact header set; strict CSV;
- costs parsed as exact decimals into micro-units (no float, at most 6 decimals);
- ISO 8601 times with a timezone, ISO 4217 currency;
- tags are a JSON object of text values; only allowlisted keys are kept;
- each source may supply exactly one finalization state.

Reasons name the row and the column. They never repeat cell content.

Column names follow the FinOps FOCUS specification. Columns starting with
``x_`` are KeepAir extensions, as FOCUS allows.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from keepair.billing.allocation import ALLOWED_TAG_KEYS
from keepair.billing.finalization import Source
from keepair.money import BIGINT_MAX, MICRO_PER_UNIT

FOCUS_VERSION = "1.0 (subset)"
COLUMNS = (
    "BillingAccountId",
    "BillingPeriodStart",
    "BillingPeriodEnd",
    "ChargePeriodStart",
    "ChargePeriodEnd",
    "ChargeCategory",
    "ProviderName",
    "ServiceName",
    "SkuId",
    "ConsumedQuantity",
    "ConsumedUnit",
    "BilledCost",
    "BillingCurrency",
    "Tags",
    "x_RecordKey",
    "x_Revision",
    "x_FinalizationState",
)
MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20_000
MAX_FIELD = 2_000
MAX_REASONS = 20
_KEY_RE = re.compile(r"[A-Za-z0-9._:-]{1,120}")
_TEXT_RE = re.compile(r"[^\x00-\x1f\x7f]{1,200}")
_CURRENCY_RE = re.compile(r"[A-Z]{3}")


class Quarantine(Exception):
    """The file is rejected as a whole. ``reasons`` are safe to show."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons[:3]))
        self.reasons = reasons[:MAX_REASONS]


@dataclass(frozen=True, slots=True)
class BillingRow:
    record_key: str
    revision: int
    provider: str
    model_id: str
    charge_date: date
    billing_period: date
    billed_micros: int
    currency: str
    finalization_state: str
    consumed_quantity: int
    consumed_unit: str
    tags: dict[str, str]

    def payload(self) -> dict[str, Any]:
        return {
            "record_key": self.record_key,
            "revision": self.revision,
            "provider": self.provider,
            "model_id": self.model_id,
            "charge_date": self.charge_date.isoformat(),
            "billing_period": self.billing_period.isoformat(),
            "billed_micros": self.billed_micros,
            "currency": self.currency,
            "finalization_state": self.finalization_state,
            "consumed_quantity": self.consumed_quantity,
            "consumed_unit": self.consumed_unit,
            "tags": self.tags,
        }


@dataclass(frozen=True, slots=True)
class ParsedFile:
    rows: list[BillingRow]
    dropped_tag_keys: int


class _Bad(ValueError):
    pass


def decimal_to_micros(text: str) -> int:
    """Exact conversion. More than six decimals cannot be stored and is refused."""
    try:
        value = Decimal(text.strip())
    except InvalidOperation:
        raise _Bad("is not a number") from None
    if not value.is_finite() or value < 0:
        raise _Bad("must be a number, zero or more")
    micros = value * MICRO_PER_UNIT
    if micros != micros.to_integral_value():
        raise _Bad("has more than 6 decimals")
    if micros > BIGINT_MAX:
        raise _Bad("is too large")
    return int(micros)


def _when(text: str) -> datetime:
    try:
        value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise _Bad("is not an ISO 8601 time") from None
    if value.tzinfo is None:
        raise _Bad("has no timezone")
    return value.astimezone(UTC)


def _whole(text: str, low: int, high: int) -> int:
    if not re.fullmatch(r"[0-9]{1,18}", text.strip()):
        raise _Bad("is not a whole number")
    value = int(text)
    if not low <= value <= high:
        raise _Bad(f"must be between {low} and {high}")
    return value


def _tags(text: str) -> tuple[dict[str, str], int]:
    if not text.strip():
        return {}, 0
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        raise _Bad("is not JSON") from None
    if not isinstance(raw, dict):
        raise _Bad("must be a JSON object")
    kept, dropped = {}, 0
    for key, value in raw.items():
        if key not in ALLOWED_TAG_KEYS:
            dropped += 1  # unknown keys are ignored, not stored
            continue
        if not isinstance(value, str) or not _TEXT_RE.fullmatch(value):
            raise _Bad(f"value of '{key}' must be text of 1 to 200 characters")
        kept[key] = value
    return kept, dropped


def parse(data: bytes, source: Source) -> ParsedFile:
    if len(data) > MAX_BYTES:
        raise Quarantine([f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB."])
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Quarantine(["The file is not UTF-8 text."]) from None
    if "\x00" in text:
        raise Quarantine(["The file contains binary data."])
    csv.field_size_limit(MAX_FIELD)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader, None)
        if header is None or tuple(header) != COLUMNS:
            raise Quarantine(
                ["The header row does not match the expected columns: " + ", ".join(COLUMNS) + "."]
            )
        rows: list[BillingRow] = []
        reasons: list[str] = []
        seen: set[tuple[str, int]] = set()
        dropped_total = 0
        for number, cells in enumerate(reader, start=2):
            if number - 1 > MAX_ROWS:
                raise Quarantine([f"The file has more than {MAX_ROWS:,} rows."])
            if len(cells) != len(COLUMNS):
                reasons.append(f"Row {number}: expected {len(COLUMNS)} columns.")
                continue
            c = dict(zip(COLUMNS, cells, strict=True))
            column = ""
            try:
                column = "x_RecordKey"
                if not _KEY_RE.fullmatch(c[column]):
                    raise _Bad("must be 1 to 120 letters, digits, dot, colon, dash or underscore")
                column = "x_Revision"
                revision = _whole(c[column], 1, 9_999)
                column = "x_FinalizationState"
                if c[column] != source.state.value:
                    raise _Bad(f"must be {source.state.value} for this source")
                column = "ProviderName"
                if c[column] != source.provider:
                    raise _Bad(f"must be {source.provider} for this source")
                column = "ChargeCategory"
                if c[column] != "Usage":
                    raise _Bad("must be Usage (other categories are not supported yet)")
                column = "SkuId"
                if not _TEXT_RE.fullmatch(c[column]):
                    raise _Bad("must be text of 1 to 200 characters")
                column = "ChargePeriodStart"
                charge_start = _when(c[column])
                column = "ChargePeriodEnd"
                if _when(c[column]) <= charge_start:
                    raise _Bad("must be after ChargePeriodStart")
                column = "BillingPeriodStart"
                period_start = _when(c[column])
                column = "BillingPeriodEnd"
                if _when(c[column]) <= period_start:
                    raise _Bad("must be after BillingPeriodStart")
                column = "BilledCost"
                billed = decimal_to_micros(c[column])
                column = "BillingCurrency"
                if not _CURRENCY_RE.fullmatch(c[column]):
                    raise _Bad("must be a three-letter ISO 4217 code")
                column = "ConsumedQuantity"
                quantity = _whole(c[column], 0, 10**15)
                column = "ConsumedUnit"
                if not _TEXT_RE.fullmatch(c[column]):
                    raise _Bad("must be text of 1 to 200 characters")
                column = "Tags"
                tags, dropped = _tags(c[column])
            except _Bad as bad:
                reasons.append(f"Row {number}, {column}: {bad}.")
                continue
            if (c["x_RecordKey"], revision) in seen:
                reasons.append(f"Row {number}: the same record key and revision appear twice.")
                continue
            seen.add((c["x_RecordKey"], revision))
            dropped_total += dropped
            rows.append(
                BillingRow(
                    record_key=c["x_RecordKey"],
                    revision=revision,
                    provider=c["ProviderName"],
                    model_id=c["SkuId"].strip().lower(),
                    charge_date=charge_start.date(),
                    billing_period=period_start.date(),
                    billed_micros=billed,
                    currency=c["BillingCurrency"],
                    finalization_state=c["x_FinalizationState"],
                    consumed_quantity=quantity,
                    consumed_unit=c["ConsumedUnit"],
                    tags=tags,
                )
            )
    except csv.Error:
        raise Quarantine(["The file is not valid CSV, or a field is too long."]) from None
    if reasons:
        raise Quarantine(reasons)
    if not rows:
        raise Quarantine(["The file has no data rows."])
    return ParsedFile(rows, dropped_total)
