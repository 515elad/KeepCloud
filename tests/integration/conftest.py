import pytest

from tests.gateway_harness import make_gateway


@pytest.fixture
def gw(settings, engine):
    return make_gateway(settings, engine)
