"""Phase 0 foundation tables: heartbeats, alerts, app_meta, demo_placeholder.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "heartbeats",
        sa.Column("component", sa.Text, primary_key=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("component", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.CheckConstraint("severity in ('SEV1','SEV2','SEV3')", name="alerts_severity_check"),
    )
    op.create_table(
        "app_meta",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )
    op.create_table(
        "demo_placeholder",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("amount_micro", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.CheckConstraint("amount_micro >= 0", name="demo_placeholder_amount_check"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="demo_placeholder_currency_check"),
    )


def downgrade() -> None:
    op.drop_table("demo_placeholder")
    op.drop_table("app_meta")
    op.drop_table("alerts")
    op.drop_table("heartbeats")
