# Phase 1 demo script

Time: about 8 minutes. Needs Docker. No account, key or internet service is used. All vendors, models, names and amounts are fictional.

## Start

1. Run:

   ```bash
   docker compose up --build
   ```

   Open <http://localhost:8000>.

   **Expect:** the Overview page with the **DEMO** band. Health is still Unknown for every component (the gateway arrives in phase 2).

## Budgets

2. Click **Budgets**.

   **Expect:** 22 budgets in a tree: Northwind Labs (organization), 3 departments, 6 teams, 12 projects. Amounts are in USD, and in EUR under Research Europe. Every project has a **Gateway-routed** badge, with "Pending decision UX-D1" above the table. No badge says Enforced.

3. Look at the **Usage** column of the Engineering row.

   **Expect:** a bar with a solid part (committed), a hatched part (reserved) and an empty part (remaining), with marks at 50, 80, 90 and 100%. Under it: "87.25% committed, 3.95% reserved". The 50, 80 and 90 marks are bold because usage has passed them.

4. Find **Research Agent** (under Engineering, Agents).

   **Expect:** Remaining `19,250.00 USD`, but Effective remaining `10,550.00 USD` with "Limited by Engineering".

5. Click the **i** in the "Effective remaining" column header.

   **Expect:** the formula `effective_remaining = min over x in path …` and a worked example for Research Agent with the same numbers as the row: 19,250.00, 18,750.00, 10,550.00, result `10,550.00 USD`.

6. Click **Research Agent**.

   **Expect:** the budget's page: Cap `35,000.00 USD`, Committed `14,000.00 USD`, Reserved `1,750.00 USD`, Remaining `19,250.00 USD`, a large bar with a legend, and a table of the limit path: Research Agent, Agents, Engineering, Northwind Labs. The Engineering row is highlighted "Lowest. This sets the allowance." Northwind Labs says "No, it only reports" because it is a soft limit.

7. Go back to **Budgets** and look at **Engineering**, **Agents** and **Language Models**.

   **Expect:** an amber warning next to effective remaining, for example on Engineering: "Sub-budget caps exceed this cap by 10,000.00 USD. This cap applies first."

8. Find **Call Notes** (under Customer Operations, Sales Assist).

   **Expect:** a red bar, "Over cap by 1,080.00 USD", and "No enforced limit": it is a Monitor budget, which reports but never blocks.

## Vendors and models

9. Click **Gateway**.

   **Expect:** vendor-a Allowed, vendor-b Blocked, with the last change "2026-01-13 09:00:00 UTC, demo-admin: Contract review in progress…".

10. Look at the models of vendor-b.

    **Expect:** both show a lock and "Blocked by vendor vendor-b". Their switch is greyed out and labelled Locked, with the text "Controlled by vendor vendor-b. This model cannot be allowed while the vendor is blocked." vendor-b/model-1 also says "Own setting: allowed, overridden by the vendor block". Neither shows Allowed.

11. Look at the switch for vendor-b.

    **Expect:** it is disabled, with "Lifting a block needs two administrators. That flow arrives in phase 5." and "Pending decision SD-03".

12. Scroll to **Unregistered models**.

    **Expect:** `vendor-a/model-9` labelled "Unregistered" (not Blocked), 14 requests, with a disabled "Register model" button and "Pending decision D-03".

## Add a block

13. In the Vendors table, click the green **Allowed** switch for vendor-a.

    **Expect:** a page "Block vendor vendor-a" listing the three models that will be denied.

14. Click **Block vendor-a** without typing a reason. Then type `no` and click again.

    **Expect:** the browser asks for the field; with `no`, the page returns "Give a reason of 10 to 300 characters." and nothing is changed.

15. Type `Security incident under investigation.` and click **Block vendor-a**.

    **Expect:** back on Gateway, vendor-a is Blocked with last change "demo-operator: Security incident under investigation." All three vendor-a models now show the lock and "Blocked by vendor vendor-a". No model on the page shows Allowed.

## Reset and stop

16. To get the original demo data back, restart the app (it reloads the demo data at start):

    ```bash
    docker compose restart app
    ```

17. Press Ctrl+C in the first terminal, then run:

    ```bash
    docker compose down -v
    ```

## Not in this phase

- Nothing is enforced yet. The gateway, reservations and the denials feed are phase 2; amounts here are seeded.
- Budgets cannot be created or edited from the UI.
- Lifting a block, owners, sign-in and approvals are phase 5.
- The forecast band on the budget bar is not built.
