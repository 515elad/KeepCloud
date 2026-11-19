# KeepAir PRD v1.5 — Combined Addendum: Architecture, Security and UX

**Date:** November 19, 2026
**Status:** Proposed. Combines the architect review (v1.4), the CISO review and the HMI/UX review into one set of requirements. Replaces the v1.5 that was described in chat but never saved.
**Base document:** `claude/keepair-prd-v1.4-build-spec.md`. Its requirements stand unless this addendum changes them. Each change names the v1.4 requirement it affects.
**Sources:** Architect review (v1.4 Part A, B-01 to B-19); CISO review (this document, Sections 3 to 6); HMI/UX review (Section 7); decisions register (Section 8).

**How to use this document:** Section 2 is the traceability matrix. Start there. Each FR row lists its security controls, UX requirements and open decisions. Sections 3 to 7 hold the detail.

---

## 1. What changed and why

- **Enforcement is not yet provable.** Nothing stops an agent from calling a provider directly. Egress control (FR-20) closes that gap, and SD-01 decides whether it is mandatory.
- **Failures must be visible.** Heartbeats, canaries and self-tests (FR-21) mean a broken control raises an alert. Failure states must also appear in the UI as health, not as "no data" (UX-5, UX-10).
- **The UI must never show a state the policy does not hold.** An inherited block is shown as blocked, and "Enforced" appears only when the controls behind it are verified (UX-2, UX-3).
- **Several v1.4 requirements had gaps** that are fixed here, including the undefined block override, the missing tenant isolation on most tables, and fail-open dispatch that left no record.

## 2. Traceability matrix

| Req | v1.4 status | Change in v1.5 | Security (Section 5) | UX (Section 7) | Decisions (Section 8) |
|---|---|---|---|---|---|
| FR-01 Ingestion | Read-only roles | External IDs or federation for cross-account reads; offline lint for write actions | SEC-18, SEC-28 | UX-10 partial data | — |
| FR-02 Data model | Money as micro-units | Raw records append-only; integrity via DB roles | SEC-33 | — | — |
| FR-03 Allocation | Deterministic rules | Rule changes need approval and audit | SEC-15, SEC-31 | UX-8 | — |
| FR-04 Budgets | Independent vs subdivision | Budget changes audited; owner MFA for HARD | SEC-17, SEC-31 | UX-8 subdivision warning | — |
| FR-05 Enforcement | Request path, fail table | Path allowlist; strict parsing; 403 denial schema; spool for fail-open; decision recorded before dispatch; DB clock for TTL | SEC-01 to SEC-12, SEC-35 | UX-4 | D-02, D-04, D-07, D-08, SD-01, SD-04 |
| FR-06 Attribution | Join key, metadata untrusted | Metadata allowlist and escaping | SEC-10, SEC-27 | UX-8 | — |
| FR-07 Reconciliation | Finalization state | Invoice upload is untrusted input; CSV formula neutralization | SEC-28, SEC-29 | UX-8 chips | D-05 |
| FR-08 Anomalies | Same-weekday baseline | Suppressions need a second person and expire | SEC-15 | UX-10 cold start, UX-11 | D-03 |
| FR-09 Optimization | Read-only recommendations | Provider text treated as untrusted | SEC-18, SEC-27 | — | — |
| FR-10 Routing | Substitution rules | Substitute must pass residency and vendor policy; no code execution in rules | SEC-30, SEC-28 | — | — |
| FR-11 Approvals | HELD queue | Requester and approver differ; expiry; caps on held count | SEC-12, SEC-15 | UX-11 | D-07, UX-D2 |
| FR-12 Reporting | Locked periods, fail-open report | Audit log tamper evidence; exports restricted to tenant recipients | SEC-29, SEC-31, SEC-32 | UX-8 | — |
| FR-13 IAM | RBAC, MFA (TOTP) | Route and role separation; step-up auth; local-account lifecycle; test material refused in production | SEC-13, SEC-14, SEC-16, SEC-17, SEC-23 | UX-9 | D-06 |
| FR-14 Connectors | Key custody, webhooks | Usage-only keys for monitor mode; SSRF protection on webhook targets; per-endpoint secrets | SEC-19, SEC-20, SEC-48 | UX-10 connector error | SD-05 |
| FR-15 Assistant (P2) | Typed queries | Prompt-injection resistance; no write tools; sub-processor disclosure | SEC-10, SEC-30 | — | — |
| FR-16 Unit economics | Customer outcomes | Outcome inputs are untrusted | SEC-27 | UX-13 no ROI claims | — |
| FR-17 Ownership | Owner required for HARD | Owner MFA; ownership changes two-person | SEC-15, SEC-17 | UX-8 unowned bucket | D-06 |
| FR-18 Registry and blocks | Vendor-over-model rule | Block override defined; kill switch; stale snapshot denies all dispatch; destination and path checks | SEC-05, SEC-07, SEC-08, SEC-09 | UX-3 cascade | SD-03 |
| FR-19 Uncontrolled spend | Provider vs gateway delta | Bypass suspicion from egress data | SEC-38 | UX-8 gateway share | D-02 |
| **FR-20 Egress control (new)** | — | Default deny for enforced workloads | SEC-02 | UX-2, UX-12 | SD-01 |
| **FR-21 Control assurance (new)** | — | Heartbeats, canaries, self-tests | SEC-37 to SEC-39 | UX-5 health strip | — |
| **FR-22 Security operations (new)** | — | Incident severity, kill switch, breach process | SEC-08, SEC-40, SEC-41 | UX-7 kill switch | SD-10 |
| Section 6 Security NFR | TLS 1.2, KMS | TLS 1.2+ with verify-full DB; key separation; deletion incl. backups | SEC-21, SEC-24, SEC-26 | — | SD-06, SD-07, SD-08 |

## 3. CISO findings on v1.4

