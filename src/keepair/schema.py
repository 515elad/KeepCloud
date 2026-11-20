"""SQLAlchemy Core table definitions (phase 0: foundation tables only).

The business tables in PRD v1.4 Section 2.5 arrive with their phases.
"""

from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

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

# --- Phase 2: agents, credentials, ledger and gateway records ----------------

agents = Table(
    "agents",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, ForeignKey("tenants.id"), nullable=False),
    Column("project_id", Uuid, ForeignKey("projects.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

# Tokens are never stored: only their SHA-256 hash (hard rule 8, SEC-12).
gateway_credentials = Table(
    "gateway_credentials",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, ForeignKey("tenants.id"), nullable=False),
    Column("token_hash", LargeBinary, nullable=False, unique=True),
    Column("agent_id", Uuid, ForeignKey("agents.id"), nullable=False),
    Column("label", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    CheckConstraint("octet_length(token_hash) = 32", name="gateway_credentials_hash_check"),
    CheckConstraint(
        "expires_at <= created_at + interval '90 days'", name="gateway_credentials_lifetime_check"
    ),
)

# Where a vendor is reached. The gateway dispatches to these hosts only (SEC-02).
vendor_endpoints = Table(
    "vendor_endpoints",
    metadata,
    Column("tenant_id", Uuid, primary_key=True),
    Column("vendor_id", Text, primary_key=True),
    Column("base_url", Text, nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "vendor_id"],
        ["vendors.tenant_id", "vendors.id"],
        name="vendor_endpoints_vendor_fkey",
    ),
    CheckConstraint(
        "base_url ~ '^https?://[a-z0-9.-]+(:[0-9]+)?$'", name="vendor_endpoints_url_check"
    ),
)

# PRD v1.4 Section 6 (multi-currency): versioned rates, rate as micro-units of quote per base unit.
fx_rates = Table(
    "fx_rates",
    metadata,
    Column("base", String(3), primary_key=True),
    Column("quote", String(3), primary_key=True),
    Column("effective_date", Date, primary_key=True),
    Column("rate_micros", BigInteger, nullable=False),
    Column("source", Text, nullable=False),
    Column("version", Integer, nullable=False, server_default=text("1")),
    CheckConstraint("rate_micros > 0", name="fx_rates_rate_check"),
)

reservations = Table(
    "reservations",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, ForeignKey("tenants.id"), nullable=False),
    Column("request_id", Uuid, nullable=False),
    Column("credential_id", Uuid, ForeignKey("gateway_credentials.id")),
    Column("agent_id", Uuid, ForeignKey("agents.id")),
    Column("budget_id", Uuid, ForeignKey("budgets.id"), nullable=False),
    Column("budget_path", ARRAY(Uuid), nullable=False),
    Column("state", Text, nullable=False),
    Column("model_id", Text),
    Column("reserved_micros", BigInteger, nullable=False),
    Column("actual_micros", BigInteger),
    Column("currency", String(3), nullable=False),
    Column("price_version", Integer),
    Column("fx_rate_micros", BigInteger),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("dispatched_at", DateTime(timezone=True)),
    Column("settled_at", DateTime(timezone=True)),
    Column("usage_known", Boolean, nullable=False, server_default=text("true")),
    CheckConstraint(
        "state in ('HELD','RESERVED','SETTLED','RELEASED','EXPIRED','UNKNOWN')",
        name="reservations_state_check",
    ),
    CheckConstraint("reserved_micros >= 0", name="reservations_amount_check"),
    Index(
        "reservations_open_idx",
        "credential_id",
        "state",
        postgresql_where=text("state in ('RESERVED','HELD')"),
    ),
)

idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    Column("agent_id", Uuid, ForeignKey("agents.id"), primary_key=True),
    Column("key", Text, primary_key=True),
    Column("tenant_id", Uuid, ForeignKey("tenants.id"), nullable=False),
    Column("request_hash", LargeBinary, nullable=False),
    Column("reservation_id", Uuid),
    Column("response_status", Integer),
    Column("response_body", JSONB),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)

usage_events = Table(
    "usage_events",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("tenant_id", Uuid, ForeignKey("tenants.id"), nullable=False),
    Column("reservation_id", Uuid, ForeignKey("reservations.id")),
    Column("provider", Text),
    Column("model_id", Text),
    Column("agent_id", Uuid),
    Column("team", Text),
    Column("project", Text),
    Column("agent", Text),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("actual_micros", BigInteger, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("usage_known", Boolean, nullable=False),
    Column("source", Text, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("ingested_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "source in ('GATEWAY','SDK','PROVIDER_API','INVOICE')", name="usage_events_source_check"
    ),
)

# One row per gateway decision. For an allowed request it is written in the
# same transaction as the reservation: no record, no dispatch (SEC-06).
gateway_decisions = Table(
    "gateway_decisions",
    metadata,
    Column("id", Uuid, primary_key=True),  # the request ID
    Column("tenant_id", Uuid, ForeignKey("tenants.id"), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("agent_id", Uuid),
    Column("agent", Text),
    Column("project", Text),
    Column("requested_model", Text),
    Column("model_id", Text),
    Column("outcome", Text, nullable=False),
    Column("reason_code", Text),
    Column("http_status", Integer, nullable=False),
    Column("budget_id", Uuid),
    Column("reservation_id", Uuid),
    Column("snapshot_version", BigInteger),
    CheckConstraint(
        "outcome in ('ALLOWED','DENIED','HELD')", name="gateway_decisions_outcome_check"
    ),
    Index("gateway_decisions_time_idx", "tenant_id", "occurred_at"),
)
