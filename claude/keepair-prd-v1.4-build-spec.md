# KeepAir — Unified AI & Multi-Cloud FinOps Platform

**Product Requirements Document with Build Specification — v1.4**

**Date:** November 19, 2026
**Status:** Proposed. Architecture review complete. Open decisions marked ⚠ require product sign-off before engineering commits to them.
**Supersedes:** v1.3 (Nov 19, 2026)
**Sources:** Market and Capability Study (Nov 19, 2026); PRD v1.3; existing gateway foundation as described by the product owner (see Assumptions A-1 to A-5).

---

# Part A — Architect's Buildability Review of v1.3

## A.1 Verdict

v1.3 states *what* the product must do clearly. It does not yet state *how* enforcement can be proven, and that is the product's core claim. The three most serious gaps are:

1. **Enforcement is only as strong as key custody.** If customers keep their own provider keys, any agent can call a provider directly and skip the gateway. v1.3 mentions this as a limitation but does not require a control for it.
2. **Fail-open is applied to the wrong thing.** v1.3 uses one fail policy for both budget checks and vendor/model blocks. A vendor block is a security control and should never fail open.
3. **Several requirements cannot be built as written** because a number, a dependency or a behavior is undefined (see A.2).

## A.2 Findings and resolution

Each finding is marked **Fixed** (resolved in this version with a stated rule) or **⚠ Open** (needs your decision; options and recommendation are in Section 12).

| ID | Sev | Section | Finding | Resolution |
|---|---|---|---|---|
| B-01 | Critical | FR-05 | Enforcement can be bypassed by direct provider calls when the customer holds provider keys. | **Fixed:** hard-limit enforcement requires KeepAir-custodied provider keys (FR-05, FR-14). Detection-only mode is allowed for customer keys. Choice of whether to allow customer keys for hard limits is ⚠ D-02. |
| B-02 | Critical | Section 6, FR-05 | One fail policy covers budgets and vendor/model blocks. Blocks would fail open during an outage. | **Fixed:** blocks and budgets have separate fail rules. Blocks never fail open (FR-05, FR-18). |
| B-03 | High | FR-05 | "Documented maximum reconciliation tolerance" is undefined. Engineers cannot test it. | **Fixed:** tolerance defined as the maximum single-request overshoot, bounded by the estimator (FR-05 build notes). |
| B-04 | High | FR-05 | Streaming responses are not covered. Cost is known only at the end of the stream, and clients can disconnect mid-stream. | **Fixed:** streaming rules added (FR-05). |
| B-05 | High | FR-05 | "Approval required" holds requests but the spec does not say where held requests live or how a hold consumes budget. | **Fixed:** HELD reservation state with expiry (FR-05, FR-11). |
| B-06 | High | FR-06 | No canonical model and vendor identity. Aliases (for example, a model name used through a different vendor endpoint) can evade a model block. | **Fixed:** canonical registry and alias resolution with default deny (FR-18). |
| B-07 | High | FR-06 | Attribution from client headers can be spoofed. | **Fixed:** principal is derived from the gateway credential only (FR-05, FR-06). |
| B-08 | High | FR-01 | Provider usage granularity (per key or per project) is assumed but not verified. Bypass detection and reconciliation depend on it. | ⚠ Blocking verification V-1 before P0 (Section 3). Cannot be resolved by the architect. |
| B-09 | High | Success Metrics, FR-07 | The 99.5% invoice reconciliation target assumes provider invoices are available through an API. They may not be. | ⚠ D-05. Build plan supports upload and customer ERP as the fallback. |
| B-10 | High | FR-17 | P0 owners are "users in the connected identity source," but SSO and SCIM are P1. P0 has no identity source. | **Fixed:** P0 owners are KeepAir local user accounts. Identity-source linkage is P1 (FR-17). Confirmation is ⚠ D-06. |
| B-11 | Medium | FR-05 | Policy changes have no propagation requirement. A newly blocked model could keep serving for minutes. | **Fixed:** block propagation SLO and staleness rule (FR-18). |
| B-12 | Medium | FR-05 | Lifting a block has no control. A single admin could re-enable a blocked vendor. | **Fixed:** lifting a block requires a second administrator. |
| B-13 | Medium | FR-06 | Reservation estimator is undefined. A non-conservative estimate breaks the hard-limit guarantee. | **Fixed:** conservative estimator with a defined bound (FR-05). Utilization trade-off is ⚠ D-04. |
| B-14 | Medium | FR-08 | "Mean and standard deviation over four weeks" fails when a project is new or has irregular usage. | **Fixed:** handled by the cold-start rule and a minimum non-zero-day count (FR-08). |
| B-15 | Medium | Section 6 | RPO/RTO is stated for reservations but the store is not named. The implementation choice affects the guarantees. | **Fixed:** PostgreSQL is the single source of truth for ledger and reservations (Section 2). |
| B-16 | Medium | Success Metrics | The p95 100 ms gateway latency target has no stated deployment assumption (region, pool size, database locality). | **Fixed:** latency budget is decomposed per step with a stated deployment assumption (Section 2.4). |
| B-17 | Medium | FR-16 | Agent-level cost requires agent identity. The gateway token model does not state how agents are identified. | **Fixed:** each agent has its own gateway credential (FR-05, FR-17). |
| B-18 | Low | FR-02 | The FOCUS conformance report has no defined output. | **Fixed:** report format defined (FR-02). |
| B-19 | Low | Section 4 | P0 includes Kubernetes-free recommendations but Phase 2 includes Kubernetes allocation with no dependency noted. | **Fixed:** dependency added to P1 (Section 4). |

**Blocking verifications (must pass before P0 build starts):** V-1 provider usage granularity; V-2 policy store status values; V-3 observability and alerting stack; V-4 existing database engine.

---

# Part B — PRD v1.4 with Build Specification

## Revision Summary (v1.3 → v1.4)

| # | Change | Review ref | Section |
|---|---|---|---|
| 1 | Added Section 2 (Build Foundation): architecture, assumptions, stack, data model, API surface, sequencing, test strategy. | All | 2 |
| 2 | Hard-limit enforcement requires KeepAir-custodied provider keys; detection-only for customer keys. | B-01 | FR-05, FR-14 |
| 3 | Vendor and model blocks split from budget fail policy; blocks never fail open. | B-02 | FR-05, FR-18 |
| 4 | Reconciliation tolerance defined. | B-03 | FR-05 |
| 5 | Streaming and hold rules added. | B-04, B-05 | FR-05, FR-11 |
| 6 | Canonical model and vendor registry with default deny. | B-06 | FR-18 |
| 7 | Principal derived from credential, never headers. | B-07 | FR-05, FR-06 |
| 8 | Owners are local KeepAir accounts in P0. | B-10 | FR-17 |
| 9 | Block propagation SLO and staleness rule; two-person rule to lift a block. | B-11, B-12 | FR-18 |
| 10 | Estimator defined. | B-13 | FR-05 |
| 11 | Spike baseline handles new and irregular projects. | B-14 | FR-08 |
| 12 | Each build note cites its requirement. Open decisions D-01 to D-09 added. | All | Section 12 |

---

## 1. Executive Summary

KeepAir is a unified platform for monitoring, attributing, controlling and optimizing spending across artificial intelligence services, cloud infrastructure and selected SaaS applications.

Its primary differentiator is combining traditional FinOps visibility with real-time AI cost governance and enforceable financial policies. Enforcement is achieved through an AI gateway that sits between agents and model vendors. The gateway is the enforcement boundary. Its value depends on enforcement being proven by tests, not assumed.

The product will allow organizations to understand:

- Where technology spending occurs.
- Which departments, teams, projects, customers and AI agents generate costs.
- Whether spending aligns with budgets and business outcomes.
- Which expenses can be optimized.
- Which future expenses can be prevented before they occur.

**Product vision:** Transform technology spending from reactive financial reporting into proactive, automated financial governance.

## 2. Build Foundation

This section is cross-cutting. Requirement-level build notes appear in Sections 5 and 6.

### 2.1 Assumptions about the existing foundation

These must be verified in step S0 (Section 2.6). Where an assumption is wrong, the affected build notes must be revised before work starts.

| ID | Assumption | Verify by |
|---|---|---|
| A-1 | The existing policy store marks vendors and models with a status of Blocked or Allowed, and a vendor Blocked status overrides a model Allowed status. Unknown status is not yet confirmed to exist. | V-2 |
| A-2 | Observability, alerting and dashboards exist and accept metrics, logs and alert rules from application code. Their technology is not confirmed. | V-3 |
| A-3 | The gateway is implemented in Python with FastAPI, per the product owner's notes. The code will live in a new branch (dev) of the existing repository, not on main. | Repo check |
| A-4 | A relational database is available or can be added. This spec assumes PostgreSQL 16. | V-4 |
| A-5 | Provider usage APIs return usage with enough granularity (per API key or per project) to reconcile gateway records. Not verified. | V-1 |

### 2.2 Architecture overview

```
 Agent / app ──(gateway token)──► [ KeepAir Gateway ] ──(provider key from vault)──► Vendor API
                                    │   1. authenticate (token → principal)
                                    │   2. canonicalize vendor/model
                                    │   3. evaluate block policy (snapshot)
                                    │   4. estimate cost
                                    │   5. reserve budget (single transaction)
                                    │   6. dispatch via adapter
                                    │   7. settle reservation
                                    ▼
                         PostgreSQL (source of truth)
          policies · registry · budgets · reservations · usage_events · audit_log · outbox
                                    │
                         Outbox worker ──► metrics / logs / alerts / dashboards (existing stack)
                                    │
             Ingestion workers ──► cloud billing exports, provider usage APIs, invoice uploads
                                    │
                         Reconciliation worker ──► uncontrolled-spend detection, drift reports
```

**Components:**