| ID | Sev | Where | Finding | Fix (section) | Status |
|---|---|---|---|---|---|
| S-01 | Critical | FR-05, FR-14 | Agents can call providers directly; nothing stops it | FR-20 (SEC-02) | Design fixed; mandatory per SD-01 |
| S-02 | Critical | FR-05 | Provider paths beyond chat (batch, files, images, audio, realtime, assistants) unclassified | Path allowlist, default deny (SEC-03) | Fixed |
| S-03 | Critical | FR-05, FR-18 | "Override" referenced but never defined | Block override defined; none by default (SEC-07) | Fixed; SD-03 |
| S-04 | High | FR-05 | Fail-open dispatch without a ledger record | Encrypted spool, replay, alert, capped window (SEC-06) | Fixed; SD-04 |
| S-05 | High | Section 2.5 | Most tables lack `tenant_id` | `tenant_id` on every tenant table, RLS (SEC-16) | Fixed |
| S-06 | High | FR-14 | Customer keys for monitor mode stored without scope rules | Vault, usage-only scope check (SEC-20) | Fixed; SD-05 |
| S-07 | High | FR-12 | DB writer can recompute the whole audit chain | External anchoring, KMS-signed heads (SEC-32) | Fixed |
| S-08 | High | FR-01, FR-09 | Cross-account read roles open to confused deputy | External IDs or federation (SEC-18) | Fixed |
| S-09 | High | FR-05 | Application clock drives reservation TTL | DB clock authoritative; skew monitored (SEC-35) | Fixed |
| S-10 | High | FR-18 | Replica policy reads can lag undetected | Primary reads, or lag-checked replica (SEC-09) | Fixed |
| S-11 | High | FR-10, FR-15 | Prompt injection can steer policy-adjacent components | Policy inputs limited to principal and validated fields (SEC-10) | Fixed |
| S-12 | High | FR-05, FR-17 | Long-lived gateway credentials in agent environments | 90-day max, scope, caps (SEC-12); SD-02 | Fixed; SD-02 |
| S-13 | Medium | FR-05 | Stolen token or retry loop exhausts a team budget | Per-credential rate and spend caps (SEC-12) | Fixed |
| S-14 | Medium | FR-05 | Duplicate JSON keys or multiple model fields | Strict parsing; body-only model source (SEC-04) | Fixed |
| S-15 | Medium | FR-05, FR-18 | Configurable base URLs enable SSRF | Registry-only hostnames (SEC-02) | Fixed |
| S-16 | Medium | FR-05 | SDK can be pointed at a provider directly | SDK refuses direct URLs in enforced mode (SEC-01) | Fixed |
| S-17 | Medium | FR-05 | Denial contract undefined | 403 with stable reason codes (SEC-11) | Fixed |
| S-18 | Medium | NFR | Provider error bodies can echo prompts; auth headers in logs | Redaction at all sinks (SEC-34) | Fixed |
| S-19 | Medium | FR-01, FR-07 | Invoice upload and CSV export are untrusted-file surfaces | Sandboxed parsers; formula neutralization (SEC-28, SEC-29) | Fixed |
| S-20 | Medium | FR-06, FR-17 | Metadata and tags rendered in UI | Escaping, CSP, allowlisted keys (SEC-27) | Fixed |
| S-21 | Medium | FR-12 | Scheduled exports to external recipients | Tenant-domain recipients; export audit (SEC-29) | Fixed |
| S-22 | Medium | FR-10 | Substitution can change data residency; customer rules can execute code | Residency check; sandboxed rules (SEC-30) | Fixed |
| S-23 | Medium | FR-11, FR-18 | Two-person rule allows colluding administrators | Distinct identity and role; step-up (SEC-15) | Fixed; SD-03 |
| S-24 | Medium | Missing | No global kill switch | Kill switch (SEC-08, FR-22) | Fixed |
| S-25 | Medium | Missing | Stopped components are silent | Heartbeats and canaries (SEC-37, SEC-38) | Fixed |
| S-26 | Medium | FR-13 | Test secrets could reach production | Startup refuses test material (SEC-23) | Fixed |
| S-27 | Medium | NFR | TLS minimum without DB rule | TLS 1.2+, verify-full DB (SEC-24) | Fixed |
| S-28 | Medium | NFR | Deletion does not reach backups | Backup window and key separation (SEC-21, SEC-26) | Fixed |
| S-29 | Medium | Section 11 | No SBOM, signing or CI credential rules | SEC-43 to SEC-48 | Fixed |
| S-30 | Medium | Sections 7, 9 | Sub-processors undisclosed | DPA and sub-processor register (SEC-30) | Fixed |
| S-31 | Medium | FR-13 | No joiner, mover, leaver process for local accounts | Deprovisioning SLA; quarterly review (SEC-17) | Fixed |
| S-32 | Medium | FR-18 | Stale snapshot denies only vendors blocked in it; a newer block is invisible | Stale snapshot denies all enforced dispatch on that instance | Fixed; availability trade-off |
| S-33 | Medium | Missing | No threat model, ISO/SOC mapping or breach process | Sections 5 and FR-22 | Fixed |
| S-34 | Medium | FR-05 | Decision not recorded but request proceeds | Record before dispatch; deny if unrecorded (SEC-06) | Fixed |
| S-35 | Low | FR-14 | Webhook secrets have no rotation | Per-endpoint secrets and rotation (FR-14) | Fixed |
| S-36 | Low | FR-13 | Tokens not detectable by secret scanners | Prefixed token format (SEC-22) | Fixed |
| S-37 | Verify | FR-05 | Egress instrumentation and existing fixtures unknown | V-5, V-6 | Verify |

**Claim discipline.** KeepAir may claim only what its controls prove.

| Term | Meaning | Condition |
|---|---|---|
| Enforced spend | Passed the gateway decision and was reserved before dispatch | Gateway credential; KeepAir key custody; egress verified (FR-20); SD-01 |
| Monitored spend | Visible through provider data; cannot be stopped | Any traffic that does not meet the enforced condition |
| Uncontrolled spend | Detected in provider data with no gateway record (FR-19) | Always shown |

Do not use "all AI spend is controlled", "cannot be bypassed", "guaranteed budget" or "zero overspend" until the bypass suite and pilot coverage data support them. Legal review of marketing copy is required before GA (SEC-41).

## 4. Trust boundaries

| ID | Boundary | Threat if unguarded | Controls |
|---|---|---|---|
| TB-1 | Agent workload → gateway | Spoofed principal; route choice to bypass | SEC-10, SEC-12, SEC-14 |
| TB-2 | Gateway → model vendor | Key leak; wrong destination; response injection | SEC-19, SEC-02, SEC-27 |
| TB-3 | Agent workload → internet | Direct provider calls; alternate endpoints; DNS bypass | SEC-02, FR-20 |
| TB-4 | Services → PostgreSQL | Cross-tenant reads; audit rewrite; stale policy | SEC-09, SEC-16, SEC-33 |
| TB-5 | Admin user → admin API | Lifting blocks; budget manipulation | SEC-13, SEC-15 |
| TB-6 | Ingestion → cloud and provider accounts | Confused deputy; over-privileged keys | SEC-18, SEC-20 |
| TB-7 | Customer file → parser | Parser exploit; formula injection | SEC-28 |
| TB-8 | SDK in customer code → gateway | Fallback to direct; misconfiguration | SEC-01, SEC-48 |
| TB-9 | Browser UI → API | XSS, CSRF, stored injection | SEC-13, SEC-27 |
| TB-10 | KeepAir features → model vendor | Customer data to undisclosed sub-processors | SEC-30 |
| TB-11 | KeepAir → customer (reports, webhooks) | Exfiltration; forged or SSRF webhook delivery | SEC-29, FR-14 |
| TB-12 | Services → vault and KMS | Key exposure; over-broad decrypt | SEC-19, SEC-21 |
| TB-13 | Services → observability sinks | Secret or content leakage | SEC-34 |
| TB-14 | CI/CD → production | Malicious build; long-lived credentials | SEC-45, SEC-46 |

