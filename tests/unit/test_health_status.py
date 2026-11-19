from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from keepair.health import COMPONENTS, HealthStatus, health_status, unknown_health

pytestmark = pytest.mark.req("UX-6", "FR-21", "SEC-37")

NOW = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)
ORDER = [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.FAILING]


def test_no_heartbeat_is_unknown():
    assert health_status(None, NOW, 60, 180) is HealthStatus.UNKNOWN


def test_future_heartbeat_is_unknown():
    assert health_status(NOW + timedelta(seconds=1), NOW, 60, 180) is HealthStatus.UNKNOWN


@pytest.mark.parametrize(
    ("age_s", "expected"),
    [(0, "Healthy"), (60, "Healthy"), (61, "Degraded"), (180, "Degraded"), (181, "Failing")],
)
def test_thresholds(age_s, expected):
    assert health_status(NOW - timedelta(seconds=age_s), NOW, 60, 180).value == expected


@given(
    a=st.integers(min_value=0, max_value=10**6),
    b=st.integers(min_value=0, max_value=10**6),
    degraded=st.integers(min_value=1, max_value=10**5),
    extra=st.integers(min_value=0, max_value=10**5),
)
def test_status_never_improves_as_a_heartbeat_ages(a, b, degraded, extra):
    younger, older = sorted((a, b))
    failing = degraded + extra
    s_young = health_status(NOW - timedelta(seconds=younger), NOW, degraded, failing)
    s_old = health_status(NOW - timedelta(seconds=older), NOW, degraded, failing)
    assert ORDER.index(s_young) <= ORDER.index(s_old)


def test_unreadable_store_claims_nothing():
    result = unknown_health()
    assert [h.component for h in result] == list(COMPONENTS)
    assert {h.status for h in result} == {HealthStatus.UNKNOWN}