| Component | Responsibility | Notes |
|---|---|---|
| Gateway API | Accepts agent requests in OpenAI-compatible and Anthropic-compatible shapes. | FastAPI. Stateless. Horizontally scaled. |
| Policy engine | Pure function: `evaluate(request_context, policy_snapshot) → Decision`. | No I/O. Deterministic. |
| Policy snapshot cache | In-process, versioned copy of registry and policies. | Refreshed by PostgreSQL LISTEN/NOTIFY. Max staleness per FR-18. |
| Budget ledger | Reservation and settlement against budget hierarchy. | Transactional. Row locks. |
| Provider adapters | One per vendor. Implement a common `dispatch()` protocol. | Mock adapter for tests. |
| Secrets vault | Holds KeepAir-custodied provider keys. | KMS-backed. Keys decrypted in memory only. |
| Outbox worker | Publishes events to existing observability and alerting. | At-least-once delivery, deduplicated by event ID. |
| Ingestion workers | Pull cloud exports, provider usage, uploaded invoices. | Idempotent by source key. |
| Reconciliation worker | Compares gateway records with provider and cloud records. | Scheduled. Emits drift events. |
| Admin API | Policies, budgets, owners, overrides, approvals. | Separate credentials and routes from gateway. |

### 2.3 Technology choices and rationale

| Area | Choice | Rationale |
|---|---|---|
| Language and API | Python 3.12, FastAPI, Pydantic v2 | Matches existing gateway (A-3). Pydantic enforces request and config schemas at the boundary. |
| Database | PostgreSQL 16 | Row-level locks give atomic multi-row budget reservation without a separate lock service. Fewer failure modes than Redis-based counters for money. |
| ORM and migrations | SQLAlchemy 2.x (Core for ledger SQL), Alembic | Ledger SQL must be explicit. Migrations are versioned. |
| Caching and invalidation | In-process snapshot + PostgreSQL LISTEN/NOTIFY | Avoids a Redis dependency on the enforcement path. Propagation is bounded (FR-18). |
| Money | Integer micro-units (`BIGINT`, 1 unit = 1e-6 of currency) plus ISO currency code | No floating point in financial math. Currency conversion is separate (Section 6, multi-currency). |
| Identifiers | UUIDv7 for records, opaque random tokens for gateway credentials (stored as SHA-256 hashes) | Time-ordered IDs aid debugging. Hashed tokens prevent credential exposure from a database leak. |
| Time | Injected `Clock` interface, UTC only | Makes time-dependent tests deterministic. |
| Randomness | Injected seed where used | Deterministic tests. |
| Outbound HTTP | httpx with explicit timeouts | Timeouts are required for reservation expiry logic. |
| Observability | OpenTelemetry SDK exporting to the existing stack (A-2) | Vendor-neutral. |
| Tests | pytest, hypothesis (property tests), testcontainers for PostgreSQL, respx for HTTP mocking | All run offline with no provider credentials (Section 2.7). |

### 2.4 Latency budget (FR-05, p95 target)

Deployment assumption: gateway and PostgreSQL in the same cloud region and same availability zone group, connection pool warm.

| Step | Budget (p95) |
|---|---|
| Token authentication (cached principal) | 2 ms |
| Canonicalization and policy evaluation (in memory) | 1 ms |
| Estimation | 1 ms |
| Reservation transaction (2–4 budget rows) | 15 ms |
| Audit and outbox write (same transaction as reservation) | included above |
| Settlement transaction | 15 ms (off the critical path where possible) |
| **Total added before dispatch** | **≤ 25 ms** |

The 100 ms target in Section 2 leaves headroom for load and cross-AZ latency. If the measured p95 exceeds 60 ms in pilots, investigate database locality before changing the target.

### 2.5 Data model (PostgreSQL)

Tables are the minimum required. Constraints are normative.

```sql
-- Registry: canonical vendors and models (A-1, FR-18)
vendors (
  id              text primary key,            -- canonical, e.g. 'openai', 'anthropic'
  status          text not null check (status in ('ALLOWED','BLOCKED')),
  updated_at      timestamptz not null,
  version         bigint not null               -- increments on every change
);
models (
  id              text primary key,            -- canonical, e.g. 'openai/gpt-x'
  vendor_id       text not null references vendors(id),
  status          text not null check (status in ('ALLOWED','BLOCKED')),
  input_price_micros_per_1k  bigint not null,
  output_price_micros_per_1k bigint not null,
  max_output_tokens integer not null,
  price_version   integer not null,
  version         bigint not null
);
model_aliases (
  alias           text primary key,            -- lowercased, trimmed
  model_id        text not null references models(id)
);
-- Unknown alias or model => DENY (FR-18). There is no row for unknown.

-- Principals and credentials (FR-05, FR-17)
projects (id uuid pk, name text, owner_user_id uuid references users(id), created_at timestamptz);
agents   (id uuid pk, project_id uuid references projects(id), name text, created_at timestamptz);
gateway_credentials (
  id uuid pk, token_hash bytea unique not null,  -- SHA-256 of token
  principal_type text check (principal_type in ('PROJECT','AGENT')),
  principal_id uuid not null, revoked_at timestamptz, created_at timestamptz
);
users (id uuid pk, email text unique, role text, created_at timestamptz);

-- Budgets (FR-04)
budgets (
  id uuid pk, parent_id uuid references budgets(id),
  scope_type text check (scope_type in ('ORG','BU','DEPT','TEAM','PROJECT','APP','AGENT')),
  scope_id uuid not null,
  cap_micros bigint not null check (cap_micros >= 0),
  currency char(3) not null,
  period text check (period in ('MONTH','QUARTER','YEAR')),
  period_start date not null,
  mode text check (mode in ('INDEPENDENT','SUBDIVISION')),
  policy text check (policy in ('MONITOR','SOFT','HARD','APPROVAL')),
  fail_mode text check (fail_mode in ('FAIL_OPEN','FAIL_CLOSED')),
  owner_user_id uuid references users(id),        -- required before HARD (FR-17)
  committed_micros bigint not null default 0,     -- settled spend
  reserved_micros bigint not null default 0,      -- open reservations
  version bigint not null default 0,
  check (committed_micros >= 0 and reserved_micros >= 0)
);

-- Reservations (FR-05)
reservations (
  id uuid pk,
  idempotency_key text, principal_id uuid not null,
  state text not null check (state in ('HELD','RESERVED','SETTLED','RELEASED','EXPIRED','UNKNOWN')),
  model_id text not null references models(id),
  reserved_micros bigint not null,
  actual_micros bigint,
  budget_path uuid[] not null,                    -- ancestors incl. self
  expires_at timestamptz not null,
  created_at timestamptz not null, settled_at timestamptz,
  usage_known boolean not null default true
);

-- Idempotency (FR-05)
idempotency_keys (
  principal_id uuid, key text, request_hash bytea,
  reservation_id uuid references reservations(id),
  response_status int, response_ref text,
  created_at timestamptz,
  primary key (principal_id, key)
);

-- Usage and audit (FR-06, FR-12)
usage_events (
  id uuid pk, reservation_id uuid references reservations(id),
  provider text, model_id text, principal_id uuid,
  team text, project text, customer text, application text, agent text, environment text,
  input_tokens int, output_tokens int, actual_micros bigint,
  source text check (source in ('GATEWAY','SDK','PROVIDER_API','INVOICE')),
  occurred_at timestamptz not null, ingested_at timestamptz not null
);
audit_log (
  id bigserial pk, occurred_at timestamptz not null,
  actor_id uuid, action text not null, subject_type text, subject_id text,
  before jsonb, after jsonb, reason text,
  prev_hash bytea not null, row_hash bytea not null          -- hash chain (tamper evidence)
);
fail_events (
  id uuid pk, occurred_at timestamptz, kind text check (kind in ('FAIL_OPEN','FAIL_CLOSED','SNAPSHOT_STALE','RESERVATION_EXPIRED','UNCONTROLLED_SPEND')),
  budget_id uuid, reservation_id uuid, detail jsonb, acknowledged_at timestamptz
);
outbox (id uuid pk, created_at timestamptz, topic text, payload jsonb, published_at timestamptz);
```

**Critical constraint:** `reservations` and the budget counter updates must be written in the same database transaction. The audit row and outbox row for the same action must also be in that transaction.

### 2.6 Sequencing and dependencies

| Step | Work | Depends on | Exit criterion |
|---|---|---|---|
| S0 | Verify V-1 to V-4 and assumptions A-1 to A-5. Record results in `docs/architecture/verification.md`. | — | All four verifications recorded; any failure triggers a spec revision. |
| S1 | Registry, alias resolution, policy engine (pure) with property tests. | S0 | Policy test matrix passes (Section 2.7). |
| S2 | Schema, migrations, budget ledger (reserve, settle, release, expire). | S0 | Concurrency tests pass (Section 2.7). |
| S3 | Mock provider adapter, then OpenAI and Anthropic adapters. | S1, S2 | Adapter contract tests pass offline. |
| S4 | Gateway endpoints (non-streaming, then streaming) with idempotency. | S3 | Gateway integration tests pass against mock adapters. |
| S5 | Audit hash chain, outbox worker, metrics, alert rules. | S2 | Every fail event produces a metric, an alert and an audit row (tested). |
| S6 | Owners, two-person rule, HELD queue, approvals (basic). | S2, S4 | FR-17 and FR-11 tests pass. |
| S7 | Cloud billing ingestion (FOCUS adapters) and invoice upload. | S0 (V-1) | Ingestion fixtures pass. |
| S8 | Reconciliation and uncontrolled-spend detection. | S5, S7 | Bypass test suite passes (Section 2.7). |
| S9 | SDK instrumentation. | S4 | SDK contract tests pass. |
| S10 | Dashboards and reports. | S5, S7 | Dashboard data contracts pass. |

S1 and S5 can run in parallel with S2. S7 cannot start until V-1 is recorded.

### 2.7 Testing strategy

**Principles:** deterministic, mocked, offline. No test requires a real provider credential or network access beyond localhost. Time, randomness and provider behavior are injected.

**Test levels:**

| Level | Scope | Tooling | Runs in CI |
|---|---|---|---|
| Unit | Policy engine, estimator, alias resolution, money arithmetic | pytest | Every commit |
| Property | Policy precedence, reservation invariants | hypothesis | Every commit |
| Concurrency | Racing reservations on the same budget | pytest + asyncio + real PostgreSQL (testcontainers) | Every commit |
| Contract | Adapter request/response shape | respx with recorded fixtures | Every commit |
| Integration | Gateway end-to-end against mock adapter | FastAPI TestClient + PostgreSQL | Every commit |
| Bypass | Every bypass route in FR-05 and FR-18 | Integration suite | Every commit |
| Fault injection | Adapter timeout, DB failure mid-transaction, snapshot stale | Injected faults | Every commit |
| Reconciliation | Drift detection on synthetic usage | Fixture data | Nightly |