**Threats and abuse cases.** Each is mapped to controls in Section 5.
- T-01 Agent calls a provider directly (SEC-02).
- T-02 Agent uses an unlisted provider path (SEC-03).
- T-03 Agent uses a model alias that resolves to a blocked model (SEC-05).
- T-04 Ambiguous model field in a request (SEC-04).
- T-05 Stolen gateway token reused (SEC-12).
- T-06 One administrator lifts a block alone (SEC-15).
- T-07 Database administrator rewrites the audit log (SEC-32).
- T-08 Cross-tenant query (SEC-16).
- T-09 Stolen provider key used outside KeepAir (SEC-20; FR-19).
- T-10 Fail-open used silently (SEC-06).
- T-11 Stale policy after a block (SEC-09).
- T-12 Prompt injection steers an agent to reveal its token or call admin routes (SEC-10, SEC-12, SEC-14).
- T-13 Malicious invoice or CSV (SEC-28, SEC-27).
- T-14 Compromised build pipeline (SEC-45, SEC-46).
- T-15 Logs leak prompts or keys (SEC-34).
- T-16 Confused deputy on cloud read roles (SEC-18).
- T-17 Data exfiltration through a scheduled report (SEC-29).
- T-18 A control fails silently (SEC-36 to SEC-39).
- T-19 Stolen token used to exhaust a budget (SEC-12).
- T-20 Undisclosed data flow to a sub-processor (SEC-30).

## 5. Security control catalogue

Each control is referenced by the requirement it protects. SOC 2 references are to the Trust Services Criteria (CC = Common Criteria). ISO references are to ISO/IEC 27001:2022 Annex A, and ISO/IEC 25010 security sub-characteristics. Mapping to be confirmed by the auditor.

