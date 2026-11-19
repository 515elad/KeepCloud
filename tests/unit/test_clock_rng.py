from datetime import UTC, datetime, timedelta, timezone

import pytest

from keepair.clock import FixedClock, SystemClock, from_iso, to_iso
from keepair.rng import seeded_rng

pytestmark = pytest.mark.req("v1.4 Section 2.3 (injected clock and seed)", "ISO 8601")


def test_fixed_clock_only_moves_when_advanced():
    clock = FixedClock(datetime(2026, 1, 15, 9, 0, tzinfo=UTC))
    assert clock.now() == clock.now()
    clock.advance(timedelta(seconds=30))
    assert to_iso(clock.now()) == "2026-01-15T09:00:30Z"


def test_fixed_clock_rejects_naive_datetime():
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 1, 15, 9, 0))  # noqa: DTZ001


def test_system_clock_is_timezone_aware_utc():
    assert SystemClock().now().utcoffset() == timedelta(0)


def test_iso_round_trip_normalizes_to_utc():
    plus_two = datetime(2026, 1, 15, 11, 0, tzinfo=timezone(timedelta(hours=2)))
    assert to_iso(plus_two) == "2026-01-15T09:00:00Z"
    assert from_iso("2026-01-15T09:00:00Z") == datetime(2026, 1, 15, 9, 0, tzinfo=UTC)


def test_iso_rejects_values_without_timezone():
    with pytest.raises(ValueError):
        from_iso("2026-01-15T09:00:00")
    with pytest.raises(ValueError):
        to_iso(datetime(2026, 1, 15, 9, 0))  # noqa: DTZ001


def test_same_seed_gives_same_sequence():
    a, b = seeded_rng(7), seeded_rng(7)
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]
