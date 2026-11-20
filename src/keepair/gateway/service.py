"""The gateway request path (FR-05, PRD v1.5 Section 6).

Normative order. Each step is its own function with its own tests:

  1. authenticate            auth.authenticate
  2. path allowlist          app.py routing (unknown paths never reach here)
  3. strict parse            parse.parse_chat_request
  4. idempotency             idempotency.begin
  5. canonicalize, block     registry.decide_block on the policy snapshot
  6. destination check       vendor host from the registry only
  7. estimate                estimate.estimate (+ fx.convert)
  8. reserve                 ledger.reserve, decision recorded in the same transaction
  9. dispatch                adapters.ChatAdapter.dispatch (claims the reservation)
 10. settle                  ledger.settle
 11. respond

Blocks and budget limits fail closed here. Fail-open for monitor and soft
budgets arrives with the spool in phase 3.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import Connection, Engine, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from keepair.clock import Clock
from keepair.failures import FailureReporter
from keepair.gateway import idempotency, ledger
from keepair.gateway.adapters import ChatAdapter, DispatchPermit, NoReservation
from keepair.gateway.auth import Principal, authenticate
from keepair.gateway.errors import CODES, GatewayError, error_body
from keepair.gateway.estimate import actual_cost, estimate
from keepair.gateway.fx import convert, lookup_rate
from keepair.gateway.parse import canonical_hash, parse_chat_request, provider_body
from keepair.gateway.snapshot import SnapshotCache
from keepair.ids import uuid7
from keepair.metrics import Metrics
from keepair.registry import decide_block, normalize
from keepair.rng import Rng
from keepair.schema import budgets, gateway_decisions, unregistered_models, usage_events

REQUESTS_TOTAL = "keepair_gateway_requests_total"
MAX_MODEL_NAME = 200


@dataclass(slots=True)
class GatewayResponse:
    status: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


class Gateway:
    def __init__(
        self,
        *,
        engine: Engine,
        clock: Clock,
        rng: Rng,
        metrics: Metrics,
        reporter: FailureReporter,
        snapshots: SnapshotCache,
        adapter: ChatAdapter,
        limits: ledger.Limits = ledger.DEFAULT_LIMITS,
        timeout_s: float = 120.0,
    ) -> None:
        self.engine = engine
        self.clock = clock
        self.rng = rng
        self.metrics = metrics
        self.reporter = reporter
        self.snapshots = snapshots
        self.adapter = adapter
        self.limits = limits
        self.timeout_s = timeout_s
        metrics.describe(REQUESTS_TOTAL, "Gateway requests by outcome and reason code.")

    # ------------------------------------------------------------------ entry

    def handle_chat(
        self,
        *,
        authorization: str | None,
        headers: dict[str, str],
        raw_body: bytes,
        route_vendor: str | None = None,
    ) -> GatewayResponse:
        request_id = uuid7(self.clock, self.rng)
        rid = str(request_id)
        try:
            response = self._handle(request_id, authorization, headers, raw_body, route_vendor)
        except GatewayError as err:
            response = GatewayResponse(err.status, error_body(err.code, rid), dict(err.headers))
        except SQLAlchemyError:
            # The ledger cannot be reached: nothing is dispatched (fail closed).
            self.reporter.report(
                "DATABASE_UNREACHABLE",
                "The gateway could not reach the ledger. The request was refused.",
                dedupe_s=60,
            )
            response = GatewayResponse(503, error_body("LEDGER_UNAVAILABLE", rid))
        code = response.body.get("error", {}).get("code", "OK") if response.status != 200 else "OK"
        outcome = {200: "allowed", 202: "held"}.get(response.status, "refused")
        self.metrics.inc(REQUESTS_TOTAL, outcome=outcome, code=code)
        response.headers["X-KeepAir-Request-Id"] = rid
        return response

    def _handle(
        self, request_id, authorization, headers, raw_body, route_vendor
    ) -> GatewayResponse:
        # 1. Authenticate. 3. Strict parse. 4. Idempotency. One transaction: a refusal
        # in any of the three rolls back and leaves nothing behind.
        with self.engine.begin() as conn:
            principal = authenticate(conn, authorization)
            request, document = parse_chat_request(raw_body, headers)
            key = idempotency.validate_key(headers.get("idempotency-key"))
            prior = idempotency.begin(
                conn, principal.tenant_id, principal.agent_id, key, canonical_hash(document)
            )
        if prior is not None:
            prior.headers["X-KeepAir-Idempotent-Replay"] = "true"
            return GatewayResponse(prior.status, prior.body, prior.headers)

        try:
            response = self._decide_and_run(request_id, principal, request, document, route_vendor)
        except GatewayError as err:
            response = self._refuse(request_id, principal, request.model, err)
        except SQLAlchemyError:
            self._forget_key(principal, key)
            raise
        if response.status == 503:
            self._forget_key(principal, key)  # nothing happened: the client may retry
        else:
            with self.engine.begin() as conn:
                idempotency.finish(conn, principal.agent_id, key, response.status, response.body)
        return response

    def _forget_key(self, principal: Principal, key: str) -> None:
        try:
            with self.engine.begin() as conn:
                idempotency.forget(conn, principal.agent_id, key)
        except SQLAlchemyError:
            # The key stays "in flight" until the sweeper removes it; retries get 409 meanwhile.
            self.reporter.report(
                "DATABASE_UNREACHABLE",
                "An idempotency key could not be cleared after a refused request.",
                dedupe_s=60,
            )

    # ------------------------------------------------------------ steps 5-11

    def _decide_and_run(self, request_id, principal, request, document, route_vendor):
        rid = str(request_id)
        # 5. Canonicalize and block check, on the snapshot. Never fails open.
        try:
            loaded = self.snapshots.get(principal.tenant_id)
        except GatewayError:
            self.reporter.report(
                "SNAPSHOT_STALE",
                "The policy snapshot is older than 30 s and could not be refreshed. "
                "All requests are refused on this gateway instance.",
                dedupe_s=60,
            )
            raise
        decision = decide_block(loaded.policy, request.model)
        if not decision.allowed:
            raise GatewayError(decision.reason.value)
        if route_vendor is not None and normalize(route_vendor) != decision.vendor_id:
            raise GatewayError("VENDOR_ROUTE_MISMATCH")
        # 6. Destination: the vendor host comes from the registry, never from the request.
        base_url = loaded.endpoints.get(decision.vendor_id)
        pricing = loaded.policy.models[decision.model_id].pricing
        if base_url is None or pricing is None:
            raise GatewayError("MODEL_NOT_ALLOWED")
        if principal.budget_id is None:
            raise GatewayError("NO_BUDGET")
        # 7. Estimate (strict upper bound).
        est = estimate(document["messages"], request.output_limit, pricing)

        # 8. Reserve. The decision row is written in the same transaction.
        with self.engine.begin() as conn:
            budget_currency = conn.execute(
                select(budgets.c.currency).where(budgets.c.id == principal.budget_id)
            ).scalar_one()
            rate = lookup_rate(conn, est.currency, budget_currency, self.clock.now().date())
            if rate is None:
                raise GatewayError("FX_RATE_MISSING")
            reserved = ledger.reserve(
                conn,
                clock=self.clock,
                rng=self.rng,
                tenant_id=principal.tenant_id,
                request_id=request_id,
                budget_id=principal.budget_id,
                cost_micros=convert(est.cost_micros, rate),
                credential_id=principal.credential_id,
                agent_id=principal.agent_id,
                model_id=decision.model_id,
                price_version=est.price_version,
                fx_rate_micros=rate.rate_micros,
                limits=self.limits,
            )
            held = reserved.state == "HELD"
            self._record(
                conn, request_id, principal, request.model, decision.model_id,
                outcome="HELD" if held else "ALLOWED",
                reason="APPROVAL_REQUIRED" if held else None,
                status=202 if held else 200,
                budget_id=principal.budget_id if held else None,
                reservation_id=reserved.reservation_id,
                snapshot_version=decision.snapshot_version,
            )  # fmt: skip
        for budget_id in reserved.soft_limits_crossed:
            self.reporter.report(
                "SOFT_LIMIT_EXCEEDED",
                f"A soft-limit budget passed its cap (budget {budget_id}). Requests continue.",
            )
        gateway_headers = {
            "X-KeepAir-Reservation-Id": str(reserved.reservation_id),
            "X-KeepAir-Decision": reserved.state,
        }
        if held:
            # D-07: the request body is not stored. Approval allows a resubmission (phase 5).
            return GatewayResponse(202, error_body("APPROVAL_REQUIRED", rid), gateway_headers)

        # 9. Dispatch. The adapter refuses unless it can claim the reservation.
        body = provider_body(document, decision.model_id, est.output_tokens_upper)
        try:
            result = self.adapter.dispatch(
                DispatchPermit(reserved.reservation_id),
                tenant_id=principal.tenant_id,
                vendor_id=decision.vendor_id,
                base_url=base_url,
                body=body,
                timeout_s=self.timeout_s,
            )
        except NoReservation:
            with self.engine.begin() as conn:
                ledger.release(conn, reserved.reservation_id, clock=self.clock)
            raise GatewayError("LEDGER_UNAVAILABLE") from None
        except httpx.HTTPError:
            # Timeout or connection error after dispatch: the provider may have done the work.
            self._settle(reserved.reservation_id, principal, decision, None, None, known=False,
                         final_state="UNKNOWN")  # fmt: skip
            self.reporter.report(
                "UNKNOWN_USAGE",
                f"No answer from {decision.vendor_id} for request {rid}. It was settled at the "
                "reserved amount and its real usage is unknown.",
            )
            return GatewayResponse(504, error_body("UPSTREAM_TIMEOUT", rid), gateway_headers)

        # 10. Settle.
        if not 200 <= result.status < 300 or result.body is None:
            # The provider refused or failed the request: nothing was produced, so release.
            with self.engine.begin() as conn:
                ledger.release(conn, reserved.reservation_id, clock=self.clock)
            self.reporter.report(
                "PROVIDER_ERROR",
                f"{decision.vendor_id} answered request {rid} with HTTP {result.status}. "
                "The reservation was released.",
            )
            return GatewayResponse(502, error_body("UPSTREAM_ERROR", rid), gateway_headers)
        if result.usage_known:
            actual = convert(actual_cost(result.input_tokens, result.output_tokens, pricing), rate)
            settled = self._settle(reserved.reservation_id, principal, decision,
                                   result, actual, known=True)  # fmt: skip
            if settled is not None and settled.overrun_micros > 0:
                self.reporter.report(
                    "BUDGET_OVERRUN",
                    f"Request {rid} cost more than was reserved for it. The overrun is recorded "
                    "on the reservation.",
                )
        else:
            self._settle(reserved.reservation_id, principal, decision, result, None, known=False)
            self.reporter.report(
                "UNKNOWN_USAGE",
                f"{decision.vendor_id} answered request {rid} without usage figures. It was "
                "settled at the reserved amount.",
            )
        # 11. Respond with the provider payload plus informational gateway headers.
        return GatewayResponse(200, result.body, gateway_headers)

    def _settle(self, reservation_id, principal, decision, result, actual, *, known,
                final_state="SETTLED"):  # fmt: skip
        with self.engine.begin() as conn:
            settled = ledger.settle(
                conn, reservation_id, clock=self.clock, actual_micros=actual,
                usage_known=known, final_state=final_state,
            )  # fmt: skip
            if settled is None:
                return None
            now = self.clock.now()
            conn.execute(
                insert(usage_events).values(
                    id=uuid7(self.clock, self.rng),
                    tenant_id=principal.tenant_id,
                    reservation_id=reservation_id,
                    provider=decision.vendor_id,
                    model_id=decision.model_id,
                    agent_id=principal.agent_id,
                    team=principal.team,
                    project=principal.project,
                    agent=principal.agent,
                    input_tokens=result.input_tokens if result and known else None,
                    output_tokens=result.output_tokens if result and known else None,
                    actual_micros=settled.actual_micros,
                    currency=settled.currency,
                    usage_known=known,
                    source="GATEWAY",
                    occurred_at=now,
                    ingested_at=now,
                )
            )
            return settled

    # ---------------------------------------------------------------- records

    def _refuse(self, request_id, principal, requested_model, err: GatewayError):
        """Record a refusal. The request is refused whether or not the record can be written."""
        try:
            with self.engine.begin() as conn:
                self._record(
                    conn, request_id, principal, requested_model, None,
                    outcome="DENIED", reason=err.code, status=err.status, budget_id=err.budget_id,
                )  # fmt: skip
                if err.code == "UNKNOWN_MODEL":
                    self._note_unregistered(conn, principal.tenant_id, requested_model)
        except SQLAlchemyError:
            self.reporter.report(
                "DECISION_RECORD_FAILED",
                f"A refusal ({err.code}) could not be written to the decision record. "
                "The request was still refused.",
            )
        return GatewayResponse(err.status, error_body(err.code, str(request_id)), dict(err.headers))

    def _record(self, conn: Connection, request_id, principal, requested_model, model_id, *,
                outcome, reason, status, budget_id=None, reservation_id=None,
                snapshot_version=None) -> None:  # fmt: skip
        conn.execute(
            insert(gateway_decisions).values(
                id=request_id,
                tenant_id=principal.tenant_id,
                occurred_at=self.clock.now(),
                agent_id=principal.agent_id,
                agent=principal.agent,
                project=principal.project,
                requested_model=requested_model[:MAX_MODEL_NAME],
                model_id=model_id,
                outcome=outcome,
                reason_code=reason,
                http_status=status,
                budget_id=budget_id,
                reservation_id=reservation_id,
                snapshot_version=snapshot_version,
            )
        )

    def _note_unregistered(self, conn: Connection, tenant_id: uuid.UUID, requested: str) -> None:
        name = normalize(requested)[:MAX_MODEL_NAME]
        if not name:
            return
        now = self.clock.now()
        stmt = pg_insert(unregistered_models).values(
            tenant_id=tenant_id,
            requested_name=name,
            first_seen_at=now,
            last_seen_at=now,
            seen_count=1,
        )
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["tenant_id", "requested_name"],
                set_={
                    "last_seen_at": now,
                    "seen_count": unregistered_models.c.seen_count + 1,
                },
            )
        )


__all__ = ["CODES", "Gateway", "GatewayResponse"]