| ID | Control | Protects | SOC 2 | ISO | Proven by |
|---|---|---|---|---|---|
| SEC-01 | Single decision path: no dispatch without a gateway reservation; SDK and adapters refuse direct URLs in enforced mode | B-n6 | CC6.6, CC7.2 | A.8.26, A.8.27 | `test_no_dispatch_without_reservation`; `test_sdk_refuses_direct_base_url_in_enforced_mode` |
| SEC-02 | Egress default deny for enforced workloads; registry-only hostnames; no IP-literal or DoH | T-01 | CC6.6, CC6.7 | A.8.20–A.8.22 | `test_enforced_direct_connect_denied`; `test_ip_literal_to_vendor_range_denied`; `test_doh_blocked_for_enforced` |
| SEC-03 | Provider path allowlist; billable classification; default deny | T-02 | CC6.1 | A.8.3 | `test_unlisted_provider_path_denied`; `test_websocket_upgrade_denied` |
| SEC-04 | Strict parsing: duplicate keys rejected; one model source; size and decompression limits | T-04 | CC7.1 | A.8.28 | `test_duplicate_model_key_rejected`; fuzzing of the canonicalizer |
| SEC-05 | Block precedence (vendor over model); default deny for unknown aliases | T-03 | CC6.1 | A.8.3; 25010 Security | `test_blocked_vendor_denies_even_when_model_allowed` (property test) |
| SEC-06 | Failure policy: blocks and hard limits fail closed; monitor and soft fail open only with spool, replay, alert and cap; decision recorded before dispatch | T-10, S-34 | CC7.2 | A.8.16 | `test_fail_open_is_counted_alerted_and_audited`; `test_spool_full_denies`; `test_no_record_no_dispatch` |
| SEC-07 | Block override: none by default; if SD-03 allows one, time-boxed, two-person, auto-revert | T-06 | CC6.3 | A.8.2 | `test_lift_block_requires_second_admin`; `test_override_auto_reverts` |
| SEC-08 | Global, vendor and project kill switch; activation one step, deactivation two-person | Incident | CC7.4 | A.5.26 | `test_kill_switch_denies_within_5s`; drill record |
| SEC-09 | Snapshot freshness: stale or lagging snapshot denies all enforced dispatch on that instance; policy reads from primary or lag-checked replica | T-11 | CC7.2 | A.8.16 | `test_block_fails_closed_when_snapshot_stale`; `test_replica_lag_fails_closed` |
| SEC-10 | Policy inputs are the authenticated principal and validated fields only; model output, message text and tool results never affect policy | T-12 | CC6.1 | A.8.26 | `test_policy_ignores_model_text_in_messages` |
| SEC-11 | Denial contract: 403 for policy, with stable reason codes and request ID; no budget amounts or internal identifiers | Disclosure | CC6.7 | A.8.28 | `test_denial_schema_is_stable_and_minimal` |
| SEC-12 | Gateway credentials: 256-bit, hashed, inference-only, 90-day maximum, revoked within 30 s, per-credential spend and rate caps, HELD caps | T-05, T-19 | CC6.1, CC6.2 | A.5.17, A.5.18 | `test_revoked_token_rejected_within_cache_window`; `test_token_cannot_reach_admin_routes` |
| SEC-13 | Admin authentication: MFA (TOTP in P0, WebAuthn in P1); step-up for policy changes; idle and absolute session limits; NIST SP 800-63B password rules | T-06, TB-9 | CC6.1, CC6.2 | A.5.17, A.8.5 | `test_admin_policy_change_requires_step_up`; `test_session_timeouts` |
| SEC-14 | Route and role separation: gateway, admin and reporting APIs use separate credentials, listeners and permission matrix | TB-5 | CC6.3 | A.5.15, A.8.2 | `test_cross_route_credentials_rejected`; permission matrix test |
| SEC-15 | Separation of duties: approver and requester differ; two-person approvers differ in identity and hold ADMIN; recorded | T-06, S-23 | CC6.3, CC8.1 | A.5.3 | `test_self_approval_denied`; `test_second_approver_must_differ` |
| SEC-16 | Tenant isolation: `tenant_id` on every tenant table; RLS; tenant context set only after authentication | T-08 | CC6.1 | A.8.3, A.5.15 | `test_cross_tenant_read_denied` on every endpoint and export |
| SEC-17 | Account lifecycle: deprovision within one business day of exit (proposed); quarterly access review; owner MFA for HARD budgets | Insider | CC6.2, CC6.3 | A.5.18 | Access review evidence; `test_owner_requires_mfa_for_hard` |
| SEC-18 | Cross-account access through external IDs or federation; cloud read policies contain no write actions | T-16 | CC6.1, CC6.3 | A.5.18, A.5.23 | `test_cloud_read_policy_has_no_write_actions` (fixture lint) |
| SEC-19 | Provider keys only in vault: KMS envelope encryption; decrypted in memory per call; never logged, returned or placed in the outbox | T-09, TB-2 | CC6.1, CC6.7 | A.8.24, A.5.17 | `test_logs_contain_no_prompt_or_key_material`; `test_key_never_in_api_response` |
| SEC-20 | Provider key scope and rotation: project scope where supported; usage-only scopes for monitor keys, validated; compromise rotation within 24 h | T-09, S-06 | CC6.1, CC6.2 | A.5.17, A.8.2 | `test_usage_key_with_write_scope_rejected` |
| SEC-21 | Key separation: KMS master keys never in database backups; annual rotation; per-tenant data keys | S-28 | CC6.1 | A.8.24 | Key policy review; restore drill checks separation |
| SEC-22 | Gateway token format with prefix and checksum for secret scanners; tokens never logged | S-36 | CC6.1 | A.8.25 | `test_token_format_detected_by_secret_scanner` |
| SEC-23 | Test material refused in production: startup check on environment | S-26 | CC6.1 | A.8.31 | `test_test_secret_refused_in_prod` |
| SEC-24 | TLS 1.2 minimum (1.3 preferred); verify-full to PostgreSQL; KMS at rest | S-27 | CC6.7 | A.8.24; 25010 Confidentiality | TLS configuration test; scan results |
| SEC-25 | Minimization: no prompts or responses stored by default; metadata only; retention configurable | Privacy | C1.1 | A.8.10, A.8.11 | `test_no_prompt_storage_by_default` |
| SEC-26 | Deletion: tenant primary data removed within 30 days (proposed); backups expire within 35 days (proposed) or tenant key destroyed | S-28 | C1.2 | A.8.10 | Deletion job test; crypto-shred test |
| SEC-27 | Output encoding, CSP, allowlisted metadata keys, length limits; no unescaped metadata in UI | S-20, T-13 | CC6.1 | A.8.28 | `test_metadata_is_escaped_in_ui_render`; CSP header test |
| SEC-28 | Untrusted files: size and type limits; parsers isolated with resource limits; quarantine on failure | S-19, T-13 | CC7.1 | A.8.28 | `test_malformed_invoice_quarantined`; fuzz test |
| SEC-29 | Export and delivery: CSV formula neutralization; recipients limited to verified tenant domains; bulk export alert; export audit | T-17, S-21 | CC6.7 | A.8.12 | `test_csv_formula_neutralized`; `test_external_recipient_rejected` |
| SEC-30 | Sub-processors and residency: maintained register; substitutions and KeepAir-feature model calls pass residency and vendor policy; minimized data to models | S-22, S-30, T-20 | CC9.2 | A.5.19, A.5.21, A.5.23 | `test_substitution_residency_check`; register review |
| SEC-31 | Security audit events: admin, policy, budget, owner, override, kill switch, key, token, failure and every denial | Accountability | CC7.2 | A.8.15; 25010 Accountability | `test_every_admin_action_audited` |
| SEC-32 | Tamper-evident audit: hash chain; hourly signed head (KMS asymmetric key) anchored to external WORM storage; daily verifier | T-07, S-07 | CC7.2 | A.8.15, A.5.28; 25010 Integrity | `test_audit_hash_chain_detects_tampering`; `test_anchor_mismatch_raises_critical` |
| SEC-33 | Database role separation: gateway role cannot UPDATE or DELETE audit; migration role separate; no superuser in application | T-07 | CC6.1, CC6.3 | A.8.15, A.8.2 | `test_app_role_cannot_modify_audit` (testcontainers) |
| SEC-34 | Log redaction at every sink, including provider error bodies; canary strings scanned | TB-13, S-18, T-15 | CC7.2 | A.8.12, A.8.15 | `test_logs_contain_no_prompt_or_key_material` (all sinks, error paths) |
| SEC-35 | Time integrity: database clock authoritative for reservation expiry; NTP drift monitored; skew alerts | S-09 | CC7.2 | A.8.17 | `test_expiry_uses_db_clock`; skew alert test |
| SEC-36 | No silent failure: every failure path emits a metric, an alert and an audit record | T-18 | CC7.2, CC7.3 | A.8.16, A.5.25 | `test_every_fail_path_emits_metric_alert_audit` (enumerated list) |
| SEC-37 | Heartbeats for gateway, egress proxy, egress monitor, outbox, reconciliation, audit verifier and canary runner; absence alerts | T-18 | CC7.2 | A.8.16 | `test_heartbeat_absence_alerts` (fake clock) |
| SEC-38 | Production canaries with no provider credentials: blocked-model canary expects 403 and zero vault reads; egress canary expects deny in the proxy decision log | T-01, T-18 | CC7.2, CC4.1 | A.8.16, A.8.29 | Canary definitions; offline canary suite with fake proxy |
| SEC-39 | Guard self-proof: startup and runtime self-tests; mutation-testing gate on guard modules; fault injection | T-18 | CC7.1, CC8.1 | A.8.29 | Mutation kill-rate gate; `test_startup_selftest_failure_blocks_start` |
| SEC-40 | Incident response: severity model, runbooks, on-call, quarterly tabletop, post-incident review | Incident | CC7.3–CC7.5 | A.5.24, A.5.26, A.5.27 | Tabletop record; runbook drill |
| SEC-41 | Claims and disclosure control: claim terms (Section 3); legal review of marketing and contracts; no certification claims before audit | Misrepresentation | CC2.3 | A.5.31 | Legal review record |
| SEC-42 | Threat model per requirement, updated each release; each threat maps to a control and a test | All | CC3.2 | A.8.25; 25010 | Threat model review record; traceability check |
| SEC-43 | Dependency pinning with hashes; lockfiles; automated vulnerability scanning | Supply chain | CC7.1 | A.8.8 | Scanning gate in CI |
| SEC-44 | Static analysis, secret scanning, IaC and container scanning in CI; critical and high findings block merge | Code defects | CC7.1 | A.8.28, A.8.29 | CI gate; seeded-defect test |
| SEC-45 | Build provenance: SBOM (CycloneDX) per release; signed images and SDK packages; provenance attestation | TB-14 | CC8.1 | A.5.21, A.8.32 | Signature verification at deploy |
| SEC-46 | CI and deploy least privilege: OIDC federation (no static cloud keys in CI); pinned action SHAs; protected branches; two reviews for security-critical paths; no force-push | T-14 | CC8.1 | A.8.31, A.8.32 | Branch protection configuration check |
| SEC-47 | Runtime hardening: non-root; read-only root filesystem; minimal base image; network policies; resource limits | Escape | CC6.6 | A.8.9 | Deployment policy checks |
| SEC-48 | SDK integrity: minimal dependencies; signed releases; no provider keys or direct endpoints; telemetry opt-in | TB-8 | CC6.1 | A.5.21 | SDK contract tests |
| SEC-49 | Vulnerability targets (proposed, SD-10): critical 7 days, high 30 days, medium 90 days; exceptions recorded with owner and expiry | Vulnerabilities | CC7.1 | A.8.8 | SLA report |
| SEC-50 | External penetration test before GA and annually; scope includes gateway bypass, egress and tenant isolation | Validation | CC4.1, CC7.1 | A.8.29 | Report; retest evidence |
| SEC-51 | Backups encrypted; PITR for reservations (RPO ≤ 5 min); quarterly scripted restore drill; reservation recovery procedure | Availability | A1.2, A1.3 | A.8.13, A.8.14 | Drill record; `test_reservation_recovery_releases_orphans` |
| SEC-52 | Change control and drift: policy and config changes via reviewed change record; effective-config hash checked hourly against approved baseline | Unauthorized change | CC8.1 | A.8.9, A.8.32 | `test_config_drift_alerts` |

