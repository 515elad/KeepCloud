import itertools
from datetime import date

import pytest

from keepair.coverage import Coverage, coverage_state
from keepair.demo.seed import demo_clock
from keepair.ids import uuid7
from keepair.rng import seeded_rng, system_rng
from keepair.web.formatting import format_pct_bp, format_period, format_unit_price, period_end


@pytest.mark.req("UX-2", "UX-D1", "FR-20")
def test_enforced_is_claimed_only_with_custody_and_verified_egress():
    for custody, egress, finding in itertools.product(
        ["KEEPAIR", "CUSTOMER"], [True, False], [True, False]
    ):
        state = coverage_state(custody, egress, finding)
        assert (state is Coverage.ENFORCED) is (custody == "KEEPAIR" and egress and not finding)
        if finding:
            assert state is Coverage.UNCONTROLLED
        elif custody == "CUSTOMER":
            assert state is Coverage.MONITORED  # D-02: customer keys are monitor only
    assert coverage_state("KEEPAIR", False, False) is Coverage.GATEWAY_ROUTED


@pytest.mark.req("v1.4 Section 2.3 (UUIDv7, injected clock and seed)")
def test_uuid7_is_versioned_time_ordered_and_reproducible():
    clock = demo_clock()
    a, b = uuid7(clock, seeded_rng(1)), uuid7(clock, seeded_rng(1))
    assert a == b and a.version == 7 and a.variant == "specified in RFC 4122"
    assert a.int >> 80 == int(clock.now().timestamp() * 1000)
    assert uuid7(clock, system_rng()) != uuid7(clock, system_rng())


@pytest.mark.req("FR-02", "UX-14 (one format)")
def test_unit_price_and_percent_formats():
    assert format_unit_price(3_000, "USD") == "0.003 USD"
    assert format_unit_price(250, "USD") == "0.00025 USD"
    assert format_unit_price(10_000, "USD") == "0.01 USD"
    assert format_unit_price(2_000_000, "EUR") == "2.00 EUR"
    assert (
        format_pct_bp(8725) == "87.25%"
        and format_pct_bp(5) == "0.05%"
        and format_pct_bp(11800) == "118.00%"
    )


@pytest.mark.req("FR-04 (periods)", "ISO 8601")
def test_period_end_dates():
    assert period_end("MONTH", date(2026, 1, 1)) == date(2026, 1, 31)
    assert period_end("MONTH", date(2028, 2, 1)) == date(2028, 2, 29)
    assert period_end("QUARTER", date(2026, 11, 1)) == date(2027, 1, 31)
    assert period_end("YEAR", date(2026, 1, 1)) == date(2026, 12, 31)
    assert format_period("QUARTER", date(2026, 1, 1)) == "Quarter, 2026-01-01 to 2026-03-31"
