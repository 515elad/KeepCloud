"""Pure parts of the gateway: tokens, strict parsing, estimator, conversion, error contract."""

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from keepair.gateway import errors, tokens
from keepair.gateway import estimate as est
from keepair.gateway.errors import GatewayError, error_body
from keepair.gateway.fx import Rate, convert
from keepair.gateway.parse import (
    MAX_BODY_BYTES,
    canonical_hash,
    parse_chat_request,
    provider_body,
)
from keepair.mockprovider.app import mock_usage
from keepair.registry import Pricing
from keepair.rng import seeded_rng, system_rng

PRICING = Pricing(3_000, 15_000, "USD", 4_096, 1)


def body(**changes) -> bytes:
    doc = {"model": "model-1", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 50}
    doc.update(changes)
    return json.dumps(doc).encode()


# --- tokens -----------------------------------------------------------------


@pytest.mark.req("SEC-12", "SEC-22", "Hard rule 8")
def test_token_has_256_bits_a_prefix_and_a_checksum():
    token = tokens.generate_token(system_rng())
    assert token.startswith("kair_") and tokens.TOKEN_RE.fullmatch(token)
    assert tokens.is_well_formed(token)
    assert 62**43 > 2**256
    assert len({tokens.generate_token(system_rng()) for _ in range(200)}) == 200
    assert tokens.generate_token(seeded_rng(5)) == tokens.generate_token(seeded_rng(5))


@pytest.mark.req("SEC-22")
@pytest.mark.parametrize("change", ["flip", "truncate", "prefix", "empty"])
def test_malformed_tokens_fail_the_checksum(change):
    token = tokens.generate_token(seeded_rng(1))
    bad = {
        "flip": token[:10] + ("A" if token[10] != "A" else "B") + token[11:],
        "truncate": token[:-1],
        "prefix": "sk_" + token[5:],
        "empty": "",
    }[change]
    assert not tokens.is_well_formed(bad)


@pytest.mark.req("Hard rule 8 (SHA-256 hash only)")
def test_hash_is_sha256_and_does_not_contain_the_token():
    token = tokens.generate_token(seeded_rng(1))
    digest = tokens.hash_token(token)
    assert len(digest) == 32 and token.encode() not in digest


# --- strict parsing ---------------------------------------------------------


@pytest.mark.req("SEC-04", "B-n5")
@pytest.mark.parametrize(
    "raw",
    [
        b'{"model":"model-1","model":"vendor-b/model-1","messages":[{"role":"user","content":"x"}]}',
        b'{"model":"model-1","messages":[{"role":"user","role":"system","content":"x"}]}',
    ],
)
def test_duplicate_model_key_rejected(raw):
    with pytest.raises(GatewayError) as err:
        parse_chat_request(raw, {})
    assert err.value.code == "AMBIGUOUS_REQUEST" and err.value.status == 400


@pytest.mark.req("SEC-04")
@pytest.mark.parametrize("header", ["x-model", "model", "x-keepair-model", "openai-model"])
def test_model_in_a_header_is_ambiguous(header):
    with pytest.raises(GatewayError) as err:
        parse_chat_request(body(), {header: "vendor-a/model-2"})
    assert err.value.code == "AMBIGUOUS_REQUEST"


@pytest.mark.req("SEC-04")
@pytest.mark.parametrize(
    "raw",
    [b"", b"not json", b"[]", b'"model"', b"\xff\xfe", body(model=""), body(messages=[]),
     body(model=5), body(max_tokens=0), body(max_tokens="many"), b"[" * 100_000],
)  # fmt: skip
def test_invalid_bodies_are_refused(raw):
    with pytest.raises(GatewayError) as err:
        parse_chat_request(raw, {})
    assert err.value.code == "INVALID_REQUEST"


@pytest.mark.req("SEC-04 (size and decompression limits)")
def test_size_limit_and_compressed_bodies():
    with pytest.raises(GatewayError) as err:
        parse_chat_request(body(messages=[{"role": "user", "content": "x" * MAX_BODY_BYTES}]), {})
    assert err.value.code == "REQUEST_TOO_LARGE" and err.value.status == 413
    with pytest.raises(GatewayError) as err:
        parse_chat_request(body(), {"content-encoding": "gzip"})
    assert err.value.code == "INVALID_REQUEST"


@pytest.mark.req("B-h (streaming cannot avoid settlement)")
def test_streaming_is_refused():
    with pytest.raises(GatewayError) as err:
        parse_chat_request(body(stream=True), {})
    assert err.value.code == "STREAMING_NOT_SUPPORTED"