### 5.1 Bypass routes (first-class cases)

Extends the B-a to B-m suite in v1.4 FR-05.

| Route | Control | Test |
|---|---|---|
| B-n1 Enforced workload connects to a provider directly | SEC-02 | `test_enforced_direct_connect_denied` |
| B-n2 Provider path beyond chat (batch, files, images, realtime) | SEC-03 | `test_unlisted_provider_path_denied` |
| B-n3 IP literal to a vendor range | SEC-02 | `test_ip_literal_to_vendor_range_denied` |
| B-n4 DNS over HTTPS or alternate resolver | SEC-02 | `test_doh_blocked_for_enforced` |
| B-n5 Duplicate or conflicting model fields | SEC-04 | `test_duplicate_model_key_rejected` |
| B-n6 SDK pointed at a provider or falls back to direct | SEC-01 | `test_sdk_refuses_direct_base_url_in_enforced_mode` |
| B-n7 Project marked enforced but using a customer key | D-02 | `test_enforced_project_with_customer_key_rejected` |
| B-n8 Stale replica read | SEC-09 | `test_replica_lag_fails_closed` |
| B-n9 Prompt injection asks the agent to use another model, print its token or call admin routes | SEC-10, SEC-12, SEC-14 | `test_policy_ignores_model_text_in_messages`; `test_token_cannot_reach_admin_routes` |
| B-n10 Test configuration in production | SEC-23 | `test_test_secret_refused_in_prod` |
| B-n11 Pass-through mode in configuration | SEC-01 | `test_no_passthrough_mode_exists` |
| B-n12 Traffic from a workload outside any enforced segment | FR-19, FR-20 detection | `test_unenforced_vendor_flow_raises_bypass_suspected` |

## 6. New and changed requirements

### FR-05 changes (request path)

The v1.4 request path is unchanged except for the steps below.

1. **Authenticate.** Token scope must be inference-only. Admin routes reject gateway tokens.
2. **Path allowlist (new).** Provider, method and path must match the allowlist. Unknown paths return 404 `PATH_NOT_ALLOWED`. Every allowed path is classified as billable or not.
3. **Strict parse (new).** Reject duplicate JSON keys. The model is read from the body only. A conflicting model in a header returns 400 `AMBIGUOUS_REQUEST`.
4. **Canonicalize and block check** as in v1.4 FR-18.
5. **Destination check (new).** The vendor host comes from the registry only. No customer-supplied URLs on this path.
6. **Estimate and reserve.** Reservation time comes from the database clock. A decision is recorded before dispatch. If it cannot be recorded, the request is denied.
7. **Dispatch and settle** as in v1.4.
8. **Respond.** Hop-by-hop and provider-internal headers are stripped.

**Denial contract (new).** Policy denials return HTTP 403 with a stable code and request ID. Example body: `{"error":{"type":"keepair_policy_denied","code":"VENDOR_BLOCKED","request_id":"..."}}`. Other status codes: 401 authentication, 404 path not allowed, 400 ambiguous request, 409 or 422 idempotency conflicts, 429 rate limit. Budget exhaustion returns 403 `BUDGET_EXHAUSTED`. The response contains no budget amounts or internal identifiers.

**Fail-open with spool (replaces v1.4 wording).** When the ledger is unreachable, monitor and soft budgets may dispatch only if the usage is written to an encrypted local spool first. The spool is replayed when the ledger returns, and each record is reconciled. Capacity is capped (proposed: one hour or 100 MB). When the cap is reached, requests are denied. Every spool event raises an alert and an audit record. Blocks never fail open. Subject to SD-04.

**Reservation caps (new).** Each credential has a maximum number of open reservations and of HELD requests (proposed: 100 and 20). Exceeding a cap returns 429.

**Reservation transaction.** The `expires_at` value is computed as `now() + ttl` in the database, not in the application.

### FR-18 changes (registry and blocks)

- **Block override (replaces v1.4 reference).** No override by default. If SD-03 allows one, it is time-boxed (maximum 24 h), requires two different administrators, and reverts automatically.
- **Stale snapshot (replaces v1.4 wording).** If the snapshot is older than 30 s and cannot refresh, or replica lag exceeds 5 s, the instance denies all enforced dispatch for every tenant and raises SNAPSHOT_STALE (SEV2). A block added after the snapshot cannot be seen, so partial denial is not safe.
- **Route and destination (new).** A vendor route mismatch returns VENDOR_ROUTE_MISMATCH. Enforced workloads reach vendor hosts only through the gateway (FR-20).
- **Kill switch (new).** Activation is one step, by any administrator with step-up authentication. Deactivation requires two people. Propagation is within 5 s. The denial code is KILL_SWITCH.
- **Admin routes.** Status changes require step-up. The kill switch uses `POST /v1/admin/kill-switch` to activate and `DELETE` to deactivate.

### FR-20 Egress control and destination policy (P0, new)

**Intent:** an enforced workload cannot reach a provider except through the gateway, and any path that is not controlled is visible.

- Enforced network segments deny egress by default. Allowed: the gateway's egress host and required internal services only.
- Egress goes through a forward proxy with a CONNECT allowlist by SNI. Direct DNS goes through a controlled resolver.
- The allowlist is generated from `vendor_endpoints` in the registry (hostnames and ports).
- Enforced segments deny IP-literal connections to vendor endpoints, and deny DNS over HTTPS and DNS over TLS.
- Unknown destinations from an enforced segment are denied and alerted (SD-01).
- Monitored segments are logged. Flows to vendor endpoints that do not correlate with a gateway record raise BYPASS_SUSPECTED (FR-19).
- The gateway is not an open proxy. It refuses CONNECT and forwards only to registry hosts.
- Proxy decision logs go to the SIEM.
- Coverage metric: percentage of workloads in enforced segments (measured in pilot).

**Limits.** Processes outside an enforced segment are detected, not prevented. Tunnelling through allowed hosts is not fully preventable at the network layer. Both limits are stated in the UI and in sales material.

**Tests (offline, fake proxy):** `test_enforced_direct_connect_denied`; `test_unknown_destination_denied_for_enforced`; `test_ip_literal_to_vendor_range_denied`; `test_doh_blocked_for_enforced`; `test_gateway_is_not_an_open_proxy`.

**Dependencies:** V-5 (instrumentation granularity); SD-01.

### FR-21 Control assurance and failure visibility (P0, new)

**Intent:** every control proves it works, and a broken control is visible.

