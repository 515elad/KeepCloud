"""Gateway outcomes that end a request early, and the denial contract (SEC-11).

Policy denials are HTTP 403 with a stable code and the request ID. The body
never carries budget amounts or internal identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# code: (HTTP status, error type)
CODES: dict[str, tuple[int, str]] = {
    # authentication and request shape
    "AUTHENTICATION_FAILED": (401, "keepair_authentication_error"),
    "PATH_NOT_ALLOWED": (404, "keepair_invalid_request"),
    "REQUEST_TOO_LARGE": (413, "keepair_invalid_request"),
    "INVALID_REQUEST": (400, "keepair_invalid_request"),
    "AMBIGUOUS_REQUEST": (400, "keepair_invalid_request"),
    "STREAMING_NOT_SUPPORTED": (400, "keepair_invalid_request"),
    "IDEMPOTENCY_KEY_REQUIRED": (400, "keepair_invalid_request"),
    "IDEMPOTENCY_IN_FLIGHT": (409, "keepair_idempotency_error"),
    "IDEMPOTENCY_KEY_REUSED": (422, "keepair_idempotency_error"),
    # policy (always 403)
    "VENDOR_BLOCKED": (403, "keepair_policy_denied"),
    "MODEL_BLOCKED": (403, "keepair_policy_denied"),
    "MODEL_NOT_ALLOWED": (403, "keepair_policy_denied"),
    "UNKNOWN_MODEL": (403, "keepair_policy_denied"),
    "VENDOR_ROUTE_MISMATCH": (403, "keepair_policy_denied"),
    "SNAPSHOT_STALE": (403, "keepair_policy_denied"),
    "BUDGET_EXHAUSTED": (403, "keepair_policy_denied"),
    "NO_BUDGET": (403, "keepair_policy_denied"),
    "FX_RATE_MISSING": (403, "keepair_policy_denied"),
    # held for approval
    "APPROVAL_REQUIRED": (202, "keepair_held"),
    # limits and availability
    "RATE_LIMITED": (429, "keepair_rate_limited"),
    "LEDGER_UNAVAILABLE": (503, "keepair_unavailable"),
    "UPSTREAM_TIMEOUT": (504, "keepair_upstream_error"),
    "UPSTREAM_ERROR": (502, "keepair_upstream_error"),
}
POLICY_CODES = frozenset(code for code, (status, _) in CODES.items() if status == 403)


@dataclass
class GatewayError(Exception):
    code: str
    budget_id: object | None = None  # recorded internally, never returned
    headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.code not in CODES:
            raise ValueError(f"unregistered gateway code: {self.code}")
        super().__init__(self.code)

    @property
    def status(self) -> int:
        return CODES[self.code][0]


def error_body(code: str, request_id: str) -> dict:
    return {"error": {"type": CODES[code][1], "code": code, "request_id": request_id}}
