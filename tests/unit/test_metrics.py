import pytest

from keepair.metrics import Metrics

pytestmark = pytest.mark.req("SEC-36", "ISO 27001 A.8.16")


def test_counters_count_per_label_and_render():
    m = Metrics()
    m.describe("keepair_failures_total", "Failures by reason code.")
    m.inc("keepair_failures_total", code="A")
    m.inc("keepair_failures_total", code="A")
    m.inc("keepair_failures_total", code='B"x')
    assert m.value("keepair_failures_total", code="A") == 2
    assert m.value("keepair_failures_total", code="missing") == 0
    text = m.render()
    assert "# TYPE keepair_failures_total counter" in text
    assert 'keepair_failures_total{code="A"} 2' in text
    assert 'code="B\\"x"' in text
