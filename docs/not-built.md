# PRD requirements not built in the MVP

The MVP follows the six phases of the owner's brief. This list names what the PRD (v1.4 build spec and v1.5 addendum) asks for and the MVP does not have, with the reason. Each item is also named on the page where a user would look for it ("Not built yet").

## Not built

| Requirement | What is missing | Reason |
|---|---|---|
| FR-01 Cloud billing connectors | AWS, Azure and GCP cost ingestion. Only CSV files in a FOCUS-style layout are loaded. | Hard rule 1: no real provider may be called and no credential may be needed. V-1 (how providers report usage) is not verified. |
| FR-03 Allocation rule editor | Rules are seeded; there is no screen to create or change them, and no approval of rule changes. | Not in the brief's phases. One rule shows the split and the exact sums. |
| FR-04 Budget creation and cap changes | Budgets come from the seed. Owner and policy can be changed; caps, periods and new budgets cannot. | Not in the brief's phases. |
| FR-05 Streaming responses | The gateway refuses `stream: true`. | PRD v1.4 allows refusing it in P0; settling a stream that is cut off needs rules the brief did not ask for. |
| FR-05 Per-budget switch from fail-closed to fail-open | The fail mode follows the policy. | SD-04 is a pending decision; the default is built. |
| FR-07 Invoice PDF upload and review queue | Invoices are loaded as CSV files. | D-05 is a pending decision; PDF parsing is an untrusted-file surface that needs a sandbox. |
| FR-08 Forecasts and anomaly alerts | Nothing. | No phase in the brief. |
| FR-09, FR-10 Optimization and recommendations | Nothing. | P1 in the PRD. |
| FR-11 Approval chains, delegation, budget-increase requests | One approver decides. | PRD marks these P1. The P0 subset (held requests and two-person actions) is built. |
| FR-12 Period close and locking; scheduled reports; chargeback posting | Reports are produced on demand. | Not in the brief's phases. Scheduled delivery needs e-mail and recipient verification (SEC-29). |
| FR-13 SSO (SAML, OIDC), SCIM, WebAuthn | Local accounts with password and TOTP only. | P1 in the PRD (D-06 default). |
| FR-13 Self-service password change | An administrator resets a user's sign-in. | Kept out to limit the account surface in the MVP. |
| FR-13, SEC-16 Row-level security per tenant | Queries filter by tenant; PostgreSQL RLS is not switched on. | The MVP runs one tenant. Needs a per-request tenant setting on every connection of both services. |
| FR-14 Integration API, webhooks, outbox | Nothing. | No phase in the brief. |
| FR-15, FR-16 Assistant and agent-level analytics | Nothing. | P1 and P2 in the PRD. |
| FR-17 Owner alerts by e-mail or in-app notification | Unowned spend is shown; owners are not notified. | No alerting channel exists in the MVP (assumption A-2 of the PRD is not verified). |
| FR-18 Time-boxed block override | None. A block is lifted for good by two people. | SD-03 default is "none". |
| FR-18 Registering a model and editing prices from the UI | The registry is seeded; unregistered names are listed. | Not in the brief's phases. |
| FR-20 Egress control, "Enforced" coverage | The coverage badge never says Enforced; the Egress health item stays Unknown. | Needs network policy outside the application. UX-D1 and SD-01 are pending decisions. |
| FR-21 Canary requests and self-tests | Heartbeats and failure alerts exist; synthetic canaries do not. | Not in the brief's phases. |
| FR-22 Runbooks, severity response targets, tabletop exercises, customer notification | The kill switch exists; the operating process does not. | Operations, not software. SD-10 is pending. |
| SEC-13 Admin REST API for the kill switch | The kill switch is a form on the Admin page. | There is no separate admin API in the MVP. |
| SEC-21, SEC-24, SEC-26 TLS termination, KMS, key rotation, deletion including backups | The demo runs on `http://localhost` with keys in a local `.env`. | Deployment concerns; SD-06 to SD-08 are pending. |
| SEC-31 Every gateway denial in the audit chain | Denials are in the gateway decision record, with a feed on the Gateway page. | They would dominate the chain. Recorded as assumption A-87. |
| SEC-32 Signed chain head anchored outside the database | The chain and its head are in the database. | Needs a KMS and write-once storage, which an offline demo cannot have. The limit is stated in the UI. |
| Real model providers and provider key custody | A mock provider and a mock vault. | Hard rule 1. |

## Pending decisions

The MVP implements the stated default for each open decision and labels it "Pending decision" in the UI. None was decided by engineering: SD-01, SD-02, SD-03, SD-04, SD-10, D-03, D-05, D-06, D-07, UX-D1, UX-D2.

## Not verified

V-1 to V-8 in `docs/architecture/verification.md` (for example how real providers report usage, and the existing alerting stack) could not be verified without access to real systems. Nothing in the MVP depends on them, and nothing in it should be read as a statement about a real provider.