- **Heartbeats (SEC-37).** Each component emits a heartbeat. No heartbeat within its threshold raises an alert. The UI shows "no heartbeat since <time>", never a healthy state.
- **Startup self-test.** The gateway runs known decisions (blocked, unknown, allowed) before accepting traffic. Failure prevents startup and raises an alert.
- **Runtime self-test.** Every 60 s, the same decisions run in process. A mismatch raises GUARD_SELFTEST_FAILED (critical) and the instance denies all enforced dispatch.
- **Production canaries (SEC-38).** A canary principal requests a canary-blocked model every 60 s. The expected result is 403 with zero vault reads. An egress canary attempts a connection to a reserved hostname (`.invalid`) through the proxy. The expected result is deny in the decision log. Canaries never use real provider credentials. Detection relies on decision logs, not on network success.
- **Mutation testing gate.** Each guard module (authentication, canonicalization, block check, reserve, egress allow, path allowlist, fail-closed switch, audit writer, tenant filter) must have its mutants killed by the test suite. Proposed gate: 100% for these modules.
- **Config drift (SEC-52).** The effective configuration hash is compared with the approved baseline hourly.
- **Audit verifier (SEC-32).** Daily. Mismatch with an external anchor raises AUDIT_CHAIN_BROKEN (critical).

**Alert severities.**

| Event | Severity |
|---|---|
| Bypass confirmed; audit chain broken; credential compromise; cross-tenant exposure | SEV1 |
| Fail-open active over 15 min; self-test failure on one instance; canary failure; uncontrolled spend over threshold; heartbeat absent for an enforcement component | SEV2 |
| Single-credential anomaly; high-severity scan finding; token nearing expiry | SEV3 |

**Tests:** `test_heartbeat_absence_alerts`; `test_startup_selftest_failure_blocks_start`; `test_runtime_selftest_mismatch_denies_enforced`; `test_every_fail_path_emits_metric_alert_audit`.

### FR-22 Security operations, incident response and kill switch (P0, new)

- **Severity model** as in FR-21. Proposed response targets: SEV1 acknowledged within 15 min and contained within 1 h; SEV2 acknowledged within 1 h; SEV3 next business day.
- **Kill switch** scopes: global, vendor, project. Activation shows an impact preview. Deactivation requires a second person.
- **Runbooks** for: provider key compromise (rotation within 24 h), gateway token compromise, audit chain break, fail-open event, and reservation recovery.
- **Customer notification.** Set by the DPA. Proposed target: confirmed exposure of customer data notified within 24 h of confirmation, with regulatory timelines applied where they are longer.
- **Quarterly tabletop exercise** with a recorded outcome.
- **Post-incident review** within 10 business days for SEV1 and SEV2.

## 7. UX requirements

### UX-1 Information architecture

One app with role-based landing pages (SD-UX-D4).

| Area | Screens | Role | Requirement |
|---|---|---|---|
| Overview | Executive summary; setup checklist until complete; unowned spend bucket; health strip | Finance, Admin | FR-12, FR-17 |
| Spend | Cost explorer; allocation; unallocated and unmatched queue; join-confidence review (70–89 band) | Finance | FR-03, FR-06 |
| Budgets | Hierarchy tree; budget detail with bar and forecast; effective-remaining panel; owner assignment | Owner, Finance | FR-04, FR-17 |
| Gateway | Projects and credentials; vendor and model registry; denials feed; fail-open report | Engineering, Admin | FR-05, FR-18 |
| Approvals | HELD queue; budget requests; override requests; two-person pending items | Admin, Owner | FR-11 |
| Reconciliation | Finalization by period; differences; uncontrolled findings; invoice upload and review queue | Finance, Auditor | FR-07, FR-19 |
| Reports | Templates; scheduled exports; export history | Finance, Auditor | FR-12 |
| Admin | Users and roles; connectors and keys; kill switch; audit log | Admin, Auditor | FR-13, FR-14, FR-22 |

Default landing: Engineering on Gateway, Finance on Overview, Owner on "My budgets", Auditor on the audit log.

### UX-2 Coverage badge

Shown on every project and budget. Four states, each with a label, an icon and a color.

| State | Meaning | Condition |
|---|---|---|
| Enforced | Gateway routed; key in KeepAir custody; egress verified | Only when SD-01 is in place and verified |
| Gateway-routed | Gateway used; egress not verified | Default until egress is verified (UX-D1) |
| Monitored | Visible through provider data only | KeepAir cannot stop this spend |
| Uncontrolled | Usage gap detected | FR-19 finding |

### UX-3 Block cascade

- The vendor row controls its models.
- An inherited model row shows a lock and "Blocked by vendor X". Its toggle is disabled and a tooltip explains why.
- The model never shows "Allowed" while the vendor is blocked.
- The last change shows who, when and why.
- Lifting a block shows "awaiting second approver" with the expiry.

### UX-4 Blocked, denied and unregistered

Three separate labels, each with its own action.
- **Blocked:** an administrator's decision.
- **Denied:** one request's outcome.
- **Unregistered:** a model nobody has registered (D-03). Offers "Register model".

### UX-5 Denials feed

Columns: time, agent, model, reason (plain language, code in monospace), budget, request ID. Grouped by reason, with a sparkline per reason. Admin and auditor roles see full context; agents see only the stable code (UX-D3).

### UX-6 Health strip

Persistent in the header. Items: gateway, policy sync (snapshot age), ledger, egress, alerting, each data source's freshness.

States: Healthy, Degraded, Failing, Unknown. **Unknown is never green.** If the alerting pipeline is down, the strip says so.

### UX-7 Fail-open banner and kill switch

- **Fail-open banner:** shown while any fail-open is active. Cannot be dismissed until an administrator acknowledges it. Shows the count and time window, and links to the fail-open report.
- **Kill switch:** administrator area only. Flow: choose scope; see impact preview (agents and projects affected, traffic in last five minutes); enter a reason; confirm. A red header indicator stays visible while active. Clearing shows "awaiting second approver".

### UX-8 Money and data

- **Finalization chip** next to every total: Estimated, Provider-reported or Invoiced (FR-07). Estimated values use a hatched or outlined pattern. Never sum across states without a split.
- **Budget bar:** horizontal, ticks at 50, 80, 90 and 100%. Committed and reserved are stacked; remaining is the rest. Forecast shown as a band. No donuts for budgets.
- **Subdivision warning** inline, next to effective remaining (FR-04).
- **Unowned spend:** neutral amber with "Assign owner". Red is reserved for blocks and failures.
- **Gateway-controlled share:** one stacked bar per project, labeled with its percentage (FR-19). Never 100% unless the coverage badge is Enforced.
- **Charts:** small multiples for cost by model; heatmap for denials by hour and reason; treemap for allocation only with a table toggle.
- **Time and currency:** timezone shown on every axis; billing timezone and user timezone labeled separately; FX rate date next to converted totals.

### UX-9 Roles and permissions