**Mandatory test cases (named, must exist):**

- `test_blocked_vendor_denies_even_when_model_allowed` (FR-18)
- `test_unknown_alias_denies` (FR-18)
- `test_alias_to_blocked_model_denies` (FR-18)
- `test_principal_ignores_client_headers` (FR-05, B-07)
- `test_reserve_never_exceeds_cap_under_200_concurrent_requests` (FR-05)
- `test_hierarchy_ancestor_cap_enforced_when_child_has_room` (FR-04)
- `test_db_failure_mid_reserve_leaves_no_partial_state` (FR-05)
- `test_timeout_after_dispatch_settles_at_reserved_and_flags_unknown` (FR-05)
- `test_expired_reservation_settles_and_alerts` (FR-05)
- `test_fail_open_is_counted_alerted_and_audited` (FR-05, FR-12)
- `test_block_fails_closed_when_snapshot_stale` (FR-18)
- `test_idempotent_retry_returns_same_result_without_double_reserve` (FR-05)
- `test_same_key_different_body_rejected` (FR-05)
- `test_streaming_disconnect_settles_once` (FR-05)
- `test_hold_expires_and_releases_budget` (FR-11)
- `test_uncontrolled_spend_detected_from_provider_usage_delta` (FR-07, FR-19)
- `test_audit_hash_chain_detects_tampering` (FR-12)
- `test_hard_limit_without_owner_cannot_activate` (FR-17)
- `test_lift_block_requires_second_admin` (FR-18)

**Fixtures:** provider responses are recorded once from sandbox or documentation examples and stored in `tests/fixtures/providers/`. Recording is a manual, separate step and never runs in CI.

---

## 3. Verification Gates (new)

No P0 build work may start until these pass. Each produces a written record.

| ID | Question | Method | Blocks |
|---|---|---|---|
| V-1 | Do OpenAI and Anthropic usage APIs report usage per API key or per project? At what time granularity and latency? | Read official documentation; test with a sandbox key if available. | FR-05 monitor-mode reconciliation, FR-07, FR-19, Section 6 freshness targets |
| V-2 | Does the existing policy store use exactly Blocked and Allowed? Is there an "unknown" state? How is vendor override implemented? | Read the policy store schema and tests. | FR-18 |
| V-3 | What observability, alerting and dashboard stack exists, and what metric and alert APIs does it expose? | Read the platform configuration. | FR-12, Section 6 |
| V-4 | Which database engine is in use? | Read the platform configuration. | Section 2.3, 2.5 |

---

## 4. Product Scope

### Phase 1 — Commercial Foundation (P0)

- AWS, Azure and GCP billing ingestion (per the ingestion matrix in FR-01).
- OpenAI and Anthropic AI usage integration (gateway and SDK).
- A versioned, FOCUS-compatible financial normalization model.
- Unified cost dashboard and organizational hierarchy.
- Allocation rules, shared costs and unallocated-cost reporting.
- AI-to-cloud join key specification with launch confidence thresholds (FR-06).
- Hierarchical budgets, alerts and basic forecasts.
- Basic cost-spike alerts with cold-start handling (FR-08).
- Commitment coverage, utilization and unused-commitment alerts (FR-09 matrix).
- Rightsizing and idle-resource recommendation ingestion (recommend only; FR-09 matrix applies).
- AI budget ownership assignment, with KeepAir local owner accounts (FR-17).
- AI gateway: canonical registry, vendor and model blocks, budget checks, enforcement via reverse proxy and SDK (FR-05, FR-18).
- Reconciliation, data-quality monitoring and audit logs.
- Uncontrolled-spend detection (FR-19).
- Tenant isolation and enterprise RBAC.
- Basic showback reports and CSV exports.
- Public price list and billing metric.

### Phase 2 — Enterprise Expansion (P1)

- Provider-native organization and project controls as an enforcement method, where sufficient for policy. Requires V-1 confirmation.
- Additional AI-provider integrations: Bedrock, Azure OpenAI, Vertex AI and Cursor, subject to integration feasibility.
- Kubernetes allocation through OpenCost-compatible data. **Dependency:** requires the cloud ingestion pipeline in P0 and OpenCost export format verification.
- Advanced anomaly detection and forecasting (machine-learning methods).
- Approval Center and exception workflows (full version; basic HELD queue is in P0).
- Model-routing policies and optimization suggestions.
- SSO, SCIM and integration APIs. **Dependency:** identity-source linkage for FR-17 owners.
- Custom business dimensions and customer-level unit economics.
- Chargeback workflows and scheduled reporting.

### Phase 3 — Intelligent Optimization (P2)

- Natural-language FinOps assistant.
- Cost-aware deployment checks.
- Agent profitability and outcome analytics.
- Automated optimization workflows with approvals.
- Scenario simulations and financial planning.
- Broader SaaS and data-platform cost integrations.
- Optional automated commitment purchasing following separate risk and economic evaluation.

---

## 5. Functional Requirements

### FR-01: Multi-Cloud and AI Ingestion

Connect to:

- AWS Cost and Usage data, including supported Data Exports / CUR.
- Azure Cost Management billing exports.
- Google Cloud Billing exports through BigQuery.
- OpenAI and Anthropic usage and billing sources (P0).

**Ingestion support matrix (P0):**

| Source | Export type | FOCUS status | Launch scope |
|---|---|---|---|
| AWS | Data Exports / CUR 2.0 | Version to be confirmed against AWS documentation before pinning | Full |
| Azure | Cost Management export | Version to be confirmed against Azure documentation before pinning | Full |
| GCP | BigQuery billing export | Version to be confirmed against Google documentation before pinning | Full |
| OpenAI | Usage and billing API | Not FOCUS. Adapter required. | Full, subject to V-1 |
| Anthropic | Usage and billing API | Not FOCUS. Adapter required. | Full, subject to V-1 |

Requirements:

- Read-only access wherever feasible.
- Historical import with clearly disclosed lookback limitations.
- Incremental synchronization.
- Source-specific ingestion status and error diagnostics.
- Recovery from temporary API failures.
- Idempotent processing to prevent double counting.
- Handling of credits, refunds, taxes, adjustments and late-arriving billing records.
- Support for multiple accounts, subscriptions, projects and billing entities within a tenant.

**Acceptance criteria:**

- Each supported provider passes an end-to-end ingestion test using real billing samples.
- Duplicate ingestion produces no duplicate financial records.
- A previously imported billing period can be corrected without corrupting the audit history.
- AWS and GCP pass equivalent **allocation and reporting** tests for supported use cases. Recommendation parity is governed by the FR-09 matrix.

**Build notes:**

- Ingestion workers are idempotent by `(source, source_record_key, revision)`. Each record stores a revision number. A corrected period inserts a new revision and marks the prior one superseded. Nothing is deleted.
- Each source adapter implements `fetch_window(start, end) → Iterable[RawRecord]` and `normalize(RawRecord) → NormalizedRecord`. Normalization is pure and fixture-tested.
- Credentials for cloud sources are read-only roles (for example, an AWS role with `ce:Get*` and S3 read on the export bucket; Azure Cost Management Reader; GCP BigQuery Data Viewer on the export dataset). Document the exact permissions in the onboarding guide and test that no write permission is required.
- Storage: raw records in `raw_billing_records` (JSONB, append-only). Normalized records in `normalized_cost_records`.
- Test: `test_reingest_same_period_is_idempotent`; `test_corrected_period_creates_new_revision_and_preserves_history`; fixtures per provider in `tests/fixtures/billing/`.
- Depends on: S0 (V-1 for AI sources), S2 (schema).

### FR-02: Unified Financial Data Model

All normalized records must include, where available:

- Source provider and billing account.
- Resource or service identifier.
- Usage period and billing period.
- Usage amount and usage unit.
- Billed, effective and amortized costs where applicable.
- Currency, exchange-rate metadata and conversion basis.
- Organization, department, team and project.
- Model, application, agent or customer identifiers.
- Allocation-rule and lineage references.
- Ingestion timestamp, source version and data-quality state.

FOCUS compatibility must be versioned and supported by an automated conformance report.

Raw billing information must remain available alongside normalized records.

Do not pin an unverified provider export version. Maintain provider-specific adapters and the support matrix in FR-01.

**Build notes:**

- Money fields are `BIGINT` micro-units plus ISO 4217 currency code. No `float` or `numeric` arithmetic outside the `Money` value type, which uses `Decimal` with explicit quantization.
- **FOCUS conformance report** (B-18): output is a JSON document per dataset with fields `{focus_version, dataset_id, checked_at, columns_present[], columns_missing[], type_errors[], row_count, pass: bool}`, plus an HTML rendering for admins. Conformance checks run on every ingestion batch. A failing batch is quarantined, not loaded, and emits a `DATA_QUALITY` event.
- The FOCUS version is a config value per adapter, not a constant in code. Changing it requires a migration note and a fixture update.
- Test: a golden-file test per provider comparing normalized output to expected output.

### FR-03: Cost Allocation Engine

Support:

- Cloud tags and labels.
- Identity and directory mappings.
- API-key and gateway metadata.
- Project and application identifiers.
- Customer-level attribution where supplied.
- Rule-based virtual allocation.
- Percentage and usage-based shared-cost splitting.
- Rule priorities and conflict handling.
- Unallocated-spend buckets.
- Effective-dated rules and historical reprocessing.

Allocation confidence must distinguish direct attribution from inferred or manually assigned attribution.

**Acceptance criteria:**

- Every eligible spend record is either allocated or explicitly classified as unallocated.
- Allocation percentages reconcile to 100% for the applicable cost basis.
- Conflicting rules produce deterministic results and visible explanations.
- Users can inspect the rule, source and confidence behind an allocated amount.
- Reallocation produces an auditable change history.

**Build notes:**

