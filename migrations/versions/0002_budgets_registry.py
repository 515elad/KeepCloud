"""Phase 1: tenants, hierarchy, projects, budgets, vendor and model registry.

Drops the phase 0 placeholder table.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.drop_table("demo_placeholder")
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
    )
    op.create_table(
        "org_units",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("parent_id", sa.Uuid, sa.ForeignKey("org_units.id")),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.CheckConstraint("kind in ('ORG','DEPT','TEAM')", name="org_units_kind_check"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("team_id", sa.Uuid, sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("key_custody", sa.Text, nullable=False, server_default="KEEPAIR"),
        sa.Column("egress_verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint(
            "key_custody in ('KEEPAIR','CUSTOMER')", name="projects_key_custody_check"
        ),
    )
    op.create_table(
        "budgets",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("parent_id", sa.Uuid, sa.ForeignKey("budgets.id")),
        sa.Column("scope_type", sa.Text, nullable=False),
        sa.Column("scope_id", sa.Uuid, nullable=False),
        sa.Column("cap_micros", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("period", sa.Text, nullable=False),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("mode", sa.Text, nullable=False, server_default="INDEPENDENT"),
        sa.Column("policy", sa.Text, nullable=False),
        sa.Column("fail_mode", sa.Text, nullable=False),
        sa.Column("owner_user_id", sa.Uuid),
        sa.Column("committed_micros", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("reserved_micros", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("version", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint(
            "scope_type in ('ORG','BU','DEPT','TEAM','PROJECT','APP','AGENT')",
            name="budgets_scope_type_check",
        ),
        sa.CheckConstraint("cap_micros >= 0", name="budgets_cap_check"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="budgets_currency_check"),
        sa.CheckConstraint("period in ('MONTH','QUARTER','YEAR')", name="budgets_period_check"),
        sa.CheckConstraint("mode in ('INDEPENDENT','SUBDIVISION')", name="budgets_mode_check"),
        sa.CheckConstraint(
            "policy in ('MONITOR','SOFT','HARD','APPROVAL')", name="budgets_policy_check"
        ),
        sa.CheckConstraint(
            "fail_mode in ('FAIL_OPEN','FAIL_CLOSED')", name="budgets_fail_mode_check"
        ),
        sa.CheckConstraint(
            "committed_micros >= 0 and reserved_micros >= 0", name="budgets_counters_check"
        ),
        sa.CheckConstraint(
            "mode = 'INDEPENDENT' or parent_id is not null", name="budgets_subdivision_parent_check"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "scope_type",
            "scope_id",
            "period",
            "period_start",
            name="budgets_scope_period_key",
        ),
    )
    op.create_table(
        "vendors",
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("version", sa.BigInteger, nullable=False, server_default=sa.text("1")),
        sa.CheckConstraint("status in ('ALLOWED','BLOCKED')", name="vendors_status_check"),
    )
    op.create_table(
        "models",
        sa.Column("tenant_id", sa.Uuid, primary_key=True),
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("vendor_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("input_price_micros_per_1k", sa.BigInteger, nullable=False),
        sa.Column("output_price_micros_per_1k", sa.BigInteger, nullable=False),
        sa.Column("price_currency", sa.String(3), nullable=False),
        sa.Column("max_output_tokens", sa.Integer, nullable=False),
        sa.Column("price_version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("version", sa.BigInteger, nullable=False, server_default=sa.text("1")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "vendor_id"],
            ["vendors.tenant_id", "vendors.id"],
            name="models_vendor_fkey",
        ),
        sa.CheckConstraint("status in ('ALLOWED','BLOCKED')", name="models_status_check"),
        sa.CheckConstraint(
            "input_price_micros_per_1k >= 0 and output_price_micros_per_1k >= 0 and max_output_tokens > 0",
            name="models_price_check",
        ),
        sa.CheckConstraint("id = lower(btrim(id))", name="models_id_canonical_check"),
    )
    op.create_table(
        "model_aliases",
        sa.Column("tenant_id", sa.Uuid, primary_key=True),
        sa.Column("alias", sa.Text, primary_key=True),
        sa.Column("model_id", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "model_id"],
            ["models.tenant_id", "models.id"],
            name="model_aliases_model_fkey",
        ),
        sa.CheckConstraint("alias = lower(btrim(alias))", name="model_aliases_canonical_check"),
    )
    op.create_table(
        "registry_changes",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("subject_type", sa.Text, nullable=False),
        sa.Column("subject_id", sa.Text, nullable=False),
        sa.Column("before_status", sa.Text, nullable=False),
        sa.Column("after_status", sa.Text, nullable=False),
        sa.Column("actor", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("changed_at", TS, nullable=False),
        sa.CheckConstraint(
            "subject_type in ('vendor','model')", name="registry_changes_subject_check"
        ),
    )
    op.create_table(
        "unregistered_models",
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("requested_name", sa.Text, primary_key=True),
        sa.Column("first_seen_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False),
        sa.Column("seen_count", sa.Integer, nullable=False),
        sa.CheckConstraint("seen_count > 0", name="unregistered_models_count_check"),
    )


def downgrade() -> None:
    for table in (
        "unregistered_models",
        "registry_changes",
        "model_aliases",
        "models",
        "vendors",
        "budgets",
        "projects",
        "org_units",
        "tenants",
    ):
        op.drop_table(table)
    op.create_table(
        "demo_placeholder",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("amount_micro", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.CheckConstraint("amount_micro >= 0", name="demo_placeholder_amount_check"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="demo_placeholder_currency_check"),
    )
