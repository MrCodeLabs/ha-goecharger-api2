"""Exercise the actual PV blueprint with Home Assistant's automation engine."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from homeassistant.helpers.sun import get_astral_event_date

BLUEPRINT = (
    Path(__file__).resolve().parents[2]
    / "example/blueprint/automation/go-echarger-pv-surplus-data.yaml"
)
SERVICE = "goecharger_api2.set_pv_data"
CAR = "binary_sensor.car_connected"
GRID = "sensor.grid_power"
PV = "sensor.pv_power"
NOON = datetime(2026, 6, 21, 12, tzinfo=UTC)
LIVE_POWER = {"pgrid": -800, "ppv": 1800, "pakku": 0}
ZERO_POWER = {"pgrid": 0, "ppv": 0, "pakku": 0}


@pytest.fixture
async def pv_env(blueprint_env):
    config = blueprint_env.hass.config
    config.latitude = 0
    config.longitude = 0
    config.elevation = 0
    await config.async_set_time_zone("UTC")
    return blueprint_env


async def start_pv(env, when, connected):
    await env.start(
        BLUEPRINT,
        {
            "car_connected_entity": {"entity_id": CAR},
            "grid_single_entity": GRID,
            "pv_entities": [PV],
            "maximum_age_seconds": 12,
        },
        states={CAR: connected, GRID: "-800", PV: "1800"},
        services=[SERVICE],
        components=["sun"],
        when=when,
    )


def sent_power(env):
    return [dict(call.data) for call in env.calls_to(SERVICE)]


async def test_daylight_pauses_on_stale_data_and_resumes_on_same_value_report(pv_env):
    await start_pv(pv_env, NOON, connected="on")

    # Advance once per tick so HA runs every scheduled five-second trigger.
    await pv_env.advance(5)
    assert sent_power(pv_env) == [LIVE_POWER]
    await pv_env.advance(5)
    assert sent_power(pv_env) == [LIVE_POWER, LIVE_POWER]

    await pv_env.advance(5)
    assert sent_power(pv_env) == [LIVE_POWER, LIVE_POWER], "stale measurements were sent"

    # A new report with the same value must refresh HA's last_reported.
    await pv_env.set_state(GRID, "-800")
    await pv_env.set_state(PV, "1800")
    await pv_env.advance(5)
    assert sent_power(pv_env) == [LIVE_POWER, LIVE_POWER, LIVE_POWER]


async def test_sunset_sends_zero_once_with_car_disconnected(pv_env):
    sunset = get_astral_event_date(pv_env.hass, "sunset", NOON.date())
    assert sunset is not None
    await start_pv(pv_env, sunset - timedelta(seconds=10), connected="off")

    await pv_env.advance(5)
    assert sent_power(pv_env) == []

    await pv_env.advance(6)
    assert sent_power(pv_env) == [ZERO_POWER], "sunset did not send one zero payload"

    await pv_env.advance(5)
    assert sent_power(pv_env) == [ZERO_POWER]