- Rules are stored as `allocation_rules (id, priority, effective_from, effective_to, match jsonb, split jsonb, version)`. The engine evaluates rules in priority order, ties broken by `id`, so results are deterministic.
- Allocation is a pure function over normalized records and rules, written to `allocation_facts` with `rule_version` and `confidence ∈ {DIRECT, INFERRED, MANUAL}`.
- Reprocessing a period recomputes facts; prior facts are retained with `superseded_by`.
- Test: property test that allocated shares sum to 100% (within one micro-unit rounding rule: largest-remainder method); determinism test across shuffled input order.

### FR-04: Hierarchical Budget Management

Budgets must support:

Organization → Business Unit → Department → Team → Project → Application / Agent.

Required capabilities:

- Monthly, quarterly and annual budgets.
- Currency-aware budgets.
- Actual spend, forecast, remaining budget and variance.
- Threshold alerts, including configurable 50%, 80%, 90% and 100% examples.
- Budget rollovers where explicitly configured.
- Budget ownership (human owner, see FR-17) and delegated administration.
- Budget transfer and exception workflows.
- Configurable parent-child consumption and enforcement rules.

**Important:** Budget hierarchy does not automatically mean that every child has an additional spend allowance. Each budget must be explicitly configured as either:
- An independent cap, or
- A subdivision of an inherited parent cap.

The default is independent cap. The UI must warn when a subdivision configuration would risk double-counting and must display the effective remaining allowance after parent constraints.

**Build notes:**

- **Effective remaining allowance** for a budget `b` with ancestor path `P(b)` (including `b`):
  - For each `x` in `P(b)` where `x` is `HARD` or `APPROVAL` policy: `remaining(x) = cap(x) − committed(x) − reserved(x)`.
  - `effective_remaining(b) = min over x in P(b) of remaining(x)`.
  - `INDEPENDENT` budgets do not contribute their parent's remaining to their own cap. `SUBDIVISION` budgets are checked against all ancestors. This rule is the only definition used by the gateway and the UI.
- Monitor and soft-limit budgets are evaluated but never block.
- Test: `test_hierarchy_ancestor_cap_enforced_when_child_has_room`; `test_independent_child_ignores_parent_remaining_for_own_cap`; property test that `effective_remaining` is never negative after any sequence of reserve and settle operations.
- Depends on: S2.

### FR-05: AI Spending Enforcement

Create an AI gateway that can:

- Authenticate a calling service, team, project or agent.
- Evaluate the request against financial policies.
- Estimate request cost using model pricing, input size and configured assumptions.
- Reserve an estimated budget amount before execution.
- Permit, reject, queue or require approval based on policy.
- Record actual usage after completion.
- Reconcile the reservation against actual usage.
- Support concurrency-safe enforcement and retry protection.

**Interception methods:**

- **P0:** reverse proxy / gateway endpoint (customer routes traffic to KeepAir). This is the enforcement boundary.
- **P0:** SDK instrumentation. This is a convenience and attribution layer. It is **not** an enforcement boundary, because the SDK can be reconfigured to call a provider directly. Enforcement claims apply only to traffic that carries a gateway credential and reaches the gateway (see B-01 and FR-14).
- **P1:** provider-native organization or project controls, where sufficient for the policy in question.

**Enforcement boundary rule (B-01):** A hard limit is enforceable only if the provider credentials used for that project are held by KeepAir's vault and are not available to agents. For projects with customer-held keys, KeepAir can monitor and alert but cannot enforce. The UI must state this per project. Whether customer keys may ever back a hard limit is ⚠ **D-02**.

**Policy modes and fail behavior:**

| Policy mode | Budget check failure (gateway or DB unavailable) | Vendor or model block failure |
|---|---|---|
| Monitor only | Allow and log | **Deny** (block is never fail-open) |
| Soft limit with notification | Allow, log and alert | **Deny** |
| Hard limit | **Deny** (fail-closed). Fail-open requires an explicit per-budget override. | **Deny** |
| Approval required | Hold and queue. Fail-closed. | **Deny** |
| Emergency override | Per the override record; always audited | **Deny** unless the block itself has an override (FR-18) |

A per-budget switch from fail-closed to fail-open on a hard limit requires confirmation from both the budget owner and an administrator. The change is recorded in the audit log.

Policy modes:

- Monitor only.
- Soft limit with notification.
- Hard limit.
- Approval required.
- Emergency override with audit trail.

**Acceptance criteria:**

- Concurrent requests cannot exceed a strict gateway-controlled budget beyond the documented maximum overshoot (defined below).
- Budget reservations expire or settle after failures and timeouts.
- Rejected requests return structured reasons.
- Every override records actor, reason, timestamp and affected scope.
- Every request passed under fail-open is logged and counted in the fail-open report.
- The UI explicitly distinguishes gateway-controlled spending from spending occurring outside KeepAir.
- Enforcement cannot be activated on a budget without an accountable human owner (see FR-17).
- Documented, tested integration patterns exist for OpenAI and Anthropic.

**Limitation:** Direct calls to external AI services cannot be blocked unless the customer routes them through an enforceable control point. KeepAir must display the share of AI spend that is gateway-controlled and the share that is not.

**Build notes — request path (normative order; each step is a separate function with its own test):**

1. **Authenticate.** Read `Authorization: Bearer <token>`. Compute SHA-256. Look up `gateway_credentials` (cached per token for 30 s, and invalidated on revocation). Resolve principal (`PROJECT` or `AGENT`). Reject with 401 if missing, revoked or unknown. Client headers such as `X-Team` or `X-Project` are **ignored for attribution** (B-07). They may only be logged as untrusted metadata.
2. **Parse and validate** the body with Pydantic. Reject unknown provider routes with 404. Reject bodies over the configured max size with 413 before parsing.
3. **Canonicalize.** Normalize the requested model string (trim, lowercase). Look up `model_aliases`. If missing, deny with reason `UNKNOWN_MODEL` (FR-18). Resolve `vendor_id` from the model row. The vendor on the route must match `vendor_id`; mismatch denies with `VENDOR_ROUTE_MISMATCH`.
4. **Policy block check** (FR-18). Deny on vendor BLOCKED, then model BLOCKED, then model not ALLOWED. This step never fails open.
5. **Estimate.** `input_tokens_upper = max(tokenizer_count(prompt), ceil(prompt_bytes / 2))` when a tokenizer is unavailable for the model. `output_tokens_upper = min(request.max_tokens or models.max_output_tokens, models.max_output_tokens)`. Cost = `ceil(input_tokens_upper × input_price / 1000) + ceil(output_tokens_upper × output_price / 1000)`. Use the price version active at request time and store it on the reservation. Tool calls and cached-prompt discounts are costed at full price (conservative). This estimator is **the only** estimator; its upper bound is the basis for the overshoot guarantee below.
6. **Reserve** in one transaction (see Section 2.5 and the pseudo-code below). Outcomes: `RESERVED`, `HELD` (approval policy), or deny with a structured reason (`BUDGET_EXHAUSTED`, `BUDGET_FAIL_CLOSED`, `NO_OWNER`).
7. **Dispatch** through the vendor adapter with an explicit timeout `T` (configured per model, default 120 s). Provider key is fetched from the vault for this call only.
8. **Settle.** On success, parse usage from the provider response. Set `actual_micros`. Release `reserved − actual` if positive. If `actual > reserved`, record `overrun` on the reservation and in `fail_events` only if above the alert threshold (default: any overrun). On timeout or connection error after dispatch, settle at `reserved` with `usage_known = false` and emit `UNKNOWN_USAGE`. On failure before dispatch, release fully.
9. **Respond** with the provider payload plus gateway headers (`X-KeepAir-Reservation-Id`, `X-KeepAir-Decision`). Gateway headers are informational and never trusted by the client for policy.

**Reservation transaction pseudo-code (PostgreSQL, Python, SQLAlchemy Core):**

```python
async def reserve(session, principal, budgets_path, cost_micros, model_id, key):
    # 1. lock all budget rows on the path in a fixed order to avoid deadlocks
    rows = await session.execute(
        select(budgets)
        .where(budgets.c.id.in_(budgets_path))
        .order_by(budgets.c.id)
        .with_for_update()
    )
    budgets_by_id = {r.id: r for r in rows}
    # 2. evaluate effective_remaining for every enforcing ancestor (FR-04)
    for b in enforcing(budgets_by_id, budgets_path):
        if cost_micros > effective_remaining(b, budgets_by_id):
            raise Deny("BUDGET_EXHAUSTED", budget_id=b.id)
    # 3. write reservation, update counters, audit and outbox in THE SAME transaction
    res_id = uuid7()
    await session.execute(
        insert(reservations).values(
            id=res_id,
            state="RESERVED",
            reserved_micros=cost_micros,
            budget_path=budgets_path,
            expires_at=clock.now() + ttl(model_id),
            principal_id=principal.id,
            model_id=model_id,
            idempotency_key=key,
        )
    )
    await session.execute(
        update(budgets)
        .where(budgets.c.id.in_(budgets_path))
        .values(
            reserved_micros=budgets.c.reserved_micros + cost_micros, version=budgets.c.version + 1
        )
    )
    await write_audit(session, "RESERVE", res_id, ...)
    await write_outbox(session, "gateway.reserved", {...})
    return res_id
```

**Reservation TTL:** `request timeout T + 120 s`. A reservation not settled by its TTL is set to `EXPIRED`, settled at `reserved` with `usage_known = false`, and emits `RESERVATION_EXPIRED` (alert).

**Maximum overshoot (defines "documented tolerance", B-03):** For any hard-limit budget `x`, committed spend cannot exceed `cap(x) + Σ max_single_request_overshoot` for requests in flight. Because the estimator is an upper bound for input and capped output, overshoot only occurs when the provider reports usage above the upper bound. The **documented tolerance** is `max_overshoot_per_request = 1 request's estimator error bound`, which is measured in the pilot. Until measured, the gateway must report overshoot per request and the tolerance must be stated as "to be measured."

