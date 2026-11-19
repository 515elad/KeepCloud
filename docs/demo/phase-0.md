# Phase 0 demo script

Time: about 5 minutes. Needs Docker. No account, key or internet service is used.

## Start

1. In the repo folder run:

   ```bash
   docker compose up --build
   ```

   **Expect:** after the build, a line saying `Demo data loaded (seed 20260115, clock 2026-01-15T09:00:00Z)` and then `Uvicorn running`.

2. Open <http://localhost:8000>.

   **Expect:** the Overview page. A hatched band at the top reads **DEMO** "Generated sample data. Nothing shown here is real spend."

## The shell

3. Click each item in the left navigation: Overview, Budgets, Gateway, Approvals, Reconciliation, Reports, Admin, Audit log.

   **Expect:** every page opens, keeps the DEMO band, and lists what is not built yet as "Coming in phase N" with PRD requirement IDs (for example Gateway: "Denials feed, Coming in phase 2, FR-05, UX-5").

## The health strip

4. Look at the strip next to the KeepAir name.

   **Expect:** Gateway, Policy sync, Ledger, Egress, Alerting and Data sources each show a dashed "?" and the word **Unknown**. Nothing is green.

5. On Overview, read the "Component health" table.

   **Expect:** every row is Unknown with last heartbeat "never". Egress says "Not part of the MVP phases (FR-20)".

## The "i" information system

6. On Overview, click the round **i** next to "Placeholder amount".

   **Expect:** a panel with the name and meaning, unit (USD, micro-units), source, the formula `display_amount = amount_micro / 1,000,000`, a worked example (`amount_micro = 2050000000`, result `2,050.00 USD`, the same number shown on the page), allowed range, validation, and the PRD reference.

7. Press **Esc**. Then press **Tab** until an **i** button has focus.

   **Expect:** Esc closes the panel. Focusing an **i** with the keyboard opens its panel; tabbing on closes it.

8. Click the **i** in the "Status" column header.

   **Expect:** the formula for Healthy, Degraded, Failing and Unknown, and a worked example for the gateway component: no heartbeat, result Unknown.

## A visible failure

9. In a second terminal run:

   ```bash
   docker compose stop db
   ```

   Reload <http://localhost:8000>.

   **Expect:** a red notice "The database cannot be reached…", both placeholders read "Not loaded", health stays Unknown, and the Alerts table has a row: `SEV2`, `DATABASE_UNREACHABLE`, component `ledger`, marked "Held in memory until the database is back."

10. Open <http://localhost:8000/metrics>.

    **Expect:** a line `keepair_failures_total{code="DATABASE_UNREACHABLE"}` with a count of 1 or more.

11. Run:

    ```bash
    docker compose start db
    ```

    Wait 10 seconds and reload the Overview page.

    **Expect:** the red notice is gone, the placeholders are back, and the alert row is still listed (now stored in the database).

## Stop

12. Press Ctrl+C in the first terminal, then run:

    ```bash
    docker compose down -v
    ```

## Not in this phase

Budgets, vendors and models, the gateway, sign-in, approvals, reports and the audit log. Each page names the phase that brings them.
