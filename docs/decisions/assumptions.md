# Assumptions log

Where the PRD is unclear, the simplest choice that keeps the intent is recorded here. Open decisions (D-xx, SD-xx, UX-Dx) are not decided here: their stated default is implemented and labelled "pending decision" in the UI when the feature appears.

| # | Phase | Topic | Assumption | Why |
|---|---|---|---|---|
| A-01 | 0 | Repository | The repo is `github.com/515elad/KeepCloud`, not `5liftoff/KeepCloud` as in the brief. | The owner gave this repo after the original could not be created from the session. |
| A-02 | 0 | Existing foundation | There is no existing gateway, policy store, observability stack or fixtures to reuse. Everything is built new in this repo. | The repo was empty. See `docs/architecture/verification.md`. |
| A-03 | 0 | Python version | Project targets Python 3.12 (PRD). The Docker image and CI use 3.12. | PRD v1.4 Section 2.3. |
| A-04 | 0 | Navigation | The eight pages in the owner brief are built. The "Spend" area from UX-1 is added in phase 4, when the brief introduces the Spend page. | The brief's phase 0 list has no Spend page; phase 4 does. |
| A-05 | 0 | "Coming in phase N" | A page can have several sections that arrive in different phases. Each section shows its own phase and requirement IDs. | The Gateway page, for example, gets the registry in phase 1 and denials in phase 2. |
| A-06 | 0 | Health strip items | Gateway, Policy sync, Ledger, Egress, Alerting, Data sources (UX-6). Egress control (FR-20) is not in any MVP phase, so Egress stays Unknown for the whole MVP and the UI says so. | Showing it as anything else would claim a control that does not exist (PRD v1.5 Section 1). |
| A-07 | 0 | Health thresholds | Healthy up to 60 s since the last heartbeat, Degraded up to 180 s, then Failing (policy sync 30 s / 60 s; data sources 24 h / 48 h). A heartbeat dated in the future gives Unknown. | The PRD sets no heartbeat thresholds. Policy sync follows the 30 s snapshot rule in FR-18. Values are in one place (`keepair.health.COMPONENTS`). |
| A-08 | 0 | Failure visibility | Phase 0 failures produce a metric, an alert record and a UI row (owner brief, hard rule 5). The audit record that SEC-36 also asks for is added when the audit log is built in phase 6. | The audit log is a phase 6 deliverable. |
| A-09 | 0 | Alerts during a database outage | If the database is down, an alert cannot be stored there. It is held in memory, shown in the UI as "held in memory", and written to the database when it returns. Alerts held in memory are lost if the process restarts during the outage; the metric is not. | A failure of the store must still be visible. An external alert sink arrives with the outbox (v1.4 S5). |
| A-10 | 0 | Tenancy | Phase 0 tables (heartbeats, alerts, app_meta, demo_placeholder) are system tables with no `tenant_id`. Tenant tables and row-level security (SEC-16) start with the first tenant-owned data in phase 1. | No tenant data exists yet. |
| A-11 | 0 | Sign-in | Phase 0 has no sign-in. The app binds to localhost in docker compose. Local accounts and TOTP arrive in phase 5 as the brief orders. | Brief phase order. Not for exposure to a network before phase 5. |
| A-12 | 0 | "i" for non-calculated fields | Fields that are recorded, not calculated, show "Formula: None" and an example value. Only calculated fields must have a formula and a code-checked worked example. | A formula for a recorded value would be invented. |
| A-13 | 0 | "i" on the health strip | The strip has one "i" for Status, not one per component, since the six chips are the same field. The Overview table repeats each component with full columns. | Six identical buttons in the header would add noise without information. |
| A-14 | 0 | Demo clock vs. app clock | The seed uses a fixed clock (2026-01-15 09:00:00 UTC). The running app uses the real clock for new events such as alerts. | Seeded data must be identical on every run; live events must carry the real time. |
| A-15 | 0 | Open-source action pinning | CI actions are pinned to commit SHAs (SEC-46). | Resolved from the upstream tags on 2026-11-19. |