**Concurrency:** budget rows are locked with `SELECT ... FOR UPDATE` in ascending id order. Two requests on the same path serialize on the locked rows. Requests on disjoint paths do not block each other. Test `test_reserve_never_exceeds_cap_under_200_concurrent_requests` drives 200 concurrent tasks against one budget with a real PostgreSQL instance and asserts `committed + reserved ≤ cap + tolerance` at all times.

**Idempotency:** the `Idempotency-Key` header is required on all gateway writes. `idempotency_keys` stores `request_hash = SHA-256(canonical body)`.
- Same key and same hash, prior result stored: return the stored response, no new reservation.
- Same key and same hash, still in flight: return 409 with `Retry-After`.
- Same key and different hash: return 422. Never reserve.

**Streaming (B-04):**
- The reservation is made before the stream starts, using the same estimator with `max_tokens`.
- Usage is read from the final provider usage event. If the provider does not send one, settle at `reserved` with `usage_known = false`.
- If the client disconnects mid-stream, the gateway keeps reading the provider stream until completion or timeout, then settles **once**. The gateway does not cancel the provider stream on client disconnect, because cancelling does not reduce cost reliably. Test: `test_streaming_disconnect_settles_once`.
- Budget exhaustion does not interrupt an in-flight stream. The next request is denied. Recorded as a known limitation.

**HELD requests (B-05, Approval policy):** a HELD reservation reserves budget (state `HELD`, counted in `reserved_micros`) and has an approval expiry (default 24 h). Approval converts it to `RESERVED` and dispatches. Rejection or expiry releases it. Held requests are stored with their request body encrypted at rest, or the body is not stored and the approval is for the request metadata only (⚠ D-07). Test: `test_hold_expires_and_releases_budget`.

**Credentials and provider keys:**
- Gateway tokens are opaque, at least 256 bits of entropy, shown once at creation, stored as SHA-256 hash only. Rotation creates a new token and revokes the old one.
- Provider keys are stored in the vault, encrypted with a KMS data key. They are decrypted in memory per dispatch and never logged, never returned by any API, and never written to the outbox.

**Bypass routes (first-class; each has a test in the bypass suite):**

| Route | Control | Test |
|---|---|---|
| B-a. Agent calls provider directly with a customer-held key | Hard limits require KeepAir custody (D-02). Detection via reconciliation (FR-19). | `test_customer_key_project_cannot_activate_hard_limit` |
| B-b. Agent calls provider directly with a KeepAir-issued provider key that leaked | Keys are scoped per project where the provider allows. Reconciliation detects unmatched usage. Key rotation procedure in runbook. | `test_unmatched_provider_usage_raises_uncontrolled_spend` |
| B-c. Gateway token leaked and reused | Token is bound to principal; revocation is immediate (cache invalidation on revoke); anomaly alert on token use from new network (P1). | `test_revoked_token_rejected_within_cache_window` |
| B-d. Client spoofs team/project headers to charge another budget | Attribution from credential only. | `test_principal_ignores_client_headers` |
| B-e. Model alias maps to a blocked model | Canonical registry with default deny. | `test_alias_to_blocked_model_denies` |
| B-f. Same model through a different vendor endpoint | Route-vendor match check. | `test_vendor_route_mismatch_denies` |
| B-g. Retry storm to exceed budget | Idempotency keys and reservation before dispatch. | `test_idempotent_retry_returns_same_result_without_double_reserve` |
| B-h. Client disconnects mid-stream to avoid settlement | Gateway settles once after provider completes. | `test_streaming_disconnect_settles_once` |
| B-i. Gateway crash between reserve and dispatch | Reservation has TTL; expiry settles at reserved and alerts. | `test_expired_reservation_settles_and_alerts` |
| B-j. Gateway crash after dispatch, before settle | Same as B-i, with `usage_known = false`. | `test_timeout_after_dispatch_settles_at_reserved_and_flags_unknown` |
| B-k. Policy store stale (block not yet applied) | Snapshot staleness rule (FR-18). | `test_block_fails_closed_when_snapshot_stale` |
| B-l. Owner or override tampered to lift a limit | Two-person rule and hash-chained audit (FR-12, FR-17). | `test_lift_block_requires_second_admin`, `test_audit_hash_chain_detects_tampering` |
| B-m. Fail-open used silently | Every fail-open is counted, alerted and audited. | `test_fail_open_is_counted_alerted_and_audited` |

**Verification of "not bypassable" claims:** the bypass suite is the evidence. A claim in sales material that enforcement is complete must cite this suite and state the B-a condition (customer keys). Marketing copy must not say "all AI spend is controlled."

**Depends on:** S1, S2, S3, S4, S5.

### FR-06: AI Cost and Usage Attribution

Supported dimensions:

- Provider.
- Model.
- Application.
- Department.
- Team.
- Project.
- Agent.
- Customer, where customer metadata is available.
- Environment.
- Request or workflow.

Support ingestion from provider billing APIs, gateway telemetry and optional SDK traces.

Records from multiple data sources must be deduplicated or reconciled, not added together indiscriminately.

Separate estimated request cost from invoiced cost.

**AI-to-cloud join key specification (P0, versioned):**

Mandatory keys at launch:

- `team` (string, normalized)
- `project` (string, normalized)

Optional enrichment keys:

- `customer`
- `application`
- `agent`
- `environment`

**Matching algorithm:**

1. Exact match on all mandatory keys present in both the AI usage record and the cloud allocation fact.
2. Hierarchical fallback (for example, project-only when team is missing). Fallback joins are capped at a maximum confidence of 70.
3. Confidence score (0–100) attached to every join.
4. Unmatched records are classified as unmatched. They are never silently assigned.

**Launch confidence thresholds:**

| Confidence | Treatment |
|---|---|
| 90–100 | Auto-accepted into allocation |
| 70–89 | Accepted, flagged for review in the monthly close. A fallback join scores exactly 70 and therefore falls in this band. |
| Below 70 | Classified as unmatched |

Name collisions (the same project name in cloud tags and AI metadata) are resolved by the published precedence rule and shown on each allocated amount.

**Acceptance criteria:**

- The join rule is testable with customer sample logs before pilot approval.
- A conformance test suite covers exact match, hierarchical fallback, missing keys, name collisions and threshold boundaries.
- Users can inspect the join keys and confidence score for any allocated AI amount.

**Build notes:**

- The gateway writes `usage_events` with principal-derived `project`, `team` (from the project record, not the request), `agent`, and `environment` from the credential's configuration. Customer and application keys come from an optional, validated request metadata field `kb_metadata` (allowlisted keys only), stored as untrusted attribution with `source = GATEWAY`.
- `join_key_spec` is a versioned table or YAML file in the repo. The join function is pure and takes the spec version as input. Records store the spec version used.
- Confidence scoring: exact on mandatory keys = 100 minus 5 per missing optional key, floored at 90; fallback = 70 maximum.
- Test: `test_join_threshold_boundaries` at 69, 70, 89, 90; `test_name_collision_uses_precedence_rule`; `test_untrusted_metadata_never_changes_principal_budget`.

### FR-07: Financial Reconciliation

Reconcile:

- Gateway and application-level usage estimates.
- Provider usage records.
- Cloud billing exports.
- Provider invoices and adjustments.

Display:

- Estimated spending.
- Billed spending.
- Reconciliation difference.
- Unmatched spending.
- Adjustment records.
- Finalization state.

Handle multi-currency data, discounts, credits, taxes and late revisions.

**Acceptance criteria:**

- The platform never presents estimates as finalized invoices.
- Users can drill into unexplained reconciliation differences.
- Reconciliation jobs can be rerun without duplicating records.

**Build notes:**

- Each figure carries `finalization_state ∈ {ESTIMATED, PROVIDER_REPORTED, INVOICED}`. The UI renders the state next to every total. The API returns it in every response.
- **Invoice source (B-09, ⚠ D-05):** provider invoices may not be available through an API. Build three paths: (a) provider usage API as `PROVIDER_REPORTED`; (b) invoice upload (CSV or PDF parsed into a manual-review queue) as `INVOICED`; (c) customer ERP connector (P1). Only (a) is required for P0 acceptance; the 99.5% invoice-reconciliation target is measured against (b).
- Reconciliation job runs daily per provider and per billing period. It writes `reconciliation_runs (id, period, provider, estimated_micros, billed_micros, difference_micros, unmatched_count, run_at, pass)`. Reruns are idempotent by `(period, provider, run_key)`.
- Test: `test_reconcile_rerun_is_idempotent`; `test_estimate_never_labelled_invoiced`.

### FR-08: Anomaly Detection and Forecasting

**P0 (launch):**

- Budget burn-rate monitoring.
- Basic cost-spike alerts with the following baseline rules (B-14):
  - **Baseline:** the mean and standard deviation of the same weekday over the prior four weeks. Alert when the day's spend exceeds 3σ above that baseline.
  - **Minimum history:** 14 days of data per provider, project and model before the statistical baseline is used. Also require at least four non-zero days of the same weekday. Otherwise, the cold-start rule applies.
  - **Cold start:** before the minimum history is reached, the owner sets an absolute threshold. The default is 150% of the budget's pro-rated daily allowance.
  - **Irregular usage:** if the standard deviation is zero, use a floor of 10% of the mean as σ. This prevents every small change from alerting.
  - **Event suppression:** owners can mark known events (launches, migrations) to suppress alerts for a defined window. Suppressions are logged.
- Alert routing to the accountable human owner (FR-17).

**P1:**

- Advanced anomaly detection and machine-learning forecasting.
- Explanation of detected drivers.
- Severity and estimated financial impact.
- User feedback on false positives.

Start with statistical baselines and rule-based detection; evaluate ML methods when sufficient historical data is available.

**Build notes:**

- Computed by a scheduled job every 15 minutes over `usage_events` and `normalized_cost_records`, not on the request path.
- Writes `anomaly_alerts (id, scope, metric, observed, baseline, sigma, rule, created_at, suppressed_by)` and emits `anomaly.detected` to the outbox.
- Test: deterministic fixtures for flat, weekly-seasonal and spike series; `test_cold_start_uses_owner_threshold`; `test_zero_variance_uses_floor`; `test_suppression_is_logged_and_applied`.

### FR-09: Cloud Optimization

**P0 (launch, recommend only):**

Provider support matrix:

