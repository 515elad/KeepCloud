from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from keepair.money import BIGINT_MAX, MICRO_PER_UNIT, Money, micro_to_decimal
from keepair.web.formatting import format_money

pytestmark = pytest.mark.req("FR-02 (money as BIGINT micro-units)", "ISO 4217")


@given(st.integers(min_value=0, max_value=BIGINT_MAX))
def test_micro_to_decimal_is_exact(amount_micro):
    value = micro_to_decimal(amount_micro)
    assert isinstance(value, Decimal)
    assert value * MICRO_PER_UNIT == amount_micro


@pytest.mark.parametrize("bad", [1.5, 10.0, "10", True, None])
def test_float_and_other_types_are_refused(bad):
    with pytest.raises(TypeError):
        Money(bad, "USD")
    with pytest.raises(TypeError):
        micro_to_decimal(bad)


@pytest.mark.parametrize("currency", ["usd", "US", "USDX", "", "U$D"])
def test_currency_must_be_iso_4217_shape(currency):
    with pytest.raises(ValueError):
        Money(1, currency)


def test_amount_must_fit_bigint():
    Money(BIGINT_MAX, "EUR")
    with pytest.raises(ValueError):
        Money(BIGINT_MAX + 1, "EUR")


def test_display_format_is_two_decimals_with_code():
    assert format_money(2_050_000_000, "USD") == "2,050.00 USD"
    assert format_money(1, "EUR") == "0.00 EUR"
    assert format_money(1_234_567_890_123, "EUR") == "1,234,567.89 EUR"
