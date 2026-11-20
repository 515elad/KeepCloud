# Phase 3 demo script

Time: about 8 minutes. Needs Docker. No account, key or internet service is used.

If you chose another port (for example `KEEPAIR_UI_PORT=8100 ./run.sh`), it is remembered: use that port wherever this script says 8000.

## Start

1. Run:

   ```bash
   ./run.sh
   ```

   **Expect:** "KeepAir is running." and the summary of 500 demo requests.

2. Open <http://localhost:8000> in **two browser tabs**. In the first, click **Budgets**. In the second, click **Admin**.

   **Expect:** no banner. On Admin, a **Demo console** with "Ledger, as the gateway sees it: Running".

## Before the outage

3. On Admin, click **Send 8 test requests**.

   **Expect:** four "Sent" (`ALLOWED`), one held (`APPROVAL_REQUIRED`), and three "Not sent": `VENDOR_BLOCKED`, `MODEL_BLOCKED`, `UNKNOWN_MODEL`. The column "Budgets on its path" says which agents have only monitor and soft budgets.

## Stop the ledger

4. Click **Stop the ledger**. Then look at the **first tab** (Budgets) without touching it.

   **Expect:** on Admin, a red banner at once: "Fail-open is active … 0 requests were sent without a budget check". Within 5 seconds the same banner appears on the Budgets tab by itself.

5. On Admin, click **Send 8 test requests** again.

   **Expect:**
   - `ticket-triage-agent` and `reply-drafts-agent` (monitor and soft only): **Sent**, "Sent without a budget check while the ledger was down" `FAIL_OPEN`.
   - `build-assistant-agent`, `log-summarizer-agent`, `research-agent` (a hard limit or approval on the path): **Not sent**, `BUDGET_FAIL_CLOSED`.
   - The three blocked or unregistered models are refused exactly as before. Blocks do not fail open.
   - The banner now counts 2 requests.

6. Look at the **Acknowledge** button in the banner.

   **Expect:** it is disabled: "It can be acknowledged once the ledger is back and the spool is replayed."

7. Click **Open the fail-open report** in the banner.

   **Expect:** Fail-open "Active", Waiting in the spool 2, Recorded 0. The two requests are in the encrypted spool, not yet in the ledger.

## Restore

8. Go back to **Admin** and click **Restore the ledger**.

   **Expect:** the ledger shows Running. The banner turns amber: "Fail-open happened and is not acknowledged. 2 requests were sent without a budget check between … and …. They are now in the ledger."

9. Click **Open the fail-open report**.

   **Expect:** Waiting 0, Recorded 2, Not acknowledged 2. A row for each request: time, agent, budget, model, amount (shown with extra decimals because it is below one cent), "Reported by the vendor", when it was written to the ledger, and "Not yet" under Acknowledged.

10. Click **Budgets**.

    **Expect:** the banner is still there. It is on every page.

11. Click **Acknowledge** in the banner.

    **Expect:** the banner disappears on every page. The report shows the time and `demo-operator` under Acknowledged.

12. Click **Overview** and look at **Alerts**.

    **Expect:** a `FAIL_OPEN` alert, and a `DATABASE_UNREACHABLE` alert for the refused hard-limit requests.

## A real database stop (optional, 2 minutes)

13. On Admin, click **Send 8 test requests** (so the gateway has just seen the agents), then in a terminal run:

    ```bash
    docker compose stop db
    ```

    Within 20 seconds, click **Send 8 test requests** again.

    **Expect:** the same picture as step 5: two `FAIL_OPEN`, three `BUDGET_FAIL_CLOSED`, three blocked. The pages say the database cannot be reached, and the banner still shows, because the UI asks the gateway directly.

14. Wait one minute and click **Send 8 test requests** again.

    **Expect:** all eight are refused with `LEDGER_UNAVAILABLE`. After 30 seconds without the database the gateway can no longer verify credentials or policy, so it refuses everything.

15. Run `docker compose start db`, wait 15 seconds, reload.

    **Expect:** the spool has been replayed and the banner asks for acknowledgement.

## Stop

16. `./run.sh stop`

## Not in this phase

- Held requests cannot be approved yet (phase 5).
- A hard limit cannot be switched to fail open (decision D-01 is pending; the default is built).
- In a total database outage, fail-open lasts about 30 seconds, not an hour (assumption A-47).
