"""SQLAlchemy Core table definitions (phase 0: foundation tables only).

The business tables in PRD v1.4 Section 2.5 arrive with their phases.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Identity,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

# One row per component, upserted on each heartbeat (FR-21, SEC-37).
heartbeats = Table(
    "heartbeats",
    metadata,
    Column("component", Text, primary_key=True),
    Column("last_heartbeat_at", DateTime(timezone=True), nullable=False),
)

# Alert records (hard rule 5: every failure leaves a metric, an alert and a UI row).
alerts = Table(
    "alerts",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("raised_at", DateTime(timezone=True), nullable=False),
    Column("severity", Text, nullable=False),
    Column("code", Text, nullable=False),
    Column("component", Text, nullable=False),
    Column("message", Text, nullable=False),
    CheckConstraint("severity in ('SEV1','SEV2','SEV3')", name="alerts_severity_check"),
)

# Key/value facts about the loaded data set (demo seed and demo clock).
app_meta = Table(
    "app_meta",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False),
)

# Phase 0 only: one placeholder amount that exercises money storage and the
# "i" popover. Replaced by real budgets in phase 1.
demo_placeholder = Table(
    "demo_placeholder",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("label", Text, nullable=False),
    Column("amount_micro", BigInteger, nullable=False),
    Column("currency", String(3), nullable=False),
    CheckConstraint("amount_micro >= 0", name="demo_placeholder_amount_check"),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="demo_placeholder_currency_check"),
)
