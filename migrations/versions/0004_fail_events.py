"""Phase 3: fail-open events.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "fail_events",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("budget_id", sa.Uuid, sa.ForeignKey("budgets.id")),
        sa.Column("reservation_id", sa.Uuid),
        sa.Column("agent", sa.Text),
        sa.Column("project", sa.Text),
        sa.Column("model_id", sa.Text),
        sa.Column("amount_micros", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("usage_known", sa.Boolean, nullable=False),
        sa.Column("detail", JSONB, nullable=False),
        sa.Column("replayed_at", TS, nullable=False),
        sa.Column("acknowledged_at", TS),
        sa.Column("acknowledged_by", sa.Text),
        sa.CheckConstraint(
            "kind in ('FAIL_OPEN','FAIL_CLOSED','SNAPSHOT_STALE','RESERVATION_EXPIRED','UNCONTROLLED_SPEND')",
            name="fail_events_kind_check",
        ),
        sa.CheckConstraint("amount_micros >= 0", name="fail_events_amount_check"),
    )


def downgrade() -> None:
    op.drop_table("fail_events")
