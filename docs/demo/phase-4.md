# Phase 4 demo script

Time: about 8 minutes. Needs Docker. All files are generated demo data; none comes from a real provider.

If you chose another port (for example `KEEPAIR_UI_PORT=8100 ./run.sh`), use that port wherever this script says 8000.

## Start

1. Run:

   ```bash
   ./run.sh
   ```

2. Open <http://localhost:8000> and click **Spend** (new in the navigation).

   **Expect:** Billing period `2026-01`. Three totals, each with its own chip:
   - Estimated `182,373.32 USD` (hatched chip). This is what the gateway calculated.
   - Provider-reported "No data".
   - Invoiced "No data".

   Under "Cost by model": three small charts with hatched bars only. Under "Allocation by project": "No billing file is loaded for this period…".

## Load the provider's usage export

3. Scroll to **Load a billing file**. Leave Source on "vendor-a usage export". Click the file chooser and pick, inside the KeepCloud folder you cloned:

   `demo/billing/vendor-a-usage-2026-01.csv`

   Click **Load file**.

   **Expect:** the page jumps to Ingestion history: "Loaded", Rows 431, New 431, Revised 0, Unchanged 0. In the header strip, **Data sources** turns Healthy.

4. Scroll to the top.

   **Expect:** Provider-reported is now `182,423.21 USD`. Each chart has a solid bar next to each hatched one. The text under the first chart reads "Estimated 117,193.46 USD, Provider-reported 117,223.51 USD".

5. Click **Show as table** under a chart, and click its **i**.

   **Expect:** the same figures per day as a table; the help shows the scale and a worked example.

## Allocation

6. Scroll to **Allocation by project**.

   **Expect:** 12 projects. Build Assistant: Direct `21,915.33 USD`, Inferred `10,755.86 USD` (its 60% share of the Platform team's shared cost, split by a rule), Allocated `32,671.20 USD`. At the foot: Unmatched `42.50 USD`, Unallocated `17.25 USD`, and "All records" `182,423.21 USD` 100.00%.

7. Scroll to **Records that need a decision**.

   **Expect:** three rows:
   - **To review**, join confidence **70**: a Red Team record tagged with the project but no team.
   - **Unallocated**, confidence 0: a record with no tags.
   - **Unmatched**, confidence 0: tags `project=shadow-experiment team=Growth`, which fit no project.

8. In the Unmatched row choose **Lead Scoring**, type the reason `Belongs to the growth pilot.` and click **Assign**.

   **Expect:** the row leaves the list. In the allocation table, Lead Scoring now has `42.50 USD` under Manual and Unmatched is `0.00 USD`.

## Loading twice, a correction, an invoice, a broken file

9. Load `vendor-a-usage-2026-01.csv` again.

   **Expect:** a new history row with New 0 and Unchanged 431. The totals do not change.

10. Load `demo/billing/vendor-a-usage-2026-01-correction.csv` (same source).

    **Expect:** Rows 2, Revised 2. Provider-reported becomes `182,461.35 USD`. The earlier figures are kept in the database as revision 1.

11. Change Source to **vendor-a invoice** and load `demo/billing/vendor-a-invoice-2026-01.csv`.

    **Expect:** Invoiced `92,457.80 USD` (the invoice covers 1 to 7 January). Charts show a dark bar for those days. A second allocation table appears for Invoiced records. The three totals are still separate; nowhere are they added.

12. Change Source back to **vendor-a usage export** and load `demo/billing/broken-example.csv`.

    **Expect:** a red box "The file was refused and nothing from it was loaded." with four reasons, each naming a row and a column (a negative cost, a bad date, tags that are not JSON, a cost with seven decimals). The totals do not change. Overview shows an `INGEST_QUARANTINED` alert.

## Reconciliation and uncontrolled spend

13. Click **Reconciliation**.

    **Expect:** the three totals again, Difference (provider minus estimate) of a few dozen USD, "Not tied to a project", and **Uncontrolled findings 1**.

14. Find **Lead Scoring** in the table.

    **Expect:** highlighted. Estimated `2,400.00 USD`, Provider-reported about `3,160 USD` (3,120.00 plus the record you assigned), Gateway-controlled share about 76%, and "Uncontrolled … more at the provider than through the gateway". Other projects say "99% or more. Not shown as 100%: egress is not verified".

15. Click **Budgets**.

    **Expect:** Lead Scoring's badge is now **Uncontrolled**. The other projects stay Gateway-routed.

16. Click **Overview**.

    **Expect:** "Spend in 2026-01" with the three totals and chips, and an `UNCONTROLLED_SPEND` alert.

## Stop

17. `./run.sh stop`

## Not in this phase

- Real cloud and provider connectors, invoice PDFs, credits and taxes, period close.
- An editor for allocation rules; one seeded rule shows the split.
- Forecasts and anomaly alerts.
- CSV export of these tables (phase 6).
