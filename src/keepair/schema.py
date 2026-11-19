"""SQLAlchemy Core table definitions (phase 0: foundation tables only).

The business tables in PRD v1.4 Section 2.5 arrive with their phases.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
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

# --- Phase 1: tenancy, hierarchy, budgets and registry -----------------------
# Every tenant-owned table carries tenant_id (SEC-16). Row-level security is
# switched on with sign-in in phase 5; until then there is one tenant.

tenants = Table(
    "tenants",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
)

org_units = Table(
    "org_units",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, ForeignKey("tenants.id"), nullable=False),
    Column("parent_id", Uuid, ForeignKey("org_units.id")),
    Column("kind", Text, nullable=False),
    Column("name", Text, nullable=False),
    CheckConstraint("kind in ('ORG','DEPT','TEAM')", name="org_units_kind_check"),
)

projects = Table(
    "projects",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, ForeignKey("tenants.id"), nullable=False),
    Column("team_id", Uuid, ForeignKey("org_units.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("key_custody", Text, nullable=False, server_default="KEEPAIR"),
    Column("egress_verified", Boolean, nullable=False, server_default=text("false")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("key_custody in ('KEEPAIR','CUSTOMER')", name="projects_key_custody_check"),
)

# PRD v1.4 Section 2.5, plus tenant_id.
budgets = Table(
    "budgets",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, ForeignKey("tenants.id"), nullable=False),
    Column("parent_id", Uuid, ForeignKey("budgets.id")),
    Column("scope_type", Text, nullable=False),
    Column("scope_id", Uuid, nullable=False),
    Column("cap_micros", BigInteger, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("period", Text, nullable=False),
    Column("period_start", Date, nullable=False),
    Column("mode", Text, nullable=False, server_default="INDEPENDENT"),
    Column("policy", Text, nullable=False),
    Column("fail_mode", Text, nullable=False),
    Column("owner_user_id", Uuid),
    Column("committed_micros", BigInteger, nullable=False, server_default=text("0")),
    Column("reserved_micros", BigInteger, nullable=False, server_default=text("0")),
    Column("version", BigInteger, nullable=False, server_default=text("0")),
    CheckConstraint(
        "scope_type in ('ORG','BU','DEPT','TEAM','PROJECT','APP','AGENT')",
        name="budgets_scope_type_check",
    ),
    CheckConstraint("cap_micros >= 0", name="budgets_cap_check"),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="budgets_currency_check"),
    CheckConstraint("period in ('MONTH','QUARTER','YEAR')", name="budgets_period_check"),
    CheckConstraint("mode in ('INDEPENDENT','SUBDIVISION')", name="budgets_mode_check"),
    CheckConstraint("policy in ('MONITOR','SOFT','HARD','APPROVAL')", name="budgets_policy_check"),
    CheckConstraint("fail_mode in ('FAIL_OPEN','FAIL_CLOSED')", name="budgets_fail_mode_check"),
    CheckConstraint(
        "committed_micros >= 0 and reserved_micros >= 0", name="budgets_counters_check"
    ),
    CheckConstraint(
        "mode = 'INDEPENDENT' or parent_id is not null", name="budgets_subdivision_parent_check"
    ),
    UniqueConstraint(
        "tenant_id",
        "scope_type",
        "scope_id",
        "period",
        "period_start",
        name="budgets_scope_period_key",
    ),
)

vendors = Table(
    "vendors",
    metadata,
    Column("tenant_id", Uuid, ForeignKey("tenants.id"), primary_key=True),
    Column("id", Text, primary_key=True),
    Column("status", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("version", BigInteger, nullable=False, server_default=text("1")),
    CheckConstraint("status in ('ALLOWED','BLOCKED')", name="vendors_status_check"),
)

models = Table(
    "models",
    metadata,
    Column("tenant_id", Uuid, primary_key=True),
    Column("id", Text, primary_key=True),
    Column("vendor_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("input_price_micros_per_1k", BigInteger, nullable=False),
    Column("output_price_micros_per_1k", BigInteger, nullable=False),
    Column("price_currency", String(3), nullable=False),
    Column("max_output_tokens", Integer, nullable=False),
    Column("price_version", Integer, nullable=False, server_default=text("1")),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("version", BigInteger, nullable=False, server_default=text("1")),
    ForeignKeyConstraint(
        ["tenant_id", "vendor_id"], ["vendors.tenant_id", "vendors.id"], name="models_vendor_fkey"
    ),
    CheckConstraint("status in ('ALLOWED','BLOCKED')", name="models_status_check"),
    CheckConstraint(
        "input_price_micros_per_1k >= 0 and output_price_micros_per_1k >= 0 and max_output_tokens > 0",
        name="models_price_check",
    ),
    CheckConstraint("id = lower(btrim(id))", name="models_id_canonical_check"),
)

model_aliases = Table(
    "model_aliases",
    metadata,
    Column("tenant_id", Uuid, primary_key=True),
    Column("alias", Text, primary_key=True),
    Column("model_id", Text, nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "model_id"],
        ["models.tenant_id", "models.id"],
        name="model_aliases_model_fkey",
    ),
    CheckConstraint("alias = lower(btrim(alias))", name="model_aliases_canonical_check"),
)

# Who changed a registry status, when and why (UX-3). The hash-chained audit
# log of phase 6 will also record these.
registry_changes = Table(
    "registry_changes",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("tenant_id", Uuid, ForeignKey("tenants.id"), nullable=False),
    Column("subject_type", Text, nullable=False),
    Column("subject_id", Text, nullable=False),
    Column("before_status", Text, nullable=False),
    Column("after_status", Text, nullable=False),
    Column("actor", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("changed_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("subject_type in ('vendor','model')", name="registry_changes_subject_check"),
)

# Model names that were requested but are not registered (D-03). There is no
# row in `models` for these: unknown means denied.
unregistered_models = Table(
    "unregistered_models",
    metadata,
    Column("tenant_id", Uuid, ForeignKey("tenants.id"), primary_key=True),
    Column("requested_name", Text, primary_key=True),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("seen_count", Integer, nullable=False),
    CheckConstraint("seen_count > 0", name="unregistered_models_count_check"),
)
