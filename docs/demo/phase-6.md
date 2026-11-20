# Phase 6 demo script

Time: about 6 minutes. Needs Docker. All data is generated demo material.

If you chose another port, use it wherever this script says 8000.

## Start

1. Run:

   ```bash
   ./run.sh
   ```

2. Open <http://localhost:8000> and sign in as `alice.admin` (the sign-in page shows the demo password and then the authenticator code).

3. Optional, to have provider figures in the report: open **Spend**, scroll to "Load a billing file", and load `demo/billing/vendor-a-usage-2026-01.csv`.

## Showback report and CSV export

4. Open **Reports**.

   **Expect:** "Showback for 2026-01": one row per project with department, team, owner and three amount columns: Estimated, Provider-reported, Invoiced. Without step 3 the last two say "No data", not zero. The foot row carries one state chip per column. Call Notes shows "Unowned".

5. Click **Download as CSV** and open the file.

   **Expect:** `keepair-showback-2026-01.csv` with a header row and 13 rows. Amounts have six decimals and are exact, for example `22000.000000`.

6. Formula neutralization. Open **Admin**, "Add a user": user name `mallory.m`, name `=HYPERLINK("http://evil.example","click")`, role Finance, the code, **Add user**. Then open **Budgets**, click **Call Notes**, assign `mallory.m` as owner (reason `Testing the export.`, the code).

7. Open **Reports** and download the CSV again. Open it in a text editor.

   **Expect:** in the Call Notes row the owner cell starts with an apostrophe: `"'=HYPERLINK(...)"`. A spreadsheet shows it as text and does not run it. On the Reports page itself the name is shown as plain text.

## Audit log and verification

8. Open **Audit log**.

   **Expect:** every action you took, newest first: who, when, the action code (for example `report.exported`, `user.created`, `budget.owner_changed`), on what, the reason, the values before and after, and a short hash. The oldest eight records are the seeded history.

9. Click **Verify the chain**.

   **Expect:** "Chain verified. N records were recomputed and every one matches."

10. Tamper with one record behind the application's back. In the terminal:

    ```bash
    ./run.sh tamper
    ```

    **Expect:** "Audit record 8 was changed directly in the database."

    This connects as the owner of the tables and switches a protection off for one statement. The application itself cannot do it: its database role may only read and append audit records.

11. Reload **Audit log**. Find record 8.

    **Expect:** its reason now reads "Edited outside the application." Nothing on the row itself tells you.

12. Click **Verify the chain**.

    **Expect:** a red box: "Chain broken at record 8. Record 8 was changed after it was written. 7 records before it are intact. A SEV1 alert AUDIT_CHAIN_BROKEN was raised."

13. Open **Overview**, section "Alerts".

    **Expect:** a row with ▲ SEV1, `AUDIT_CHAIN_BROKEN`.

14. Put the demo data back:

    ```bash
    ./run.sh reset
    ```

    Sign in again and verify once more: the chain is intact.

## Stop

15. `./run.sh stop`

## What this does not protect against

Someone with full rights on the database could rewrite every record and the stored chain head so that the chain verifies again. Detecting that needs a signed copy of the head kept outside the database (PRD SEC-32). That part is not built.