| Capability | AWS | Azure | GCP |
|---|---|---|---|
| Rightsizing / idle resource recommendations | Full | Full | Limited (core compute) |
| Commitment coverage and utilization | Full | Full | Full |
| Unused-commitment alerts | Full | Full | Full |

- Estimated savings and confidence.
- Recommendation status and ownership.

**Out of scope for v1:** automatic execution of infrastructure changes and automated commitment purchasing.

Initial releases should recommend rather than automatically execute infrastructure changes.

**Build notes:**

- Recommendations are ingested from each provider's native recommendation service, read-only: AWS Compute Optimizer and Cost Explorer commitment data; Azure Advisor and Cost Management reservation data; GCP Recommender and CUD data. Each adapter writes `recommendations (id, provider, type, resource_ref, est_savings_micros, confidence, status, owner_user_id, source_record_key, ingested_at)`.
- Status values: `OPEN`, `ACCEPTED`, `DISMISSED`, `DONE`. Status changes are audited.
- Ingestion is idempotent by `(provider, source_record_key)`.
- GCP rightsizing is shown with a "limited" label in the UI because the matrix says so.
- Test: fixtures per provider; `test_recommendation_reingest_is_idempotent`.

### FR-10: AI Optimization and Model Routing

Enable users to compare supported models using:

- Estimated price per request.
- Token utilization.
- Latency.
- Supported context and feature requirements.
- Customer-provided quality benchmarks.
- Policy restrictions.
- Reliability observations.

Routing options:

- Lowest estimated cost among approved models.
- Performance-first within budget.
- Fixed approved model.
- Customer-defined decision rules.
- Fallback to another approved model.

**Acceptance criteria:**

- Model substitutions are permitted only when compatibility and policy criteria are met.
- Customers can disable automatic substitutions.
- Routing decisions are auditable.
- Claims about quality or savings require measured workload-specific evidence.

**Build notes:**

- Routing runs inside step 3 of the request path (after canonicalization, before the block check). A substitution is a new canonical model that must pass the same block and budget checks. A substituted request is evaluated as a new request; the original is not reserved.
- Routing decisions are written to `usage_events` with `routed_from` and `route_rule_version`.
- P1 feature. Its only P0 dependency is the registry (FR-18).
- Test: `test_substitution_must_pass_block_check`; `test_disabled_substitution_never_routes`.

### FR-11: Approval Center

Support:

- Approval of budget increases.
- Temporary spending exceptions.
- Model-access requests.
- Departmental allocation changes.
- Policy override requests.
- High-impact optimization actions.

Every approval records identity, reason, affected scope, expiry and decision history.

Support configurable approval chains, delegation and separation of duties.

**Build notes:**

- **P0 subset (required now):** HELD queue for FR-05 approval-policy requests, plus approval of budget increases and policy overrides. Full chains, delegation and the request types above are P1.
- `approvals (id, kind, subject_ref, requested_by, requested_at, reason, scope, expires_at, decision, decided_by, decided_at)`. Separation of duties: requester cannot approve their own request (enforced in the service layer and tested).
- On approval of a HELD reservation, the gateway dispatches the stored request if the body was retained (D-07), or returns `410 Gone` with a new request required if not.
- Test: `test_self_approval_denied`; `test_approval_expiry_releases_hold`.

### FR-12: Reporting, Showback and Chargeback

Provide:

- Executive financial dashboard.
- Department and team dashboards.
- Monthly financial reports.
- Budget variance reports.
- Allocation coverage reports.
- AI cost by model, agent and application.
- Fail-open activity report.
- Savings opportunity summaries.
- CSV export and a documented reporting API.

Financial periods must support configurable closing, locking and authorized adjustments.

**Build notes:**

- Dashboards read from materialized views refreshed by the outbox/aggregation job. They never query raw `usage_events` on the request path. Refresh interval is stated on every dashboard (FR-12, freshness).
- **Audit log (B-l):** `audit_log` is append-only. Each row's `row_hash = SHA-256(prev_hash || canonical(row))`. A verification job walks the chain daily and emits `AUDIT_CHAIN_BROKEN` on failure. Revocation of database write grants for the application role on `audit_log` is required (UPDATE and DELETE denied).
- **Fail-open report:** lists every `FAIL_OPEN` event with budget, duration, requests counted and whether they were reconciled.
- Period lock: once locked, adjustments require an `approvals` record and produce a new revision (never an update).
- Test: `test_audit_hash_chain_detects_tampering`; `test_locked_period_rejects_direct_update`; `test_fail_open_report_matches_fail_events`.

### FR-13: Identity and Access Management

Minimum capabilities:

- Organization and tenant isolation.
- Role-based access control.
- Restricted access by organizational scope and by group, applied consistently across every view.
- Separate finance, engineering, administrator and auditor permissions.
- Service identities and scoped API credentials.
- MFA through supported authentication mechanisms.
- Complete authorization checks across UI, API, exports and scheduled reports.

Phase 2:

- SAML/OIDC SSO.
- SCIM provisioning.
- Automated group-to-department mapping.
- Access reviews.

**Build notes:**

- Roles: `FINANCE`, `ENGINEERING`, `ADMIN`, `AUDITOR`, `OWNER` (per budget). Permissions are a matrix in code (`permissions.py`), tested exhaustively.
- Tenant isolation: every table with tenant-owned data carries `tenant_id`. Postgres row-level security policies enforce `tenant_id = current_setting('app.tenant_id')`. The application sets the setting per request. Test: `test_cross_tenant_read_denied` on every list and export endpoint.
- Gateway routes use gateway credentials only. Admin routes use user sessions with MFA. The two authentication paths share no code path that could accept the wrong credential type (tested).
- MFA: TOTP in P0 (standard, offline-verifiable in tests with a fixed secret). SSO in P1.

### FR-14: Integration and API Framework

Provide a connector framework with:

- Credential validation.
- Least-privilege scopes.
- Connector health and synchronization history.
- Rate-limit handling and exponential backoff.
- Secret rotation and credential revocation.
- Standardized error reporting.
- Versioned APIs and webhooks.
- Integration event logs.

**Build notes:**

- Connector interface: `validate_credentials()`, `fetch_window()`, `normalize()`, `health()`, `dispatch()` (AI providers only). Each connector declares its required scopes in a manifest; validation fails if extra scopes are granted.
- Backoff: exponential with full jitter, base 1 s, cap 60 s, max 8 attempts, then `CONNECTOR_FAILED` event (visible; never silent).
- **Provider key custody (B-01):** provider keys are stored only in the vault. The connector API accepts a key reference, not a key value, for KeepAir-custodied keys. Customer-held keys are accepted only in monitor-only mode and are flagged in the project record.
- API versioning: path-based (`/v1/`). Webhooks are signed with HMAC-SHA256 over the raw body with timestamp; receivers reject timestamps older than 5 minutes.
- Test: `test_connector_scope_validation_rejects_extra_scopes`; `test_backoff_gives_up_with_visible_event`; `test_webhook_signature_and_replay_window`.

### FR-15: FinOps AI Assistant (P2)

Support questions such as:

- Why did cloud spending increase this month?
- Which departments exceed their AI budgets?
- Which models are driving our costs?
- What changed in the last seven days?
- Which optimization opportunities are most promising?

Responses must reference underlying cost records and explain filters, time periods and data freshness.

The assistant must respect the user's permissions and must not make financial changes without an explicit authorized action.

**Build notes:**

- The assistant does not generate SQL from free text against production tables. It calls a fixed set of typed query functions, each scoped by the caller's permissions, and returns record IDs for every number it states.
- No write tools are exposed to the assistant in P2 initial release. Any proposed change becomes an `approvals` request.
- Test: `test_assistant_cannot_read_outside_permissions`; `test_every_figure_has_record_reference`.

### FR-16: Agent Unit Economics (P1/P2)

Support measurement of:

- Cost per AI agent.
- Cost per workflow execution.
- Cost per successful task.
- Cost per customer served.
- Cost per business transaction.
- Estimated savings compared with an approved baseline.

Business value and revenue inputs must be customer-supplied or clearly sourced; do not fabricate ROI from token usage alone.

**Build notes:**

- Cost per agent is available in P0 because agent identity is in the credential (B-17). Cost per workflow and per successful task require the SDK to send a `workflow_id` and an outcome signal. Both are P1.
- Outcome inputs are customer-supplied via API and stored with `source = CUSTOMER`.

### FR-17: AI Cost Ownership (P0)

- Every AI budget and gateway-controlled project must have exactly one **accountable human owner**.
- **P0 owners are KeepAir local user accounts (B-10).** Linking to an external identity source is P1 (FR-13).
- An AI agent or service identity may be the **scope** of a budget. It cannot be the owner. Each agent or service inherits an owner from its parent project or budget.
- Owners receive threshold alerts and can view their budgets, usage and pending exceptions.
- Unowned AI spend is shown as a distinct bucket on the executive dashboard and in the monthly close.
- Ownership changes are logged with actor, timestamp and reason.
- Ownership assignment is required before a hard limit can be activated.
- Ownership changes to a budget with an active hard limit require a second administrator's confirmation (before the Approval Center is available) or an Approval Center workflow (once available). Both paths produce an immutable audit record.

**Build notes:**

- Activation check: `policy = HARD` requires `owner_user_id IS NOT NULL` and the owner's user row has `status = ACTIVE`. Enforced in the service layer and as a database `CHECK` via a trigger. Test: `test_hard_limit_without_owner_cannot_activate`.
- Owner alerts route through the outbox to the existing alerting stack (A-2), with the owner's email or the in-app notification as destination (P0 in-app only if email is not in the stack).
- Test: `test_owner_change_on_hard_limit_requires_second_admin`; `test_agent_cannot_be_owner` (validation rejects non-user owner IDs).

---

## 6. Nonfunctional Requirements

### Security

