"""Routes for the showback report, its CSV export, and the audit record (phase 6)."""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response

from keepair import audit
from keepair.billing.finalization import Finalization
from keepair.exports import to_csv
from keepair.permissions import Perm, allowed
from keepair.web import record_views, spend_views

AUDIT_VERIFY_TOTAL = "keepair_audit_verify_total"


def register(ctx) -> None:
    app, engine = ctx.app, ctx.engine
    ctx.metrics.describe(AUDIT_VERIFY_TOTAL, "Audit chain verifications, by result.")

    def report_for(state, period_text: str | None):
        if not state.tenant_id:
            return None, []
        with engine.connect() as conn:
            found, default = spend_views.periods(conn, state.tenant_id)
            period = spend_views.parse_period(period_text, found, default)
            if period is None:
                return None, found
            return record_views.showback(conn, state.tenant_id, period), found

    @app.get("/reports", response_class=HTMLResponse)
    def reports(period: str | None = None) -> HTMLResponse:
        page, state = ctx.page_context("reports")
        report, periods = report_for(state, period)
        return ctx.render(
            "reports.html", page=page, state=state, report=report, periods=periods,
            can_export=allowed(ctx.actor().role, Perm.EXPORT_REPORTS),
            report_states=[Finalization.ESTIMATED, Finalization.PROVIDER_REPORTED,
                           Finalization.INVOICED],
        )  # fmt: skip

    @app.get("/reports/showback.csv")
    def showback_csv(period: str | None = None) -> Response:
        state = ctx.load_state()
        report, _ = report_for(state, period)
        if report is None:
            raise HTTPException(status_code=404)
        body = to_csv(record_views.SHOWBACK_HEADER, record_views.showback_csv_rows(report))
        name = f"keepair-showback-{report.period.strftime('%Y-%m')}.csv"
        with engine.begin() as conn:  # SEC-29: every export is recorded
            ctx.record(
                conn, state, "report.exported", "report", "showback",
                after={"period": report.period.strftime("%Y-%m"), "rows": len(report.rows),
                       "format": "csv"},
            )  # fmt: skip
        return Response(
            body.encode("utf-8-sig"),  # the byte-order mark makes spreadsheets read UTF-8
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "Cache-Control": "no-store",
            },
        )

    def audit_page(before: int | None = None, result=None, status_code: int = 200):
        page, state = ctx.page_context("audit-log")
        rows, total, older = [], 0, None
        if state.tenant_id:
            with engine.connect() as conn:
                rows, total, older = record_views.audit_rows(conn, state.tenant_id, before)
        return ctx.render(
            "audit_log.html", status_code=status_code, page=page, state=state, rows=rows,
            total=total, older=older, result=result,
            can_verify=allowed(ctx.actor().role, Perm.VERIFY_AUDIT),
        )  # fmt: skip

    @app.get("/audit-log", response_class=HTMLResponse)
    def audit_log_page(before: int | None = None) -> HTMLResponse:
        return audit_page(before)

    @app.post("/audit-log/verify", response_class=HTMLResponse)
    async def audit_verify() -> HTMLResponse:
        state = ctx.load_state()
        with engine.connect() as conn:
            result = audit.verify(conn)
        ctx.metrics.inc(AUDIT_VERIFY_TOTAL, result="ok" if result.ok else "broken")
        if not result.ok:
            ctx.reporter.report(
                "AUDIT_CHAIN_BROKEN",
                f"The audit record failed verification at record {result.broken_at}. "
                f"{result.problem} Treat every record from there on as untrusted.",
            )
        try:
            with engine.begin() as conn:
                ctx.record(
                    conn, state, "audit.verified", "audit_log", "chain",
                    after={"ok": result.ok, "checked": result.checked,
                           "broken_at": result.broken_at},
                )  # fmt: skip
        except audit.AuditUnavailable:
            pass  # the head is gone: the result above already says the chain is broken
        return audit_page(result=result, status_code=200 if result.ok else 409)
