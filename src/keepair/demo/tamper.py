"""Demo only: change one audit record behind the application's back.

Run with:  python -m keepair.demo.tamper     (or ./run.sh tamper)

It shows what the chain check on the Audit log page is for. The application
role cannot do this: UPDATE on the audit record is revoked from it and a trigger
refuses the statement. This script connects as the owner of the tables and
switches the trigger off for one statement, which is what a database
administrator with full rights could do.
"""

from __future__ import annotations

from sqlalchemy import Connection, select, text

from keepair.config import Settings
from keepair.db import make_owner_engine
from keepair.schema import app_meta, audit_log

NEW_REASON = "Edited outside the application."


class NotDemoData(RuntimeError):
    """This script only ever touches a demo database."""


def tamper(conn: Connection) -> int:
    """Rewrite the reason of the newest registry block. Returns the record number."""
    demo = conn.execute(select(app_meta.c.value).where(app_meta.c.key == "demo")).scalar()
    if demo != "true":
        raise NotDemoData("not a demo database")
    seq = conn.execute(
        select(audit_log.c.seq)
        .where(audit_log.c.action == "registry.blocked")
        .order_by(audit_log.c.seq.desc())
        .limit(1)
    ).scalar_one()
    conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_change"))
    conn.execute(
        text("UPDATE audit_log SET reason = :reason WHERE seq = :seq"),
        {"reason": NEW_REASON, "seq": seq},
    )
    conn.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_change"))
    return seq


if __name__ == "__main__":
    _settings = Settings()
    if _settings.env == "prod":
        raise SystemExit("Refusing to run in production.")
    with make_owner_engine(_settings).begin() as _conn:
        _seq = tamper(_conn)
    print(f"Audit record {_seq} was changed directly in the database.")
    print("Open the Audit log page and press 'Verify the chain'.")