| Role | Core question | Sees | Does | Hidden or read-only |
|---|---|---|---|---|
| Finance | Where is money going; what is unowned? | Spend, budgets, close, reconciliation | Allocate, close, export | Credentials, policy edits |
| Engineering | Is my agent allowed; why was it denied? | Gateway, denials, credentials, egress status | Create and rotate credentials; copy SDK config | Budget edits |
| Admin | Is enforcement working; what must I change? | Operations | Blocks, kill switch, approvals, users | Audit log read-only |
| Auditor | Can I prove what happened? | All, read-only, including audit anchors | Export | All writes |
| Budget owner | Am I about to exceed my budget? | Own budgets and scope | Approve own-scope requests | Other teams |

**Permission limits:** show a disabled control with the reason and who can approve it. Do not hide it.

### UX-10 States

| State | Design |
|---|---|
| New tenant | Setup checklist on Overview, not blank charts |
| Waiting for first data | "Waiting for first AWS export. Expected within 24 h", with ETA from provider latency |
| Cold start (FR-08) | "Learning baseline: day 6 of 14. Owner threshold applies: $X." |
| No denials | "No denials in the last 24 h. Last gateway request: 2 min ago." Last-request time proves traffic is arriving |
| Stale data | "As of 14:32, 3 h ago." Amber once the freshness target is breached |
| Partial data | Per-source tiles, for example "Azure: 3 of 7 days ingested" |
| Connector error | Error card: what failed; last success; next retry; remediation link (CONNECTOR_FAILED) |
| Loading | Skeleton with previous value and timestamp. No spinner over numbers |
| Permission limit | Disabled control with reason (UX-9) |

### UX-11 Approvals and two-person actions

- **HELD approvals:** the approver sees request metadata, budget impact and expiry. Under D-07 (metadata only), the approve button says what happens next (UX-D2).
- **Two-person actions:** the requester sees "pending second approver", the expiry, and who is eligible. Self-approval is disabled with a reason.

### UX-12 Onboarding

Checklist, not a 12-step list. Each step shows its validation result.

- The custody choice is a card: "Monitor only. KeepAir cannot stop spend on this key." (D-02)
- The egress step (SD-01) has copyable configuration and a "verify" action that confirms the control works.

### UX-13 Companion and delight

The PRD does not define Vane or a cat helper. Nothing in this addendum depends on it.

If the companion is added (UX-D5):
- Appears only in onboarding and empty states. Never on alert, denial, approval or kill-switch surfaces.
- Respects reduced-motion settings. Never animates over a status.
- Does not say "the AI decided". Decisions are attributed to the policy.
- Has a per-user off switch, on for new users and off for administrators.

Operational delight:
- "Why was this blocked?" card on each denial: policy, snapshot version, change history.
- "What changed since yesterday" digest for owners.
- Command palette (Ctrl+K / ⌘K) for administrators, with search by request ID.
- No savings celebration unless measured (PRD Section 7; no fabricated ROI).

### UX-14 Accessibility and consistency

- WCAG 2.2 AA.
- Status is never color alone: each status has an icon and a word.
- Every chart has a text summary and a table view.
- All actions, including the kill switch and credential creation, work by keyboard.
- Visible focus on every control. Reduced-motion respected. Dark-mode contrast checked separately.
- RTL-ready layout. IDs, currency and numbers stay left-to-right inside it.
- Shared components: StatusChip, CoverageBadge, FinalizationChip, DataAgeLabel, ReasonCode, BudgetBar, HealthStrip.
- One currency format, one date format and one timezone label across all screens.
- Dense table mode for administrators; sparse mode for executives.

## 8. Decisions register

Each decision has a recommendation. Where undecided, the default applies and engineering proceeds on it.

### Architecture (from v1.4)

| ID | Decision | Recommendation | Default |
|---|---|---|---|
| D-01 | Hard-limit fail mode: fail-closed for all, or configurable by tier | Fail-closed for all; Enterprise may request an audited override | Fail-closed |
| D-02 | Can customer-held keys back a hard limit? | Never; monitor only | Never |
| D-03 | Unknown models | Discovery in monitor scope only; deny for enforced budgets | Discovery only |
| D-04 | Estimator conservatism | Strict upper bound in P0 | Strict |
| D-05 | Invoice source | Upload in P0; ERP in P1; restate the 99.5% target | Upload, target restated |
| D-06 | P0 owner identity | Local accounts with MFA; IdP in P1 | Local accounts |
| D-07 | HELD request body stored? | Metadata only in P0 | Metadata only |
| D-08 | Stream cut at budget exhaustion? | No; deny the next request | No cut |
| D-09 | Waiting period for lifting a block | Two administrators plus one hour | Zero wait until decided |
| D-10 | Billing metric | Product decision; no recommendation without willingness-to-pay data | Not built |

### Security (new)

| ID | Decision | Options | Recommendation | Risk of each option |
|---|---|---|---|---|
| **SD-01** | Egress control for enforced workloads | (a) required for hard limits; (b) recommended, with detection if not deployed; (c) optional | (a) for hard limits; (b) for soft and monitor | (a): most onboarding friction, strongest claim. (b): claim must be qualified. (c): bypass remains easy |
| **SD-02** | Gateway credential lifetime | (a) static, 90-day maximum, rotation alerts in P0; (b) short-lived via federation in P0; (c) static, no expiry | (a) in P0; (b) in P1 | (a): a stolen token works for up to 90 days. (b): needs federation work now. (c): unacceptable |
| **SD-03** | Block overrides | (a) none; lift by two people only; (b) time-boxed override, two people, auto-revert within 24 h; (c) single-administrator override | (b) with the 24 h cap; (a) until operations need it | (a): a false block needs two people to lift. (b): a short window of exposure. (c): one compromised administrator can lift a block |
| **SD-04** | Monitor and soft budgets when the ledger is down | (a) allow with encrypted spool, replay, alert and one-hour cap; (b) deny all dispatch | (a). Blocks stay closed in both | (a): spend can be unrecorded if the spool is lost. (b): agents stop during ledger outages |
| **SD-05** | Keys for monitor-only customers | (a) accept provider admin keys; (b) accept usage-only scopes, validated, else upload; (c) never store keys, upload only | (b) | (a): high blast radius. (b): some providers may not offer usage-only scopes. (c): more manual work for customers |
| **SD-06** | Data residency | (a) single region at launch; (b) per-tenant region pinning at onboarding; (c) pinning for Enterprise only | (b) in design; (a) at launch | (a): enterprise objections. (b): more operational cost |
| **SD-07** | Customer-managed encryption keys (BYOK) | (a) none in P0; (b) Enterprise in P1; (c) P0 for all | (b) | (a): enterprise objections. (c): large build now |
| **SD-08** | Prompt and response retention | (a) none, metadata only; (b) opt-in encrypted retention with per-tenant TTL; (c) mandatory | (a) by default; (b) in P1 with DPA | (b): larger breach exposure. (c): unacceptable |
| **SD-09** | ISO scope | (a) ISO/IEC 27001 certification path; (b) ISO/IEC 25010 product-quality alignment only; (c) both, sequenced | (c): 27001 for operations, 25010 for product quality | (a): cost and time. (b): weaker assurance for enterprise buyers |
| **SD-10** | Vulnerability remediation targets | (a) 7 / 30 / 90 days; (b) 14 / 30 / 90 days | (a) for critical and high, given the enforcement claim | (b): longer exposure window on the critical path |

