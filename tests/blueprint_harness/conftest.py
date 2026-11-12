import pytest

pytest_plugins = ["ha_blueprint_test_harness.pytest_plugin"]


@pytest.fixture
def expected_lingering_timers():
    """The blueprint keeps its periodic and sunset triggers scheduled."""
    return True