- Encryption in transit (TLS 1.2 or higher) and at rest (KMS-backed).
- Centralized secrets management (vault, Section 2.2).
- Tenant-aware authorization and data isolation (FR-13).
- Security audit events (FR-12).
- Webhook signing and API rate limiting (FR-14). Rate limits on the gateway are per credential and configurable; excessive rate denies with 429 and emits `RATE_LIMITED`.
- Defined retention, deletion and export policies.
- Secure handling of prompt and response metadata.
- No collection of prompt contents by default unless explicitly enabled. Gateway logs record metadata only. Test: `test_logs_contain_no_prompt_or_key_material` runs the full request path with canary strings and scans all sinks.

### Reliability

- Target production availability of 99.9%.
- Resumable ingestion.
- Dead-letter handling for persistent integration failures.
- Backup and recovery procedures with defined RPO/RTO:
  - Gateway budget reservation store: RPO ≤ 5 minutes, RTO ≤ 1 hour. Reservations must be recoverable from the request log.
  - Control plane (other data): RPO ≤ 1 hour, RTO ≤ 4 hours.
  - Financial reporting snapshots: RPO ≤ 24 hours, RTO ≤ 8 hours.
- Graceful degradation when providers or integrations are unavailable.
- Gateway behavior under control-plane outage or excessive latency follows the fail rules in FR-05 and FR-18. Budget checks follow the per-budget fail mode (default fail-open for soft and monitor-only, fail-closed for hard limits). Blocks always fail closed.

**Build notes:**

- Backups: PostgreSQL point-in-time recovery (WAL archiving) meets the 5-minute RPO for reservations. Restore drill runs quarterly and is scripted.
- Reservation recovery procedure: after restore, reconcile `reservations` in `RESERVED` and `HELD` states with the request log. Any reservation without a matching request is `RELEASED`; any with a matching dispatch record is `UNKNOWN`. Procedure is in `runbooks/reservation-recovery.md` and is tested in the restore drill.

### Performance

- Explicit dashboard responsiveness targets for supported data volumes.
- Documented request-path latency budget for gateway controls (Section 2.4).
- Ability to process historical billing imports asynchronously.
- Isolation of heavy analytical workloads from real-time enforcement (FR-12: dashboards read materialized views).

### Data Freshness

**Proposed targets (P0), pending PoC measurement (V-1 and Section 13):**

- AI gateway events: under 1 minute end-to-end.
- Cloud billing exports: provider's normal latency plus 4 hours.
- Recommendation data: within 24 hours of provider publication.
- AI provider usage (if V-1 confirms availability): provider's normal latency plus 4 hours.

Per-source freshness status is always visible. Each source's status is computed from `last_successful_sync` and the target, and shows `STALE` when exceeded. A stale source raises `DATA_STALE` (alert).

### Compliance

- Design for SOC 2 readiness.
- GDPR and applicable privacy requirements assessed by target market.
- Configurable data retention and regional requirements.
- Complete auditability of administrative and financial changes.

Do not claim certifications before independent assessment or completion.

### Multi-currency

- All amounts stored with original currency and amount.
- Conversion to reporting currency uses a versioned FX rate source with effective date.
- FX rate source, rate, and conversion timestamp are retained for audit.

**Build notes:** FX rates are a versioned table `fx_rates (base, quote, rate_micros, effective_date, source, version)`. Conversion uses the rate effective on the usage date. Rate rounding follows the `Money` value type. Test: `test_conversion_uses_effective_date_rate`.

---

## 7. Commercial and Packaging Requirements

Proposed packaging:

**Free / Starter**
- Limited connected spend or usage.
- Basic AI and cloud dashboards.
- Basic budgets and notifications.
- Self-service setup.

**Business**
- Hierarchical allocation and budgets.
- Extended history and reporting.
- AI gateway controls.
- Team-level governance.
- Additional integrations.

**Enterprise**
- Advanced IAM and approvals.
- Multi-entity reporting.
- Extended audit and compliance features.
- Custom retention and support agreements.
- API and integration capabilities.

**Public pricing requirement (P0):**

- The Free / Starter and Business price points, included limits and billing metric must be publicly listed before general availability.
- Enterprise may use a published starting price or a published pricing basis, with a sales path for the final quote.
- Quote-only pricing is not permitted for Free / Starter or Business.

**Billing metric (decision required before GA):**

Candidates under consideration:
- Percentage of tracked spend
- Managed AI spend
- Request volume
- Hybrid (with explicit double-counting prevention)

The chosen metric, free-tier thresholds, and unit-economics model must be validated and published. Pricing must transparently define the billing metric and prevent ambiguous double counting.

Final price points, free-tier thresholds and usage-based pricing require willingness-to-pay research and unit-economic validation.

**Build notes:** the billing metric is computed from data already in the system. Whichever metric is chosen, the calculation is a versioned, pure function with fixtures, and the same function is used for invoices and for the public calculator. ⚠ **D-10** (below) selects the metric.

---

## 8. Core User Workflows

### Workflow A — Onboarding

1. Create an organization.
2. Connect identity and directory source, if available (P1; P0 uses local accounts).
3. Connect AWS, Azure, GCP or AI providers. For AI providers, choose: KeepAir-custodied key (enforceable) or customer-held key (monitor only).
4. Validate credential permissions.
5. Begin import and display status.
6. Configure organizational hierarchy.
7. Apply allocation rules and validate the AI-to-cloud join rule against sample logs.
8. Review unallocated and unmatched spend.
9. Create local owner accounts and assign accountable human owners to AI budgets and projects.
10. Set cold-start thresholds for spike alerts.
11. Create budgets and alerts.
12. Optionally activate gateway enforcement (proxy or SDK). Hard limits require step 3's custodied-key option.

### Workflow B — Budget Overrun Prevention

1. Agent initiates an AI request with its gateway credential.
2. Gateway derives principal, owning team and project, named owner and applicable budgets from the credential.
3. Model is canonicalized; vendor and model blocks are checked.
4. Estimated cost is reserved.
5. Policy allows, rejects or holds the request.
6. Provider returns usage information.
7. Reservation is settled.
8. Actual spending and dashboards update.
9. Alerts or approval requests are raised when necessary.

If the gateway or control plane is unavailable, the fail rules in FR-05 apply, and the request is counted in the fail-open report where applicable.

### Workflow C — Monthly Finance Close

1. Import finalized billing data.
2. Detect delayed or adjusted records.
3. Reconcile provider costs with usage estimates.
4. Resolve unallocated, unowned and unmatched costs, including join-confidence items in the 70–89 band.
5. Review unresolved uncontrolled-spend findings (FR-19).
6. Approve allocation changes.
7. Lock the reporting period.
8. Generate executive and department reports.

---

## 9. Data Architecture Principles

Separate:

- Raw source records.
- Normalized financial records.
- Attribution and allocation facts.
- Real-time AI usage events.
- Budget reservations and enforcement decisions.
- Finalized financial reporting snapshots.

Use immutable identifiers, schema versioning, idempotency keys and lineage references.

Maintain a clear distinction between:

- Event time.
- Usage time.
- Invoice period.
- Ingestion time.
- Reporting close time.

An operational cost estimate is not equivalent to a finalized financial charge.

**Build notes:**

- Event time = `occurred_at` (provider or gateway timestamp). Ingestion time = `ingested_at`. Stored on every table that carries financial data.
- Outbox pattern: every state change writes its event in the same transaction. The outbox worker publishes at least once, and consumers deduplicate by event ID. This prevents lost alerts when the publisher is down.

---

## 10. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Provider billing delays | Expose per-source freshness and estimate status |
| Different FOCUS versions | Adapter-based normalization, support matrix, conformance testing |
| Double counting across APIs and gateway | Source precedence and reconciliation identifiers; `source` field on every usage record |
| Incomplete tags | Virtual allocation and unallocated buckets |
| Strict AI caps under concurrency | Atomic reservations with ordered row locks; hard limits fail closed |
| Customer-held keys bypass enforcement (B-a) | Hard limits require custodied keys (D-02); reconciliation detects the rest (FR-19); marketing must state the condition |
| Fail-open traffic bypassing evaluation | Per-budget override with dual confirmation; fail-open report |
| Blocks applied late | Snapshot staleness rule and propagation SLO (FR-18) |
| Bypassed AI calls outside the gateway | Display gateway-controlled vs. uncontrolled share; require customer routing; track pilot coverage metric |
| Customer security concerns | Least privilege, encryption and explicit content-data controls |
| Large multi-cloud scope | Phased rollout, provider support matrix, connector-specific acceptance tests; provider-native enforcement moved to P1 |
| Unverified savings claims | Measured baselines and confidence labels |
| High platform operating costs | Usage-based internal cost monitoring and ingestion optimization |
| Complex onboarding | Guided setup, diagnostics, sample-data preview, and join-key validation step |
| No accountable AI owner | Human owner required before hard limits (FR-17); unowned-spend bucket |
| False spike alerts | Same-weekday baseline, minimum history, cold-start thresholds, zero-variance floor, event suppression |
| Pricing ambiguity or perceived opacity | Public price list, billing metric, and unit-economics model before GA |
| Unvalidated targets used as commitments | Hypothesis labels and pilot validation (Section 13) |
| Provider usage API lacks per-key granularity (V-1) | Reconciliation falls back to project-aggregate; monitor-only scope narrowed in marketing |
| Single database as enforcement dependency | Reservation recovery procedure; fail-closed for hard limits; restore drill |

---

## 11. Release Gates

### P0 Release

May be considered ready after:

- Verifications V-1 to V-4 are recorded.
- Supported AWS, Azure and GCP import tests pass.
- Initial OpenAI and Anthropic integration tests pass (contract tests against recorded fixtures).
- Financial totals reconcile within defined thresholds.
- Allocation rules are traceable and deterministic.
- AI-to-cloud join key specification and conformance tests pass on customer sample logs, including threshold boundaries.
- Commitment and rightsizing recommendations display according to the FR-09 support matrix.
- Spike alerts (same-weekday baseline, cold-start handling) route to accountable owners.
- Role-based authorization and tenant isolation pass cross-tenant testing.
- **Enforcement proof:** every named test in Section 2.7 passes, including all bypass tests in FR-05 (B-a to B-m) and all FR-18 tests.
- Concurrency test shows no overshoot beyond the measured per-request tolerance, with the tolerance recorded.
- Fail-open and fail-closed behavior is tested under injected faults, and every fail event is visible in metrics, alerts and audit.
- Gateway latency is measured against Section 2.4 in the pilot environment. p95 ≤ 25 ms added before dispatch, excluding provider latency.
- Restore drill for reservations completes within RPO and RTO.
- Log scan test confirms no prompt or key material in any sink.
- Public price list and billing metric are published.
- Critical security findings are resolved.
- Pilot users complete onboarding and first reporting workflows, including join-key validation and owner assignment.

