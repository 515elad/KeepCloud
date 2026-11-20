"""Phase 2: agents, credentials, vendor endpoints, FX rates, ledger and gateway records.

Also adds the rule that a project with a customer-held key cannot carry a
limiting budget (D-02, bypass route B-a).

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)

CUSTODY_RULE = """
CREATE FUNCTION keepair_check_custody() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM budgets b JOIN projects p ON p.id = b.scope_id
    WHERE b.scope_type = 'PROJECT' AND b.policy IN ('HARD','APPROVAL') AND p.key_custody = 'CUSTOMER'
  ) THEN
    RAISE EXCEPTION 'a project with a customer-held key cannot have a hard or approval budget (D-02)'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER budgets_custody_rule AFTER INSERT OR UPDATE ON budgets
  DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW EXECUTE FUNCTION keepair_check_custody();
CREATE CONSTRAINT TRIGGER projects_custody_rule AFTER INSERT OR UPDATE ON projects
  DEFERRABLE INITIALLY IMMEDIATE FOR EACH ROW EXECUTE FUNCTION keepair_check_custody();
"""


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("project_id", sa.Uuid, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "gateway_credentials",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("token_hash", sa.LargeBinary, nullable=False, unique=True),
        sa.Column("agent_id", sa.Uuid, sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS),
        sa.CheckConstraint("octet_length(token_hash) = 32", name="gateway_credentials_hash_check"),
        sa.CheckConstraint(
            "expires_at <= created_at + interval '90 days'",
            name="gateway_credentials_lifetime_check",
        ),
    )
    op.create_table(
        "vendor_endpoints",
        sa.Column("tenant_id", sa.Uuid, primary_key=True),
        sa.Column("vendor_id", sa.Text, primary_key=True),
        sa.Column("base_url", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "vendor_id"],
            ["vendors.tenant_id", "vendors.id"],
            name="vendor_endpoints_vendor_fkey",
        ),
        sa.CheckConstraint(
            "base_url ~ '^https?://[a-z0-9.-]+(:[0-9]+)?$'", name="vendor_endpoints_url_check"
        ),
    )
    op.create_table(
        "fx_rates",
        sa.Column("base", sa.String(3), primary_key=True),
        sa.Column("quote", sa.String(3), primary_key=True),
        sa.Column("effective_date", sa.Date, primary_key=True),
        sa.Column("rate_micros", sa.BigInteger, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint("rate_micros > 0", name="fx_rates_rate_check"),
    )
    op.create_table(
        "reservations",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("request_id", sa.Uuid, nullable=False),
        sa.Column("credential_id", sa.Uuid, sa.ForeignKey("gateway_credentials.id")),
        sa.Column("agent_id", sa.Uuid, sa.ForeignKey("agents.id")),
        sa.Column("budget_id", sa.Uuid, sa.ForeignKey("budgets.id"), nullable=False),
        sa.Column("budget_path", sa.ARRAY(sa.Uuid), nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("model_id", sa.Text),
        sa.Column("reserved_micros", sa.BigInteger, nullable=False),
        sa.Column("actual_micros", sa.BigInteger),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("price_version", sa.Integer),
        sa.Column("fx_rate_micros", sa.BigInteger),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("dispatched_at", TS),
        sa.Column("settled_at", TS),
        sa.Column("usage_known", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.CheckConstraint(
            "state in ('HELD','RESERVED','SETTLED','RELEASED','EXPIRED','UNKNOWN')",
            name="reservations_state_check",
        ),
        sa.CheckConstraint("reserved_micros >= 0", name="reservations_amount_check"),
    )
    op.create_index(
        "reservations_open_idx",
        "reservations",
        ["credential_id", "state"],
        postgresql_where=sa.text("state in ('RESERVED','HELD')"),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("agent_id", sa.Uuid, sa.ForeignKey("agents.id"), primary_key=True),
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("request_hash", sa.LargeBinary, nullable=False),
        sa.Column("reservation_id", sa.Uuid),
        sa.Column("response_status", sa.Integer),
        sa.Column("response_body", JSONB),
        sa.Column("created_at", TS, nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("reservation_id", sa.Uuid, sa.ForeignKey("reservations.id")),
        sa.Column("provider", sa.Text),
        sa.Column("model_id", sa.Text),
        sa.Column("agent_id", sa.Uuid),
        sa.Column("team", sa.Text),
        sa.Column("project", sa.Text),
        sa.Column("agent", sa.Text),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("actual_micros", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("usage_known", sa.Boolean, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("ingested_at", TS, nullable=False),
        sa.CheckConstraint(
            "source in ('GATEWAY','SDK','PROVIDER_API','INVOICE')", name="usage_events_source_check"
        ),
    )
    op.create_table(
        "gateway_decisions",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("agent_id", sa.Uuid),
        sa.Column("agent", sa.Text),
        sa.Column("project", sa.Text),
        sa.Column("requested_model", sa.Text),
        sa.Column("model_id", sa.Text),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("reason_code", sa.Text),
        sa.Column("http_status", sa.Integer, nullable=False),
        sa.Column("budget_id", sa.Uuid),
        sa.Column("reservation_id", sa.Uuid),
        sa.Column("snapshot_version", sa.BigInteger),
        sa.CheckConstraint(
            "outcome in ('ALLOWED','DENIED','HELD')", name="gateway_decisions_outcome_check"
        ),
    )
    op.create_index("gateway_decisions_time_idx", "gateway_decisions", ["tenant_id", "occurred_at"])
    op.execute(CUSTODY_RULE)


def downgrade() -> None:
    op.execute("DROP TRIGGER projects_custody_rule ON projects")
    op.execute("DROP TRIGGER budgets_custody_rule ON budgets")
    op.execute("DROP FUNCTION keepair_check_custody()")
    for table in (
        "gateway_decisions",
        "usage_events",
        "idempotency_keys",
        "reservations",
        "fx_rates",
        "vendor_endpoints",
        "gateway_credentials",
        "agents",
    ):
        op.drop_table(table)
