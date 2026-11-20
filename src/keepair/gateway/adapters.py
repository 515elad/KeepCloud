"""Provider adapters (hard rule 6, SEC-01).

An adapter sends nothing unless it can claim a live reservation in the
database. Calling it directly, with no permit or with a made-up reservation
ID, is refused. There is no pass-through mode.

The only adapter in the MVP speaks the OpenAI-compatible chat shape to the
mock provider. No real provider is ever called.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from sqlalchemy import Engine

from keepair.gateway import ledger

DEFAULT_TIMEOUT_S = 120.0
# The path this adapter may call on a vendor host. Billable.
CHAT_PATH = "/v1/chat/completions"


class NoReservation(Exception):
    """Raised instead of dispatching when there is no live reservation."""


@dataclass(frozen=True, slots=True)
class DispatchPermit:
    reservation_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ProviderResult:
    status: int
    body: dict[str, Any] | None
    input_tokens: int | None
    output_tokens: int | None

    @property
    def usage_known(self) -> bool:
        return self.input_tokens is not None and self.output_tokens is not None


class Vault(Protocol):
    def provider_key(self, tenant_id: uuid.UUID, vendor_id: str) -> str: ...


class MockVault:
    """Stands in for the KMS-backed vault. Holds no secret: the mock provider needs none."""

    def provider_key(self, tenant_id: uuid.UUID, vendor_id: str) -> str:
        return "mock-provider-key-not-a-secret"  # pragma: allowlist secret


class ChatAdapter:
    def __init__(self, engine: Engine, http: httpx.Client, vault: Vault) -> None:
        self._engine = engine
        self._http = http
        self._vault = vault

    def dispatch(
        self,
        permit: DispatchPermit,
        *,
        tenant_id: uuid.UUID,
        vendor_id: str,
        base_url: str,
        body: dict[str, Any],
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> ProviderResult:
        if not isinstance(permit, DispatchPermit):
            raise NoReservation("dispatch needs a permit from the gateway")
        with self._engine.begin() as conn:
            if not ledger.claim_for_dispatch(conn, permit.reservation_id):
                raise NoReservation("no live reservation for this dispatch")
        # The key is read for this call only and is never logged or returned.
        key = self._vault.provider_key(tenant_id, vendor_id)
        response = self._http.post(
            base_url + CHAT_PATH,
            json=body,
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout_s,
        )
        payload = None
        if response.headers.get("content-type", "").startswith("application/json"):
            try:
                payload = response.json()
            except ValueError:
                payload = None
        usage = payload.get("usage") if isinstance(payload, dict) else None
        tokens = [
            usage.get(k) if isinstance(usage, dict) else None
            for k in ("prompt_tokens", "completion_tokens")
        ]
        valid = all(isinstance(t, int) and not isinstance(t, bool) and t >= 0 for t in tokens)
        return ProviderResult(
            status=response.status_code,
            body=payload if isinstance(payload, dict) else None,
            input_tokens=tokens[0] if valid else None,
            output_tokens=tokens[1] if valid else None,
        )