### P1 Release

Add:

- Provider-native enforcement methods.
- Advanced identity management and SSO.
- Broader AI integrations.
- Approval Center.
- Kubernetes cost attribution.
- Advanced anomaly detection and forecasting.
- More sophisticated unit economics.

### P2 Release

Add:

- Explainable FinOps assistant.
- Business-outcome intelligence.
- Approved automated optimization.
- Broader SaaS financial governance.

---

## FR-18: Canonical Registry, Vendor and Model Blocks (P0) — new in v1.4

**Intent:** a block is a security control. It must be applied everywhere, quickly, and must not be bypassable by naming tricks.

**Requirements:**

- Every model is referenced by one canonical identifier. Every alias resolves to exactly one canonical model or is unknown.
- **Default deny:** an unknown alias or unregistered model is denied (`UNKNOWN_MODEL`). New models must be registered before use.
- **Vendor block overrides model allow.** A vendor with status `BLOCKED` denies every model of that vendor, regardless of the model's status.
- A model `BLOCKED` denies that model regardless of vendor status.
- Allowed requires both: the vendor is `ALLOWED` and the model is `ALLOWED`.
- **Propagation SLO:** a block change is effective in every gateway instance within 5 seconds of commit.
- **Staleness rule:** if a gateway instance's snapshot is older than 30 seconds and it cannot refresh, it denies all requests to any vendor that has a block in the snapshot. It also raises `SNAPSHOT_STALE`. Budget fail mode is not used here.
- **Lifting a block requires two administrators.** The second administrator must differ from the first and must confirm within 24 hours. Until confirmed, the block remains.
- Every change to the registry is audited with actor, before and after values, and reason.
- **Emergency block:** any administrator may add a block immediately. Adding a block does not require a second person. Only lifting does. This asymmetry is deliberate.

**Build notes:**

- Snapshot: in-process object `PolicySnapshot(version, vendors, models, aliases, built_at)`. Rebuilt on NOTIFY from PostgreSQL trigger `registry_changed`. Also rebuilt every 5 seconds as a safety net.
- Snapshot is immutable once built. The gateway reads the current reference atomically (swap, never mutate).
- Decision function: `decide_block(snapshot, canonical_model) → Allow | Deny(reason)`. Pure. Reasons: `VENDOR_BLOCKED`, `MODEL_BLOCKED`, `MODEL_NOT_ALLOWED`, `UNKNOWN_MODEL`, `SNAPSHOT_STALE`.
- Every decision records `snapshot_version` on the usage or denial event. This lets an auditor prove which policy applied to any request.
- Admin endpoints: `PUT /v1/admin/vendors/{id}/status`, `PUT /v1/admin/models/{id}/status`, `POST /v1/admin/block-lifts/{id}/confirm`. The two-person lift is a `block_lift_requests` row with `requested_by`, `confirmed_by`, `expires_at`.
- **Mandatory tests:**
  - `test_blocked_vendor_denies_even_when_model_allowed` (property test over all vendor × model status combinations, including every alias)
  - `test_unknown_alias_denies`
  - `test_alias_to_blocked_model_denies`
  - `test_block_propagates_within_5s_across_instances` (two gateway instances, fake clock)
  - `test_block_fails_closed_when_snapshot_stale`
  - `test_lift_block_requires_second_admin`
  - `test_self_confirmation_denied`
  - `test_blocked_vendor_not_bypassed_by_model_alias`
- ⚠ Confirm against V-2 whether the existing policy store already has these semantics. If it differs, FR-18 wins and the existing store is migrated.

---

## FR-19: Uncontrolled Spend Detection (P0) — new in v1.4

**Intent:** if enforcement cannot be guaranteed for some traffic, KeepAir must still show that traffic exists. Silent gaps are not acceptable.

**Requirements:**

- For each provider and each provider key or project that KeepAir can see, compare provider-reported usage with gateway-recorded usage for the same period.
- A difference above the threshold creates an `UNCONTROLLED_SPEND` event with the amount and affected key or project.
- Threshold (proposed, to be tuned in pilot): the greater of 2% of provider usage or a fixed micro-amount, whichever is larger.
- Results appear on the dashboard as the "gateway-controlled share" for each project.
- If V-1 shows usage cannot be attributed below the account level, detection is account-level only and the UI says so.

**Build notes:**

- Reconciliation worker runs hourly for near-real-time drift and daily for the period close.
- Writes `uncontrolled_findings (id, provider, scope_ref, period, provider_micros, gateway_micros, delta_micros, granularity, created_at, acknowledged_by)`.
- Test: `test_uncontrolled_spend_detected_from_provider_usage_delta`; `test_below_threshold_is_not_flagged`; `test_account_level_granularity_is_labelled`.

---

## 12. Outstanding Decisions

The following decisions need product sign-off. The architect's recommendation is given for each. Engineering proceeds with the recommendation only where marked "default."

| ID | Decision | Options | Recommendation | Build impact if undecided |
|---|---|---|---|---|
| **D-01** | Should the default fail mode for hard limits be fail-closed for all customers, or configurable only at Enterprise? | (a) fail-closed for all; (b) configurable at Enterprise only; (c) configurable at all tiers | (a) fail-closed for all. Enterprise may request a documented, audited fail-open override. | Default is (a). Build proceeds. |
| **D-02** | Can customer-held provider keys ever back a hard limit? | (a) never; (b) yes, with a disclosed reduced-guarantee label; (c) yes, only if the customer also routes through a provider-native control | (a) never. Customer keys are monitor-only. This keeps the enforcement claim provable. Revisit only if pilots show custody is a blocker. | Default is (a). Build proceeds. |
| **D-03** | How should unknown models be handled? | (a) deny; (b) allow in monitor mode only, deny for enforced budgets | (b). Unknown models are allowed for discovery in monitor-only scope, logged as `UNREGISTERED_MODEL`, and denied for any budget under soft, hard or approval policy. Registration is required before enforcement. | Default is (b). Build proceeds. |
| **D-04** | How conservative should the cost estimator be? | (a) strict upper bound (no overshoot, lower utilization); (b) tighter estimate (higher utilization, measured overshoot tolerance) | (a) for P0. Move to (b) only after pilot data measures overshoot. | Default is (a). Build proceeds. |
| **D-05** | Where do invoices come from for reconciliation, if provider invoices are not available through an API? | (a) upload only; (b) upload plus customer ERP connector (P1); (c) provider API if available after V-1 | (b) with (a) in P0. Revise the 99.5% target to apply only to uploaded or ERP-connected invoices. | Default is (a) with the target restated. Build proceeds once the target is restated. |
| **D-06** | Are P0 owners KeepAir local accounts, or must they be linked to an identity provider? | (a) local accounts in P0; (b) IdP required in P0 | (a). IdP linkage in P1. Local accounts need MFA (FR-13). | Default is (a). Build proceeds. |
| **D-07** | For HELD requests, is the request body stored? | (a) store encrypted body and dispatch on approval; (b) store metadata only, require re-submission on approval | (b) for P0. It stores less sensitive data and removes a prompt-retention question. Revisit with (a) in P1 if users find re-submission unacceptable. | Default is (b). Build proceeds. |
| **D-08** | When budget is exhausted mid-stream, should the stream be cut? | (a) no, complete the stream and deny the next request; (b) yes, terminate the stream | (a). Terminating a stream does not reliably reduce cost and harms the client. Stated as a known limitation. | Default is (a). Build proceeds. |
| **D-09** | Should lifting a block also require a waiting period? | (a) two administrators only; (b) two administrators plus a waiting period (for example, 1 hour) | (b). A waiting period makes a compromised admin pair harder to exploit quickly. Cost is delay for legitimate lifts. | Default is (a). Build proceeds with a configurable wait period set to zero until decided. |
| **D-10** | Which billing metric is used for pricing? | (a) percentage of tracked spend; (b) managed AI spend; (c) request volume; (d) hybrid | Architect has no recommendation without willingness-to-pay data. Product decides. Note: (a) and (b) both need the same double-counting rule (Section 7). | Build of the metric function waits. Other work proceeds. |

---

## 13. Validation Plan

Before final scope approval:

- Conduct five to eight structured practitioner and customer interviews, as suggested by the market study.
- Complete verifications V-1 to V-4 (Section 3). Record results.
- Validate cloud and AI-provider ingestion against primary documentation, including the FOCUS version for each provider.
- Run an AWS–GCP allocation and reporting parity test. Recommendation parity is measured against the FR-09 matrix.
- Measure actual data latency by provider to confirm or revise the freshness targets.
- Test AI usage-to-team/project/customer attribution on real workloads, including the join-key specification, confidence thresholds and conformance suite (FR-06).
- Run the enforcement proof: all named tests in Section 2.7, plus a pilot-scale concurrency test measuring the actual per-request overshoot. Record the measured tolerance.
- Measure gateway added latency in the pilot environment against Section 2.4.
- Validate concurrent budget enforcement under stress, including fail-open and fail-closed behavior.
- Benchmark reconciliation accuracy against invoices to confirm or revise the 99.5% target (D-05).
- Measure false-positive rate of spike alerts against historical data using the same-weekday baseline.
- Measure uncontrolled-spend detection threshold (FR-19) against pilot data.
- Test willingness to pay for real-time controls, cross-cloud attribution and the public price points.
- Confirm owner-assignment workflow with at least two pilot finance teams (FR-17).
- Measure gateway or equivalent control coverage after 30 days in pilots to confirm or revise the 60% target.

**Document status:** Proposed product specification with build notes, v1.4. Architecture review complete. Verifications V-1 to V-4 are blocking for P0 build start. Open decisions D-01 to D-10 are listed in Section 12. Targets labeled [H] are hypotheses. Release boundaries and features are recommendations requiring technical and commercial validation.
