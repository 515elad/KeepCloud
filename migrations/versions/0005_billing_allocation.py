"""Phase 4: billing ingestion, normalized cost records, allocation.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("usage_events", sa.Column("price_micros", sa.BigInteger))
    op.add_column("usage_events", sa.Column("price_currency", sa.String(3)))
    op.create_table(
        "ingestion_batches",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("file_name", sa.Text, nullable=False),
        sa.Column("file_sha256", sa.LargeBinary, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("rows_total", sa.Integer, nullable=False),
        sa.Column("rows_new", sa.Integer, nullable=False),
        sa.Column("rows_revised", sa.Integer, nullable=False),
        sa.Column("rows_unchanged", sa.Integer, nullable=False),
        sa.Column("reasons", JSONB, nullable=False),
        sa.Column("actor", sa.Text, nullable=False),
        sa.Column("ingested_at", TS, nullable=False),
        sa.CheckConstraint(
            "status in ('LOADED','QUARANTINED')", name="ingestion_batches_status_check"
        ),
    )
    op.create_table(
        "raw_billing_records",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("batch_id", sa.Uuid, sa.ForeignKey("ingestion_batches.id"), nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("record_key", sa.Text, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("payload_hash", sa.LargeBinary, nullable=False),
        sa.Column("ingested_at", TS, nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "source", "record_key", "revision", name="raw_billing_records_key"
        ),
        sa.CheckConstraint("revision >= 1", name="raw_billing_records_revision_check"),
    )
    op.create_table(
        "normalized_cost_records",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("raw_id", sa.BigInteger, sa.ForeignKey("raw_billing_records.id"), nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("record_key", sa.Text, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("is_current", sa.Boolean, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("model_id", sa.Text, nullable=False),
        sa.Column("charge_date", sa.Date, nullable=False),
        sa.Column("billing_period", sa.Date, nullable=False),
        sa.Column("billed_micros", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("finalization_state", sa.Text, nullable=False),
        sa.Column("consumed_quantity", sa.BigInteger, nullable=False),
        sa.Column("consumed_unit", sa.Text, nullable=False),
        sa.Column("tags", JSONB, nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "source", "record_key", "revision", name="normalized_cost_records_key"
        ),
        sa.CheckConstraint(
            "finalization_state in ('PROVIDER_REPORTED','INVOICED')",
            name="normalized_cost_records_state_check",
        ),
        sa.CheckConstraint("billed_micros >= 0", name="normalized_cost_records_amount_check"),
    )
    op.create_table(
        "allocation_rules",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date),
        sa.Column("match", JSONB, nullable=False),
        sa.Column("split", JSONB, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
    )
    op.create_table(
        "manual_allocations",
        sa.Column("tenant_id", sa.Uuid, primary_key=True),
        sa.Column("source", sa.Text, primary_key=True),
        sa.Column("record_key", sa.Text, primary_key=True),
        sa.Column("project_id", sa.Uuid, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("actor", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("assigned_at", TS, nullable=False),
    )
    op.create_table(
        "allocation_facts",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "record_id", sa.Uuid, sa.ForeignKey("normalized_cost_records.id"), nullable=False
        ),
        sa.Column("project_id", sa.Uuid, sa.ForeignKey("projects.id")),
        sa.Column("amount_micros", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("confidence", sa.Text),
        sa.Column("join_confidence", sa.Integer, nullable=False),
        sa.Column("rule_id", sa.Uuid),
        sa.Column("rule_version", sa.Integer),
        sa.Column("explanation", sa.Text, nullable=False),
        sa.Column("is_current", sa.Boolean, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint(
            "state in ('ALLOCATED','REVIEW','UNMATCHED','UNALLOCATED')",
            name="allocation_facts_state_check",
        ),
        sa.CheckConstraint(
            "confidence is null or confidence in ('DIRECT','INFERRED','MANUAL')",
            name="allocation_facts_confidence_check",
        ),
        sa.CheckConstraint("join_confidence between 0 and 100", name="allocation_facts_join_check"),
        sa.CheckConstraint(
            "(state in ('ALLOCATED','REVIEW')) = (project_id is not null and confidence is not null)",
            name="allocation_facts_shape_check",
        ),
    )
    op.create_index("allocation_facts_current_idx", "allocation_facts", ["tenant_id", "is_current"])


def downgrade() -> None:
    for table in (
        "allocation_facts",
        "manual_allocations",
        "allocation_rules",
        "normalized_cost_records",
        "raw_billing_records",
        "ingestion_batches",
    ):
        op.drop_table(table)
    op.drop_column("usage_events", "price_currency")
    op.drop_column("usage_events", "price_micros")
