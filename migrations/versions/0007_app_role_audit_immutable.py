"""Phase 6: a restricted database role for the running services, and an audit
record that cannot be changed.

Revision ID: 0007
Revises: 0006

The services (UI and gateway) connect as ``keepair_app``. Migrations and the
demo seed run as the owner. The application role may read and append audit
records, and nothing else on them. Triggers refuse UPDATE and DELETE for every
role; only the table owner could switch them off, and the services are not it.
"""

import os
import re

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

ROLE = "keepair_app"

IMMUTABLE = """
CREATE FUNCTION audit_log_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'AUDIT_IMMUTABLE: audit records cannot be changed or deleted'
    USING ERRCODE = 'insufficient_privilege';
END $$ LANGUAGE plpgsql;
CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
"""


def _password() -> str:
    # A local default, like the database password in docker-compose.yml. Real
    # deployments set KEEPAIR_APP_DB_PASSWORD from their own secret store.
    value = os.environ.get("KEEPAIR_APP_DB_PASSWORD", "keepair_app")  # pragma: allowlist secret
    if not re.fullmatch(r"[A-Za-z0-9_.-]{8,128}", value):
        raise SystemExit("KEEPAIR_APP_DB_PASSWORD must be 8 to 128 characters of A-Z a-z 0-9 _ . -")
    return value


def upgrade() -> None:
    password = _password()  # validated above: letters, digits, _ . - only
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN "
        f"CREATE ROLE {ROLE} LOGIN PASSWORD '{password}'; "
        f"ELSE ALTER ROLE {ROLE} LOGIN PASSWORD '{password}'; END IF; END $$"
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {ROLE}"
    )
    # The audit record: read and append only. The chain head: read and move forward only.
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM {ROLE}")
    op.execute(f"REVOKE INSERT, DELETE, TRUNCATE ON audit_head FROM {ROLE}")
    op.execute(f"REVOKE ALL ON alembic_version FROM {ROLE}")
    op.execute(IMMUTABLE)


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_log_no_change ON audit_log")
    op.execute("DROP FUNCTION audit_log_immutable()")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "  # noqa: S608  (ROLE is a constant)
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {ROLE}"
    )
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE}")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {ROLE}")
    op.execute(f"REVOKE ALL ON SCHEMA public FROM {ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {ROLE}")
