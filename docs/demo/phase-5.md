# Phase 5 demo script

Time: about 10 minutes. Needs Docker. All people, accounts and data are generated demo material.

If you chose another port (for example `KEEPAIR_UI_PORT=8100 ./run.sh`), use that port wherever this script says 8000.

You need **two browser windows that do not share cookies**, for two different people. The simplest way: one normal window and one private (incognito) window.

## Start and sign in

1. Run:

   ```bash
   git pull origin dev
   ```

   ```bash
   ./run.sh
   ```

2. Open <http://localhost:8000> in the normal window.

   **Expect:** the sign-in page. Nothing else can be opened without signing in. Below the form is a "DEMO accounts" list with five fictional people and the demo password.

3. Type user name `alice.admin`, copy the password shown on the page, click **Continue**.

   **Expect:** "Authenticator code, step 2 of 2". Below the input: "DEMO Your authenticator would show 123456 now" (your digits differ).

4. Type those six digits and click **Sign in**.

   **Expect:** Overview. Top right: "Signed in as Alice Okafor, Administrator" and a Sign out button.

5. In the private window open <http://localhost:8000> and sign in the same way as `bob.admin`.

About the code: every sensitive action asks for a fresh authenticator code. In demo mode the page shows it next to the input. A code works once. If the page says "The next code is not valid yet", wait: the next one appears by itself within 30 seconds.

## Owners and the unowned bucket

6. As Alice, look at **Overview**, section "Unowned spend".

   **Expect:** Unowned spend `11,971.30 USD` with the hatched Estimated chip, "Budgets without an owner" `4`, and four links: Benchmark Runs, Call Notes, Evaluation, Sales Assist.

7. Click **Call Notes**. Scroll to "Owner and policy". Under "Change the policy" choose **Hard limit**, type the reason `Sales wants a firm ceiling.`, type the code shown, click **Change policy**.

   **Expect:** "The change was refused. A hard limit cannot be switched on without an active owner (FR-17). Nothing was changed."

8. Go back. Under "Assign the owner" choose **Bob Lindqvist (bob.admin)**, reason `Bob runs the sales tooling.`, the code, **Assign owner**.

   **Expect:** Owner is now Bob Lindqvist. Overview now counts 3 budgets without an owner.

9. Repeat step 7.

   **Expect:** the policy is now Hard limit.

## A held request, and approving it

10. As Alice open **Admin**, scroll to "Demo console", click **Send 8 test requests**.

    **Expect:** the research-agent row says "Not sent. Held until an approver decides `APPROVAL_REQUIRED`".

11. Open **Approvals**.

    **Expect:** "Held requests" lists requests of the research-agent, newest first. The text above the table says in bold: "Approving allows one matching resubmission within 15 minutes". Each row shows the model, the amount reserved, the budget, what is left after the hold, and when the hold ends. The request text is nowhere: it is not stored.

12. In the top row click **Approve one resubmission**.

    **Expect:** the row changes to "Approved. Waiting for the agent to send the same request again", with the end of the 15-minute window. "Recent decisions" shows "Held request, Approved, alice.admin".

13. Open **Admin** and click **Send 8 test requests** again.

    **Expect:** the research-agent row now says "Sent". Click the button a third time: it is held again. One approval, one resubmission.

14. Self-approval. Sign out, sign in as `omar.owner` (Omar owns the Research Agent budget), open **Approvals**.

    **Expect:** Approve is disabled, with the reason "This request comes from your own project. Someone else must decide it." Sign out and sign in as `alice.admin` again.

## Lifting a block needs a second person

15. As Alice open **Gateway**, section "Vendors". In the `vendor-b` row click **Ask to lift this block**.

    **Expect:** a page that explains: you ask, a second administrator approves within 24 hours, there is no time-boxed override (pending decision SD-03). "Who can approve": `bob.admin`.

16. Reason `Blocked by mistake, the contract was signed.`, the code, **Ask a second administrator**.

    **Expect:** Approvals, "Waiting for a second administrator": "Lift a block", "Pending second approver. You made this request, so you cannot approve it", the expiry time 24 hours ahead, who can approve, and a Cancel button. On Gateway, vendor-b is still Blocked and says "Awaiting second approver".

17. In Bob's window open **Approvals**. In that row type Bob's code and click **Approve**.

    **Expect:** the row moves to "Recent decisions" as Approved by bob.admin. On Gateway vendor-b is Allowed, last change "alice.admin + bob.admin".

## Kill switch

18. As Alice open **Admin**, section "Kill switch". Leave the scope on "All traffic" and click **Preview the impact**.

    **Expect:** a page with three figures: Projects affected 12, Agents affected 12, Requests in the last 5 minutes (some number). Nothing is switched on yet.

19. Reason `Incident drill for the demo.`, the code, **Switch on for All traffic**.

    **Expect:** a red bar under the header on every page: "Kill switch on. The gateway refuses requests for: All traffic."

20. Wait 5 seconds. In the Demo console click **Send 8 test requests**.

    **Expect:** all eight rows: "Not sent. A kill switch is on for this traffic `KILL_SWITCH`".

21. In the kill switch table type a reason (`The drill is over, traffic may resume.`), the code, and click **Ask to switch off**.

    **Expect:** "Awaiting second approver". The red bar stays.

22. In Bob's window open **Approvals**, type Bob's code, click **Approve**.

    **Expect:** the red bar is gone. After 5 seconds the test requests go through again. "Earlier uses" lists the switch, switched off by "alice.admin + bob.admin".

## Users and roles

23. As Alice, **Admin**, "Add a user": user name `nina.new`, name `Nina New`, role Finance, the code, **Add user**.

    **Expect:** a page that shows an initial password and an authenticator secret once.

24. Sign out and sign in as `fiona.finance`.

    **Expect:** the navigation has no Admin and no Audit log. Opening <http://localhost:8000/admin> says "Your role does not allow this".

## Stop

25. `./run.sh stop`

## Not in this phase

- Single sign-on, hardware keys, e-mail, password change by the user.
- Time-boxed block overrides (SD-03 default is none).
- Approval chains and delegation.
- The audit log viewer and its verify button (phase 6). The actions above are already recorded.