@given(st.text(max_size=300))
@pytest.mark.req("SEC-04 (fuzzing of the canonicalizer)")
def test_parser_never_fails_in_an_unplanned_way(text):
    for raw in (text.encode("utf-8", "surrogatepass"), body(model=text or "m")):
        try:
            request, _ = parse_chat_request(raw, {})
            assert request.model
        except GatewayError as err:
            assert err.code in {"INVALID_REQUEST", "AMBIGUOUS_REQUEST", "STREAMING_NOT_SUPPORTED"}


@pytest.mark.req("FR-05 (idempotency hash)", "SEC-01")
def test_canonical_hash_ignores_key_order_and_only_known_fields_are_forwarded():
    a = json.loads(b'{"model":"m","messages":[{"role":"user","content":"x"}],"max_tokens":5}')
    b = json.loads(b'{"max_tokens":5,"messages":[{"content":"x","role":"user"}],"model":"m"}')
    assert canonical_hash(a) == canonical_hash(b) != canonical_hash({**a, "max_tokens": 6})
    forwarded = provider_body(
        {**a, "base_url": "http://evil", "stream": False, "tools": []}, "v/m", 5
    )
    assert set(forwarded) == {"model", "messages", "max_tokens"} and forwarded["model"] == "v/m"


# --- estimator --------------------------------------------------------------


@pytest.mark.req("FR-05 (estimate)", "D-04")
def test_estimate_matches_the_formula():
    messages = [{"role": "user", "content": "hello"}]
    e = est.estimate(messages, 256, PRICING)
    raw_bytes = est.prompt_bytes(messages)
    assert e.input_tokens_upper == -(-raw_bytes // 2) and e.output_tokens_upper == 256
    assert e.cost_micros == -(-e.input_tokens_upper * 3_000 // 1000) + 256 * 15
    assert est.estimate(messages, None, PRICING).output_tokens_upper == 4_096
    assert (
        est.estimate(messages, 10**9, PRICING).output_tokens_upper == 4_096
    )  # capped by the model


@given(content=st.text(max_size=2_000), max_tokens=st.one_of(st.none(), st.integers(1, 10_000)))
@pytest.mark.req("FR-05 (estimator is an upper bound)", "D-04")
def test_estimate_is_never_below_what_the_mock_provider_charges(content, max_tokens):
    messages = [{"role": "user", "content": content}]
    e = est.estimate(messages, max_tokens, PRICING)
    sent_limit = e.output_tokens_upper  # what the gateway forwards as max_tokens
    prompt_tokens, completion_tokens = mock_usage(messages, sent_limit)
    assert prompt_tokens <= e.input_tokens_upper and completion_tokens <= e.output_tokens_upper
    assert est.actual_cost(prompt_tokens, completion_tokens, PRICING) <= e.cost_micros


@pytest.mark.req("FR-02 (integer money)")
def test_token_cost_rounds_up_to_a_whole_micro_unit():
    assert (
        est.token_cost(1, 250) == 1 and est.token_cost(4, 250) == 1 and est.token_cost(5, 250) == 2
    )
    assert est.token_cost(0, 250) == 0


# --- currency conversion ----------------------------------------------------


@given(st.integers(0, 10**15), st.integers(1, 10**8))
@pytest.mark.req("v1.4 Section 6 (multi-currency)")
def test_conversion_rounds_up_and_is_monotonic(amount, rate_micros):
    rate = Rate("USD", "EUR", rate_micros, None)
    converted = convert(amount, rate)
    assert converted * 1_000_000 >= amount * rate_micros > (converted - 1) * 1_000_000
    assert convert(amount + 1, rate) >= converted
    assert convert(amount, Rate("USD", "USD", 1_000_000, None)) == amount


# --- error contract ---------------------------------------------------------


@pytest.mark.req("SEC-11")
def test_policy_denials_are_403_and_bodies_are_minimal():
    for code in errors.POLICY_CODES:
        assert errors.CODES[code] == (403, "keepair_policy_denied")
    assert {"VENDOR_BLOCKED", "MODEL_BLOCKED", "UNKNOWN_MODEL", "BUDGET_EXHAUSTED",
            "VENDOR_ROUTE_MISMATCH", "SNAPSHOT_STALE"} <= errors.POLICY_CODES  # fmt: skip
    assert error_body("VENDOR_BLOCKED", "abc") == {
        "error": {"type": "keepair_policy_denied", "code": "VENDOR_BLOCKED", "request_id": "abc"}
    }
    assert errors.CODES["AUTHENTICATION_FAILED"][0] == 401
    assert errors.CODES["PATH_NOT_ALLOWED"][0] == 404
    assert errors.CODES["AMBIGUOUS_REQUEST"][0] == 400
    assert errors.CODES["IDEMPOTENCY_KEY_REUSED"][0] == 422
    assert errors.CODES["RATE_LIMITED"][0] == 429
    with pytest.raises(ValueError):
        GatewayError("MADE_UP")
