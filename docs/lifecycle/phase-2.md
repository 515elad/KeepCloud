# Phase 2: Gateway, ledger and denials

Lifecycle record, aligned with ISO/IEC 12207 (plan, entry and exit criteria, review).

## Plan

**Scope.**

- A gateway listener, separate from the UI, with an OpenAI-compatible chat endpoint that talks to a mock provider. No real provider and no real key is used.
- The request path in FR-05 order, each step its own function: authenticate, path allowlist, strict parse, idempotency, canonicalize, block check, estimate, reserve, dispatch, settle, respond.
- Budget ledger in PostgreSQL: reserve, settle, release and expire in transactions with row locks taken in a fixed order. Reservation expiry uses the database clock.
- Agents and gateway credentials. Tokens are shown once, stored as SHA-256 hash only, never logged, and expire after at most 90 days.
- Idempotency keys: same key and body returns the stored result; same key with another body is refused.
- Adapters refuse to run without a live reservation.
- Policy snapshot with a staleness rule: a stale snapshot denies everything.
- Denial contract (HTTP 403, stable codes, request ID, no amounts) and the denials feed (UX-5).
- Health strip goes live: gateway, policy sync, ledger and alerting heartbeats.
- Demo: a seeded generator sends 500 requests through the gateway; some are denied.

**Out of scope.** Streaming responses, real provider adapters, the vault and KMS, fail-open spool (phase 3), approving held requests (phase 5), audit log and outbox (phase 6), egress control (FR-20), the SDK.

**Entry criteria.**

| Criterion | Status |
|---|---|
| Phase 1 exit criteria met and reviewed | Met. Owner go-ahead given 2026-11-20. |
| Assumptions A-16 and A-17 (how budgets limit and count spend) | No objection raised at the phase gate; the ledger implements them. |

**Risks.**

| Risk | Handling |
|---|---|
| Concurrent requests overshoot a cap | One transaction per reservation, `SELECT ... FOR UPDATE` on the budget path in ascending id order; test with 200 concurrent reservations on a real PostgreSQL. |
| A provider call happens with no reservation | The adapter claims the reservation in the database before sending; no claim, no call. Test calls the adapter directly. |
| Money is lost or double counted on retries, timeouts and crashes | Idempotency keys; settle-once; timeout settles at the reserved amount and flags unknown usage; expiry sweeper. Each has a test. |
| A token leaks through logs or the database | Hash only in the database; a test runs the request path with canary strings and scans logs and every table. |
| A new block is not seen | Snapshot refresh at most every 5 s; older than 30 s denies all. |
| Demo traffic is mistaken for real spend | DEMO band stays on every page; all vendors and models are fictional. |
| EUR budgets charged with USD prices | Versioned FX rate table; conversion rounds up; a missing rate denies. |

## Exit criteria and result

| Exit criterion | Evidence | Result |
|---|---|---|
| Request path works end to end against the mock provider | `tests/integration/test_gateway_path.py` (34 tests) | Pass |
| 200 concurrent reservations never exceed the cap | `test_reserve_never_exceeds_cap_under_200_concurrent_requests`: exactly 50 of 200 succeed on a budget with room for 50; a watcher thread saw no moment above the cap. Tolerance used: zero. | Pass |
| Idempotency: replay, in flight, changed body | `test_idempotent_retry_returns_same_result_without_double_reserve`, `test_same_key_still_in_flight_returns_409_with_retry_after`, `test_same_key_different_body_rejected` | Pass |
| Timeout after dispatch settles at reserved and flags unknown | `test_timeout_after_dispatch_settles_at_reserved_and_flags_unknown` | Pass |
| Adapter refuses without a reservation | `test_no_dispatch_without_reservation` (no permit, bare ID, made-up, settled, released, expired, held, already dispatched) | Pass |
| Bypass routes that apply have tests | See the table below | Pass |
| Denials feed and live health strip | `tests/system/test_gateway_activity.py` | Pass |
| 500-request demo gives the same outcomes on every run | `test_demo_traffic_gives_the_same_outcomes_on_every_run`; also run against the Docker stack | Pass |
| Every new failure path has metric, alert and UI row | `tests/system/test_failure_visibility.py` (9 codes) | Pass |
| Every new field has a registry entry | `tests/system/test_field_help.py` | Pass |
| Lint, secret scan and all tests pass | 343 tests, 0 failures; 95% line coverage | Pass locally and in CI (commit `ece192d`). The commit before it failed lint on one line and was fixed. |

