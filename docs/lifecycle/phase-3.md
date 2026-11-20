# Phase 3: Fail-open spool and visibility of failures

Lifecycle record, aligned with ISO/IEC 12207 (plan, entry and exit criteria, review).

## Plan

**Scope.**

- When the ledger cannot be written, a request whose whole budget path is monitor or soft may still be sent, but only after its usage record is written to an encrypted local spool (SD-04 default, SEC-06). Hard-limit and approval budgets, and every block, fail closed.
- The spool: append-only, encrypted per record, capped by count, size and age. A full spool denies. A failed spool write denies.
- Adapters accept a spool record as the only alternative to a ledger reservation, and claim it before sending.
- Replay when the ledger returns: each spooled record is applied to the budgets exactly once and becomes a fail-open event, a usage record and a decision record.
- Fail-open banner on every page (UX-7): shown while fail-open is active and afterwards until acknowledged.
- Fail-open report: every event, with budget, time, amount and whether it was reconciled.
- Demo console (demo mode only): stop and restore the ledger, send a few requests.
- A credential check that still works for 30 seconds when the database is down, for credentials seen just before.

**Out of scope.** A per-budget switch that lets a hard limit fail open (D-01), KMS-held spool keys, more than one gateway instance sharing a spool, audit log (phase 6).

**Entry criteria.**

| Criterion | Status |
|---|---|
| Phase 2 exit criteria met and reviewed | Met. Owner go-ahead given 2026-11-20. The stack was also run by the owner on his own machine. |
| SD-04 (monitor and soft budgets when the ledger is down) | Pending decision. The stated default (a: allow with encrypted spool, replay, alert, cap) is built and labelled. |

**Risks.**

| Risk | Handling |
|---|---|
| Fail-open lets a blocked vendor or a hard limit through | Blocks are decided before the ledger is touched and never depend on it. Eligibility needs every budget on the path to be monitor or soft. A stale policy snapshot still denies everything. |
| A request is sent and no record survives | The spool record is written and flushed to disk before dispatch. If that fails, the request is denied. |
| Replay counts a record twice | The record ID is the key of the fail-open event; a second replay finds it and skips. |
| Spool grows without bound during a long outage | Caps on count, bytes and age of the oldest record. At a cap, requests are denied. |
| Spool file is read or altered on disk | AES-256-GCM per record. A record that fails authentication is reported and skipped, never trusted. |
| Fail-open goes unnoticed | Metric, alert, banner that needs an acknowledgement, report, and an escalation alert after 15 minutes. |
| The UI cannot show fail-open when its own database is down | The UI asks the gateway for its fail-open status directly. |

## Exit criteria and result

| Exit criterion | Evidence | Result |
|---|---|---|
| Ledger down: soft and monitor continue through the spool; hard, approval and blocks are denied | `test_fail_open_is_counted_alerted_and_audited`, `test_ledger_down_denies_hard_approval_and_every_block`, `test_stale_policy_during_an_outage_stops_fail_open_too` | Pass |
| Spool full denies; spool write failure denies | `test_spool_full_denies`, `test_fail_open_window_is_capped_by_time_and_size`, `test_spool_write_failure_denies` | Pass |
| Replay is idempotent, also after a crash | `test_replay_is_idempotent`, `test_spooled_request_without_an_answer_is_replayed_at_its_estimate` | Pass |
| Every fail-open is counted, alerted and recorded | `test_fail_open_is_counted_alerted_and_audited` (metric, alert, then fail event, usage record and decision record after replay) | Pass |
| The spool is encrypted and holds no prompt; changed lines are detected | `test_spool_file_is_encrypted_and_holds_no_prompt`, `test_tampered_or_foreign_spool_lines_are_detected_and_never_trusted` | Pass |
| Adapter refuses without an open spool record | `test_adapter_refuses_without_an_open_spool_record` | Pass |
| Banner on every page, not dismissible until acknowledged | `tests/system/test_fail_open_ui.py` | Pass |
| Fail-open report matches the recorded events | `test_fail_open_report_matches_fail_events` | Pass |
| Demo console stops and restores the ledger | `test_demo_console_shows_what_an_outage_changes`, and a browser check | Pass |
| Banner appears within 5 seconds | Measured in Chromium against the Docker stack: 4.0 s on a second open page | Pass |
| Every new failure path has metric, alert and UI row; every new field has help | `tests/system/test_failure_visibility.py` (14 codes), `tests/system/test_field_help.py` | Pass |
| Lint, secret scan and all tests pass | 380 tests, 0 failures | Pass locally; CI result recorded below |

Bypass route B-m (fail-open used silently) is now covered: `test_fail_open_is_counted_alerted_and_audited`.

**Checked by hand against the Docker stack.** Console and banner in Chromium (stop, send, restore, acknowledge). A real `docker compose stop db`: two fail-open and three fail-closed within the first seconds; all eight refused after 40 seconds; spool replayed after `docker compose start db`.

**Notes.**

- **Behaviour change from phase 2.** A hard-limit request that meets a ledger failure now gets 403 `BUDGET_FAIL_CLOSED` (a policy answer) instead of 503. The two phase 2 tests that asserted 503 were updated, with the reason written in them.
- **Found by the new tests and fixed.** (1) A malformed token during an outage got 503 instead of 401; the format check now comes before any database call. (2) An unusable spool folder stopped the gateway from starting; it now starts and simply cannot fail open. (3) Two refuse paths had stopped raising an alert after the rework; they report `DATABASE_UNREACHABLE` again.
- **Limit worth the owner's attention (A-47).** With PostgreSQL fully down, fail-open lasts about 30 seconds, because credentials and policy can no longer be verified. The one-hour window of SD-04 is reached only when ledger writes fail while policy stays readable. This follows from "blocks always fail closed"; a longer window in a total outage would need a policy source that survives the database.
- The image rebuild in the build sandbox hit a Docker Hub rate limit once; the image was rebuilt from the cached base image. Not a product issue.
- Assumptions A-45 to A-56 were recorded.

## Review record

| Date | Reviewer | Outcome |
|---|---|---|
| 2026-11-20 | Engineering self-review | Exit criteria met, with the notes above. |
| Pending | Product owner | Go-ahead needed before phase 4. |
