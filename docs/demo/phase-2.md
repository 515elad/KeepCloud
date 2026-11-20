# Phase 2 demo script

Time: about 10 minutes. Needs Docker. No account, key or internet service is used: the "vendor" is a mock server in the same stack.

## Start

1. Run:

   ```bash
   docker compose up --build
   ```

   **Expect:** four services start: `db`, `app` (UI, port 8000), `gateway` (port 8080) and `mock-provider`. The app prints "Demo data loaded" and "12 demo gateway credentials issued".

2. Open <http://localhost:8000>.

   **Expect:** within about 10 seconds the health strip shows **Gateway, Policy sync, Ledger and Alerting as Healthy** (green tick and the word). Egress and Data sources stay Unknown.

## Before any traffic

3. Click **Gateway**.

   **Expect:** Requests 0, Denied 0, Held 0, Last request "never", and the box "No denials in the last 24 hours. Last gateway request: never. No traffic has reached the gateway, so this is not a sign that all is well."

4. Click **Reload this page every 5 seconds**.

## Send the demo traffic

5. In a second terminal run:

   ```bash
   docker compose run --rm demo-traffic
   ```

   **Expect:** this summary (the same on every fresh start):

   ```
   Sent 500 demo requests to http://gateway:8080 (run 1):
     ALLOWED                   375
     VENDOR_BLOCKED             40
     UNKNOWN_MODEL              34
     BUDGET_EXHAUSTED           22
     MODEL_BLOCKED              18
     APPROVAL_REQUIRED          11
   ```

6. Watch the Gateway page.

   **Expect:** Requests 500, Denied 114, Held 11. A table by reason, each in plain words with its code (for example "The vendor is blocked `VENDOR_BLOCKED`", 40) and a small trend line. Below it the latest 50 denied or held requests with time, agent, requested model, reason, budget and request ID.

7. Find a row with `BUDGET_EXHAUSTED`.

   **Expect:** agent `summaries-eu-agent`, budget "Summaries EU". Click **Budgets**: Summaries EU has only a few cents remaining and a full bar (99.99% used). It never goes over its cap.

8. On **Gateway**, scroll to **Unregistered models**.

   **Expect:** `vendor-a/model-9` (was 14 requests, now more) and a new name `vendor-c/new-model`.

## One request by hand

9. Click **Gateway**, scroll to **Create a credential**, choose `ticket-triage-agent`, type the label `demo-hand` and click **Create credential**.

   **Expect:** a page with the token (starts with `kair_`) and the warning that it is shown only once.

10. Copy the token and run (paste it in place of `TOKEN`):

    ```bash
    curl -s localhost:8080/v1/chat/completions -H "Authorization: Bearer TOKEN" -H "Idempotency-Key: hand-1" -H "Content-Type: application/json" -d '{"model":"model-1","messages":[{"role":"user","content":"hello"}],"max_tokens":50}'
    ```

    **Expect:** a JSON answer with `"content": "This is a mock answer. No real model was called."` and a `usage` block.

11. Run the same command again, unchanged.

    **Expect:** the same answer. The gateway replays the stored result; the budget is not charged twice.

12. Change `hello` to `goodbye` but keep `hand-1`, and run it.

    **Expect:** `"code":"IDEMPOTENCY_KEY_REUSED"` (HTTP 422).

13. Change the model to `vb-large` and the key to `hand-2`, and run it.

    **Expect:** `{"error":{"type":"keepair_policy_denied","code":"VENDOR_BLOCKED","request_id":"…"}}`. No amounts, no internal names. The request appears in the denials feed with that request ID.

14. Back on **Gateway**, find the `demo-hand` credential and click **Revoke**. Run the command from step 10 with key `hand-3`.

    **Expect:** `"code":"AUTHENTICATION_FAILED"` (HTTP 401) at once.

## Stop the gateway

15. Run:

    ```bash
    docker compose stop gateway
    ```

    Reload the Overview page after about 70 seconds, and again after about 3 minutes.

    **Expect:** Policy sync turns Degraded, then Failing; Gateway, Ledger and Alerting follow. The table says "No heartbeat since" with the time. Nothing shows Healthy without a recent heartbeat.

16. Run `docker compose start gateway`. **Expect:** Healthy again within about 10 seconds.

## Reset and stop

17. `docker compose restart app` reloads the demo data. `docker compose down -v` stops everything.

## Not in this phase

- Held requests cannot be approved yet (phase 5); a hold expires after 24 hours.
- If the database is down, the gateway refuses everything. Continuing on soft budgets through a spool is phase 3.
- Streaming responses, real vendors, and registering a model from the UI are not built.
