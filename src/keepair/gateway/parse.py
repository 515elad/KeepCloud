"""Strict request parsing (SEC-04).

- The body has a size limit, checked before parsing.
- Duplicate JSON keys are rejected anywhere in the document.
- The model is read from the body only; a model named in a header is refused.
- Streaming is not built in the MVP and is refused, so that it cannot be used
  to avoid settlement (bypass route B-h).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from keepair.gateway.errors import GatewayError

MAX_BODY_BYTES = 256 * 1024
MODEL_HEADERS = ("x-model", "model", "x-keepair-model", "openai-model")
# Fields forwarded to the provider. Anything else is dropped, not passed through.
FORWARDED = ("messages", "max_tokens", "temperature", "top_p", "stop", "seed")


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str = Field(min_length=1, max_length=32)
    content: Any = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = Field(min_length=1, max_length=200)
    messages: list[Message] = Field(min_length=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    stream: bool = False

    @property
    def output_limit(self) -> int | None:
        limits = [v for v in (self.max_tokens, self.max_completion_tokens) if v is not None]
        return min(limits) if limits else None


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise GatewayError("AMBIGUOUS_REQUEST")
    return dict(pairs)


def parse_chat_request(raw: bytes, headers: dict[str, str]) -> tuple[ChatRequest, dict[str, Any]]:
    """Return the validated request and the parsed document."""
    if len(raw) > MAX_BODY_BYTES:
        raise GatewayError("REQUEST_TOO_LARGE")
    if headers.get("content-encoding", "identity").lower() != "identity":
        raise GatewayError("INVALID_REQUEST")  # no decompression on this path
    if any(h in headers for h in MODEL_HEADERS):
        raise GatewayError("AMBIGUOUS_REQUEST")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
        if not isinstance(document, dict):
            raise GatewayError("INVALID_REQUEST")
        request = ChatRequest.model_validate(document)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, RecursionError):
        raise GatewayError("INVALID_REQUEST") from None
    if request.stream:
        raise GatewayError("STREAMING_NOT_SUPPORTED")
    return request, document


def canonical_hash(document: dict[str, Any]) -> bytes:
    """SHA-256 of the canonical body, for idempotency."""
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).digest()


def provider_body(document: dict[str, Any], model_id: str, output_limit: int) -> dict[str, Any]:
    body = {k: document[k] for k in FORWARDED if k in document}
    body["model"] = model_id
    body["max_tokens"] = output_limit
    return body
