"""The one cost estimator (FR-05 step 5, D-04: strict upper bound).

    input_tokens_upper  = ceil(prompt_bytes / 2)          (no tokenizer in the MVP)
    output_tokens_upper = min(requested max, model max)   (model max when none requested)
    cost = ceil(input_tokens_upper * input_price / 1000)
         + ceil(output_tokens_upper * output_price / 1000)

Prices are micro-units per 1,000 tokens. Integer arithmetic only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from keepair.registry import Pricing


@dataclass(frozen=True, slots=True)
class Estimate:
    input_tokens_upper: int
    output_tokens_upper: int
    cost_micros: int
    currency: str
    price_version: int


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def prompt_bytes(messages: Any) -> int:
    return len(json.dumps(messages, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def token_cost(tokens: int, price_micros_per_1k: int) -> int:
    return _ceil_div(tokens * price_micros_per_1k, 1000)


def estimate(messages: Any, requested_max: int | None, pricing: Pricing) -> Estimate:
    input_upper = _ceil_div(prompt_bytes(messages), 2)
    output_upper = min(requested_max or pricing.max_output_tokens, pricing.max_output_tokens)
    cost = token_cost(input_upper, pricing.input_price_micros_per_1k) + token_cost(
        output_upper, pricing.output_price_micros_per_1k
    )
    return Estimate(input_upper, output_upper, cost, pricing.currency, pricing.price_version)


def actual_cost(input_tokens: int, output_tokens: int, pricing: Pricing) -> int:
    return token_cost(input_tokens, pricing.input_price_micros_per_1k) + token_cost(
        output_tokens, pricing.output_price_micros_per_1k
    )
