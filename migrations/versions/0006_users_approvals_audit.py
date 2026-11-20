"""Phase 5: users, sessions, approvals, kill switch, audit record, owner rule.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
STATES_OLD = "state in ('HELD','RESERVED','SETTLED','RELEASED','EXPIRED','UNKNOWN')"
STATES_NEW = "state in ('HELD','APPROVED','RESERVED','SETTLED','RELEASED','EXPIRED','UNKNOWN')"

# FR-17: a hard limit needs an accountable, active owner. The service checks this
# too; the triggers make it true whatever writes to the tables.
OWNER_RULE = """
CREATE FUNCTION budgets_hard_owner_check() RETURNS trigger AS $$
BEGIN
  IF NEW.policy = 'HARD' AND NOT EXISTS (
    SELECT 1 FROM users u WHERE u.id = NEW.owner_user_id AND u.status = 'ACTIVE'
  ) THEN
    RAISE EXCEPTION 'NO_OWNER: a hard limit needs an active owner'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER budgets_hard_owner BEFORE INSERT OR UPDATE OF policy, owner_user_id ON budgets
  FOR EACH ROW EXECUTE FUNCTION budgets_hard_owner_check();
CREATE FUNCTION users_hard_owner_check() RETURNS trigger AS $$
BEGIN
  IF NEW.status <> 'ACTIVE' AND EXISTS (
    SELECT 1 FROM budgets b WHERE b.owner_user_id = NEW.id AND b.policy = 'HARD'
  ) THEN
    RAISE EXCEPTION 'OWNS_HARD_LIMIT: this user owns a hard-limit budget'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER users_hard_owner BEFORE UPDATE OF status ON users
  FOR EACH ROW EXECUTE FUNCTION users_hard_owner_check();
"""


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("username", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("totp_secret_enc", sa.LargeBinary, nullable=False),
        sa.Column("totp_last_step", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("failed_attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", TS),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("created_by", sa.Text, nullable=False),
        sa.UniqueConstraint("tenant_id", "username", name="users_username_key"),
        sa.CheckConstraint(
            "role in ('ADMIN','FINANCE','ENGINEERING','AUDITOR')", name="users_role_check"
        ),
        sa.CheckConstraint("status in ('ACTIVE','DISABLED')", name="users_status_check"),
        sa.CheckConstraint("username ~ '^[a-z][a-z0-9._-]{2,39}$'", name="users_username_check"),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.LargeBinary, primary_key=True),
        sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False),
        sa.Column("mfa_verified", sa.Boolean, nullable=False),
        sa.CheckConstraint("octet_length(token_hash) = 32", name="sessions_hash_check"),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("subject_type", sa.Text, nullable=False),
        sa.Column("subject_id", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("requested_by", sa.Uuid, sa.ForeignKey("users.id")),
        sa.Column("requested_by_name", sa.Text, nullable=False),
        sa.Column("requested_at", TS, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("decision", sa.Text),
        sa.Column("decided_by", sa.Uuid, sa.ForeignKey("users.id")),
        sa.Column("decided_by_name", sa.Text),
        sa.Column("decided_at", TS),
        sa.CheckConstraint(
            "kind in ('HELD_REQUEST','BLOCK_LIFT','KILL_SWITCH_OFF','OWNER_CHANGE',"
            "'POLICY_CHANGE')",
            name="approvals_kind_check",
        ),
        sa.CheckConstraint(
            "decision is null or decision in ('APPROVED','REJECTED','EXPIRED','CANCELLED')",
            name="approvals_decision_check",
        ),
        sa.CheckConstraint(
            "decided_by is null or requested_by is null or decided_by <> requested_by "
            "or decision = 'CANCELLED'",
            name="approvals_two_person_check",
        ),
    )
    op.create_index(
        "approvals_pending_idx",
        "approvals",
        ["tenant_id"],
        postgresql_where=sa.text("decision is null"),
    )
    op.create_table(
        "kill_switches",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("tenant_id", sa.Uuid, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("scope_type", sa.Text, nullable=False),
        sa.Column("scope_id", sa.Text, nullable=False),
        sa.Column("scope_name", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("activated_by", sa.Uuid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("activated_by_name", sa.Text, nullable=False),
        sa.Column("activated_at", TS, nullable=False),
        sa.Column("deactivated_at", TS),
        sa.Column("deactivated_by_name", sa.Text),
        sa.CheckConstraint(
            "scope_type in ('GLOBAL','VENDOR','PROJECT')", name="kill_switches_scope_check"
        ),
    )
    op.create_index(
        "kill_switches_active_key",
        "kill_switches",
        ["tenant_id", "scope_type", "scope_id"],
        unique=True,
        postgresql_where=sa.text("deactivated_at is null"),
    )
    op.create_table(
        "audit_log",
        sa.Column("seq", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("tenant_id", sa.Uuid),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("actor", sa.Text, nullable=False),
        sa.Column("actor_id", sa.Uuid),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("subject_type", sa.Text, nullable=False),
        sa.Column("subject_id", sa.Text, nullable=False),
        sa.Column("before", JSONB),
        sa.Column("after", JSONB),
        sa.Column("reason", sa.Text),
        sa.Column("prev_hash", sa.LargeBinary, nullable=False),
        sa.Column("row_hash", sa.LargeBinary, nullable=False),
        sa.CheckConstraint(
            "octet_length(prev_hash) = 32 and octet_length(row_hash) = 32",
            name="audit_log_hash_check",
        ),
    )
    op.create_table(
        "audit_head",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("seq", sa.BigInteger, nullable=False),
        sa.Column("row_hash", sa.LargeBinary, nullable=False),
        sa.CheckConstraint("id = 1", name="audit_head_single_row_check"),
    )
    op.execute(
        "INSERT INTO audit_head (id, seq, row_hash) VALUES (1, 0, decode(repeat('00', 32), 'hex'))"
    )
    op.add_column("reservations", sa.Column("request_hash", sa.LargeBinary))
    op.drop_constraint("reservations_state_check", "reservations")
    op.create_check_constraint("reservations_state_check", "reservations", STATES_NEW)
    op.create_index(
        "reservations_hold_idx",
        "reservations",
        ["agent_id", "request_hash"],
        postgresql_where=sa.text("state in ('HELD','APPROVED')"),
    )
    # The triggers below check rows when they are written. Rows that already exist are
    # not rewritten here; the demo seed reloads every budget with its owner.
    op.create_foreign_key("budgets_owner_fkey", "budgets", "users", ["owner_user_id"], ["id"])
    op.execute(OWNER_RULE)


def downgrade() -> None:
    op.execute("DROP TRIGGER users_hard_owner ON users")
    op.execute("DROP FUNCTION users_hard_owner_check()")
    op.execute("DROP TRIGGER budgets_hard_owner ON budgets")
    op.execute("DROP FUNCTION budgets_hard_owner_check()")
    op.drop_constraint("budgets_owner_fkey", "budgets")
    op.drop_index("reservations_hold_idx", "reservations")
    op.execute("UPDATE reservations SET state = 'HELD' WHERE state = 'APPROVED'")
    op.drop_constraint("reservations_state_check", "reservations")
    op.create_check_constraint("reservations_state_check", "reservations", STATES_OLD)
    op.drop_column("reservations", "request_hash")
    for table in ("audit_head", "audit_log", "kill_switches", "approvals", "sessions", "users"):
        op.drop_table(table)