### UX (from HMI review)

| ID | Decision | Options | Recommendation | Default |
|---|---|---|---|---|
| **UX-D1** | Label for gateway traffic without verified egress | (a) "Enforced" for any gateway traffic; (b) "Gateway-routed" until verified | (b). "Enforced" overstates protection | (b) |
| **UX-D2** | Approval flow under D-07 | (a) store encrypted body and dispatch on approval; (b) metadata only, one resubmission, with clear copy | (b), with copy such as "Approving allows one matching resubmission within 15 min" | (b) with that copy |
| **UX-D3** | Denial detail for admins | (a) same codes as agents; (b) full context for admin and auditor roles | (b) | (b) |
| **UX-D4** | App shape | (a) one app with role-based landing; (b) separate consoles | (a) | (a) |
| **UX-D5** | Companion | (a) none in P0; (b) onboarding and empty states only; (c) throughout | (b), with per-user off switch | No build impact until chosen |
| **UX-D6** | UI languages at launch | (a) English, RTL-ready; (b) English and Hebrew | (a); Hebrew in P1 | (a) |
| **UX-D7** | Forecast before 90 days of history | (a) point forecast; (b) band only until minimum history | (b) | (b) |

**Decisions needed first:** SD-01, SD-03, SD-04, UX-D1 and UX-D2. They change what the coverage badge says, what the approval screen says, and what the enforcement claim may be.

## 9. Verification gates

Before P0 build starts. Each produces a written record.

| ID | Question | Method | Blocks |
|---|---|---|---|
| V-1 | Do OpenAI and Anthropic usage APIs report per key or per project? At what granularity and latency? | Official documentation; sandbox key if available | FR-05 monitor reconciliation, FR-07, FR-19, FR-20 coverage |
| V-2 | Does the existing policy store use exactly Blocked and Allowed? Is there an unknown state? How is vendor override implemented? | Read schema and tests | FR-18 |
| V-3 | Observability, alerting and dashboard stack; absence (no-data) alert rules; metric and alert APIs | Platform configuration | FR-21, UX-6 |
| V-4 | Database engine | Platform configuration | Sections 2.3, 2.5 |
| **V-5** | Egress instrumentation: does it identify destination hostname (SNI), IP and workload identity? | Read the instrumentation configuration | FR-20 design, SD-01 |
| **V-6** | Existing shared policy fixtures and mocked-LLM setup: do they test vendor-over-model precedence and fail paths? Where do they live? | Read the test suite | Test plan Section 2.7; reuse decision |
| **V-7** | Does the alerting stack support absence rules and heartbeat metrics? | Read alert configuration | FR-21 |
| **V-8** | Does the existing gateway return 403 with a reason for blocks? | Read the policy store and gateway code | FR-05 denial contract (SEC-11) |

## 10. Build sequencing (additions)

v1.4 Section 2.6 stands. These steps are added:

| Step | Work | Depends on | Exit criterion |
|---|---|---|---|
| S0-sec | Threat model reviewed (Section 4); V-5 to V-8 recorded | S0 | Threat model signed off; every T-xx mapped to a control and test |
| S4a | Egress proxy and destination policy (FR-20) | S1, S3 | Egress tests pass with fake proxy |
| S5-sec | Heartbeats, self-tests, canaries, audit anchor, verifier (FR-21, SEC-32) | S5 | Every failure path tested to emit metric, alert and audit |
| S6-sec | Kill switch; two-person flows; UX states for held and pending items | S6 | FR-22 and UX-7, UX-11 tests pass |
| S7-sec | Secure parsers for invoices and imports (SEC-28) | S7 | Malformed-file fuzz tests pass |
| S9-sec | SDK fail-closed behavior (SEC-01, SEC-48) | S9 | SDK refuses direct URLs in enforced mode |
| S11-sec | Penetration test; mutation gate; restore and kill-switch drills | All | Release gates in Section 11 met |

## 11. Release gates (additions to v1.4 Section 11)

P0 may proceed only when, in addition to the v1.4 gates:

- The bypass suite (B-a to B-m and B-n1 to B-n12) passes.
- Mutation kill rate is 100% on the guard modules listed in FR-21.
- No critical or high findings open from static analysis, dependency scanning or secret scanning. Medium findings have a recorded exception.
- SBOM and signed artifacts exist for the release.
- External penetration test complete; its critical and high findings fixed or accepted under SD-10.
- Kill switch drill and reservation restore drill completed and recorded.
- Audit anchor verification passes.
- Canaries have run for seven consecutive days in pilot.
- No CI test uses a provider credential, verified by the secret scanner and the test runner environment.
- Egress coverage measured in pilot and reported (FR-20).
- Claim wording reviewed by legal (SEC-41).
- Coverage badge, health strip and denials feed reviewed against UX-2, UX-5 and UX-6 with pilot users.

## 12. Risks (additions to v1.4 Section 10)

| Risk | Mitigation |
|---|---|
| Agents bypass the gateway directly | FR-20 egress control; SD-01; coverage badge shows the gap; FR-19 detection |
| Unlisted provider paths are unmetered | Path allowlist, default deny (SEC-03) |
| Stolen gateway token used for spend or data access | 90-day maximum; caps; revocation within 30 s; SD-02 |
| A control fails silently | Heartbeats, canaries, self-tests (FR-21); health strip (UX-6) |
| Audit log rewritten by a database administrator | External anchoring (SEC-32) |
| Prompt injection steers an agent or the assistant | Policy inputs limited (SEC-10); no write tools (FR-15) |
| Users read a zero-denial state as healthy | "Last gateway request" shown with zero (UX-10) |
| Users read reserved money as spent | Stacked bar (UX-8) |
| Approvers approve requests that need resubmission | Approve-button copy (UX-D2) |
| Companion distracts from alerts | Companion excluded from operational surfaces (UX-13) |
| Overstated enforcement claims | Claim discipline (Section 3); legal review (SEC-41) |

## 13. Known gaps in this addendum

- **Vane and the cat helper** are not in the PRD. UX-13 gives rules in case they are added.
- **Hebrew and RTL.** RTL-ready layout is specified. Hebrew copy is not (UX-D6).
- **ISO target** is a working assumption until SD-09 is decided.
- **SOC 2 and ISO mappings** are the architect's reading of the criteria and Annex A. An auditor must confirm them before they are cited externally.
- **Proposed numbers** (for example 30 days deletion, 35 days backup expiry, 100 reservations per credential, 7-day critical SLA) are placeholders until decided or measured.
- **Verification V-5 to V-8** are blocking for the security design, and not yet done.
