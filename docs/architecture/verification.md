# Verification record (S0)

PRD v1.4 Section 3 and v1.5 Section 9 ask for these checks before P0 build. This repo started empty, so most answers are "nothing exists to verify; built new to the PRD". Recorded 2026-11-19.

| ID | Question | Result | Effect |
|---|---|---|---|
| V-1 | Provider usage API granularity | **Not verified.** It needs provider documentation and a sandbox key; the MVP may not call a real provider. | The MVP uses a mock provider and generated billing files only. FR-19 detection against real provider data is out of the MVP. |
| V-2 | Existing policy store semantics | No existing policy store. | FR-18 is built as written: ALLOWED / BLOCKED, vendor block overrides model allow, unknown is denied. |
| V-3 | Observability and alerting stack | None exists. | Phase 0 provides a `/metrics` endpoint (Prometheus text format), an `alerts` table and an alerts list in the UI. An outbox to an external stack is future work. |
| V-4 | Database engine | PostgreSQL 16 (docker compose; testcontainers in tests). | As assumed in A-4. |
| V-5 | Egress instrumentation | None exists. | FR-20 is not in the MVP phases. Coverage badge stays "Gateway-routed" (UX-D1 default). |
| V-6 | Existing policy fixtures and mocked-LLM setup | None exist. | Fixtures are created in `tests/fixtures/providers/` from phase 2. |
| V-7 | Absence (no-heartbeat) alert rules | No alerting stack. | Heartbeat absence is computed in the app (`keepair.health`) and shown in the health strip. |
| V-8 | Existing gateway denial contract | No existing gateway. | The gateway is built to the v1.5 denial contract (SEC-11) in phase 2. |