**Bypass suite status.**

| Route | Test | Status |
|---|---|---|
| B-a customer-held key behind a hard limit | `test_customer_key_project_cannot_activate_hard_limit` (database rule) | Pass |
| B-b leaked provider key used directly | Needs reconciliation | Phase 4 |
| B-c gateway token leaked | `test_revoked_token_rejected_within_cache_window` | Pass |
| B-d spoofed team or project headers | `test_principal_ignores_client_headers` | Pass |
| B-e alias of a blocked model | `test_alias_to_blocked_model_denies` | Pass |
| B-f same model through another vendor route | `test_vendor_route_mismatch_denies` | Pass |
| B-g retry storm | `test_idempotent_retry_returns_same_result_without_double_reserve` | Pass |
| B-h disconnect mid-stream | Streaming is refused (`test_streaming_is_refused`), so the route does not exist | Pass by refusal |
| B-i crash between reserve and dispatch | `test_expired_reservation_settles_and_alerts` | Pass |
| B-j crash or timeout after dispatch | `test_timeout_after_dispatch_settles_at_reserved_and_flags_unknown` | Pass |
| B-k stale policy | `test_block_fails_closed_when_snapshot_stale` | Pass |
| B-l owner or override tampered | Needs two-person rule and audit chain | Phases 5 and 6 |
| B-m fail-open used silently | Needs the spool | Phase 3 |
| B-n2 unlisted provider path | `test_unlisted_provider_path_denied` | Pass |
| B-n5 duplicate model fields | `test_duplicate_model_key_rejected` | Pass |
| B-n7 enforced project with customer key | Same as B-a | Pass |
| B-n9 prompt injection | `test_policy_ignores_model_text_in_messages`, `test_token_cannot_reach_admin_routes` | Pass |
| B-n10 test material in production | `test_test_secret_refused_in_prod` | Pass |
| B-n11 pass-through mode | `test_no_passthrough_mode_exists` | Pass |
| B-n1, n3, n4, n12 egress | Egress control (FR-20) is not in the MVP phases | Not built |
| B-n6 SDK pointed at a provider | No SDK in the MVP; the adapter side is covered by `test_no_dispatch_without_reservation` | Not built |
| B-n8 stale replica | No replica; policy is read from the primary | Not applicable |

**Notes.**

- **Defect found and fixed in this phase, present since phase 1.** Clicking through in a real browser showed that form posts were refused as "cross-site". The browser sent `Origin: null` because of the strict referrer policy. The phase 1 "Block" form therefore did not work from a browser; it had only been exercised by tests and curl, which send a normal Origin. The check now uses the browser's own `Sec-Fetch-Site` header, the referrer policy is `same-origin`, a regression test was added (`test_form_posts_as_a_real_browser_sends_them`), and the block, create-credential and revoke forms were re-checked in Chromium. Lesson recorded in the test plan: forms get a browser check, not only HTTP-level tests.
- **Latency.** `test_gateway_overhead_is_measured` measured a full round trip (authenticate to settle, mock provider with no latency, PostgreSQL in a local container, test client included) at about p50 29 ms and p95 34 ms. The PRD target is p95 at most 25 ms *before dispatch* in a pilot deployment. The two are not the same measurement, and the target is not yet shown to be met. The request path uses five database transactions; fewer round trips and a credential cache are the obvious next steps if a pilot needs them.
- The guard test on registry writes was narrowed to the vendor and model tables, because the ledger legitimately updates budgets. The reason is written in the test.
- Assumptions A-29 to A-44 were recorded. A-29 (what the Approval policy does), A-30 (unknown models always denied) and A-32 (responses kept 24 hours for idempotent replay) deserve the owner's review.

## Review record

| Date | Reviewer | Outcome |
|---|---|---|
| 2026-11-20 | Engineering self-review | Exit criteria met, with the notes above. |
| Pending | Product owner | Go-ahead needed before phase 3. |
