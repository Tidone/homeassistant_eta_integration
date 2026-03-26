"""Unit tests for EtaWritableNumberSensor.async_set_native_value."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.eta_webservices.const import (
    ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION,
)
from custom_components.eta_webservices.number import EtaWritableNumberSensor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_URL = "/user/var/12345"


def _make_endpoint_info(
    url=_URL,
    value=20.0,
    scaled_min_value=5.0,
    scaled_max_value=30.0,
    scale_factor=10,
    dec_places=1,
    unit="°C",
    endpoint_type="DEFAULT",
):
    return {
        "url": url,
        "value": value,
        "valid_values": {
            "scaled_min_value": scaled_min_value,
            "scaled_max_value": scaled_max_value,
            "scale_factor": scale_factor,
            "dec_places": dec_places,
        },
        "friendly_name": "ETA > Boiler Temperature",
        "unit": unit,
        "endpoint_type": endpoint_type,
    }


def _make_config(ignore_ids=None):
    return {
        CONF_HOST: "192.168.0.25",
        CONF_PORT: 9091,
        ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION: ignore_ids or [],
    }


def _make_coordinator(url=_URL, value=20.0):
    coordinator = MagicMock()
    coordinator.data = {url: value}
    coordinator.async_refresh = AsyncMock()
    return coordinator


@contextmanager
def _mock_write(sensor, *, returns=True):
    """Patch _create_eta_client so write_endpoint returns `returns`."""
    mock_client = MagicMock()
    mock_client.write_endpoint = AsyncMock(return_value=returns)
    with patch.object(sensor, "_create_eta_client", return_value=mock_client):
        yield mock_client


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def make_sensor(hass: HomeAssistant):
    """Factory that builds an EtaWritableNumberSensor with mocked HTTP session."""

    def _make(
        endpoint_info=None, config=None, unique_id="test_sensor_id", coordinator=None
    ):
        endpoint_info = endpoint_info or _make_endpoint_info()
        config = config or _make_config()
        coordinator = coordinator or _make_coordinator(endpoint_info["url"])
        with patch("custom_components.eta_webservices.entity.async_get_clientsession"):
            return EtaWritableNumberSensor(
                config, hass, unique_id, endpoint_info, coordinator
            )

    return _make


# ---------------------------------------------------------------------------
# Bounds-validation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raises_when_value_below_min(make_sensor):
    """Value strictly below scaled_min_value must raise HomeAssistantError."""
    endpoint = _make_endpoint_info(scaled_min_value=5.0, scaled_max_value=30.0)
    sensor = make_sensor(endpoint_info=endpoint)

    with _mock_write(sensor) as mock_client:
        with pytest.raises(HomeAssistantError):
            await sensor.async_set_native_value(4.9)
        mock_client.write_endpoint.assert_not_awaited()


@pytest.mark.asyncio
async def test_raises_when_value_above_max(make_sensor):
    """Value strictly above scaled_max_value must raise HomeAssistantError."""
    endpoint = _make_endpoint_info(scaled_min_value=5.0, scaled_max_value=30.0)
    sensor = make_sensor(endpoint_info=endpoint)

    with _mock_write(sensor) as mock_client:
        with pytest.raises(HomeAssistantError):
            await sensor.async_set_native_value(30.1)
        mock_client.write_endpoint.assert_not_awaited()


@pytest.mark.asyncio
async def test_does_not_raise_at_min_boundary(make_sensor):
    """Value equal to scaled_min_value is valid and must call write_endpoint."""
    endpoint = _make_endpoint_info(scaled_min_value=5.0, scaled_max_value=30.0)
    sensor = make_sensor(endpoint_info=endpoint)

    with _mock_write(sensor) as mock_client:
        await sensor.async_set_native_value(5.0)
    mock_client.write_endpoint.assert_awaited_once()


@pytest.mark.asyncio
async def test_does_not_raise_at_max_boundary(make_sensor):
    """Value equal to scaled_max_value is valid and must call write_endpoint."""
    endpoint = _make_endpoint_info(scaled_min_value=5.0, scaled_max_value=30.0)
    sensor = make_sensor(endpoint_info=endpoint)

    with _mock_write(sensor) as mock_client:
        await sensor.async_set_native_value(30.0)
    mock_client.write_endpoint.assert_awaited_once()


# ---------------------------------------------------------------------------
# Raw-value calculation – normal path (integer-type sensor)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integer_type_rounds_and_scales(make_sensor):
    """Normal integer sensor: raw = round(round(value, dec_places) * scale_factor, 0)."""
    endpoint = _make_endpoint_info(
        dec_places=1, scale_factor=10, endpoint_type="DEFAULT"
    )
    sensor = make_sensor(endpoint_info=endpoint)

    # round(20.56, 1) = 20.6  →  20.6 * 10 = 206.0  →  round(206.0, 0) = 206.0
    with _mock_write(sensor) as mock_client:
        await sensor.async_set_native_value(20.56)
    mock_client.write_endpoint.assert_awaited_once_with(_URL, 206.0)


@pytest.mark.asyncio
async def test_dec_places_zero_rounds_to_integer(make_sensor):
    """With dec_places=0, rounding eliminates fractions before scaling."""
    endpoint = _make_endpoint_info(
        dec_places=0, scale_factor=10, endpoint_type="DEFAULT"
    )
    sensor = make_sensor(endpoint_info=endpoint)

    # round(20.7, 0) = 21.0  →  21.0 * 10 = 210.0  →  round(210.0, 0) = 210.0
    with _mock_write(sensor) as mock_client:
        await sensor.async_set_native_value(20.7)
    mock_client.write_endpoint.assert_awaited_once_with(_URL, 210.0)


# ---------------------------------------------------------------------------
# Raw-value calculation – normal path (IEEE-754 float sensor)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_float_type_skips_final_round(make_sensor):
    """IEEE-754 sensor must NOT apply the final round(raw, 0) step.

    We use a value that, after rounding to dec_places and scaling, yields a
    result with a fractional part — confirming the branch was NOT rounded away.
    """
    # dec_places=2, scale_factor=3 → a value that stays fractional after scaling
    endpoint = _make_endpoint_info(
        scaled_min_value=0.0,
        scaled_max_value=100.0,
        dec_places=2,
        scale_factor=3,
        endpoint_type="IEEE-754",
    )
    sensor = make_sensor(endpoint_info=endpoint)

    # round(10.33, 2) = 10.33  →  10.33 * 3 = 30.990…  (not an integer)
    expected = round(10.33, 2) * 3  # ≈ 30.990…
    assert expected != round(expected, 0), (
        "sanity: value must not already be an integer"
    )

    with _mock_write(sensor) as mock_client:
        await sensor.async_set_native_value(10.33)
    mock_client.write_endpoint.assert_awaited_once_with(_URL, expected)


# ---------------------------------------------------------------------------
# Raw-value calculation – ignore-decimal path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ignore_decimal_restriction_uses_scale_factor(
    hass: HomeAssistant, make_sensor
):
    """sensor listed in ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION → raw = round(value * scale_factor, 0)."""
    unique_id = "my_special_sensor"
    config = _make_config(ignore_ids=[unique_id])

    # round(20.55 * 10, 0) = round(205.5, 0) = 206.0
    # Normal path would give: round(round(20.55, 1) * 10, 0) = round(20.6 * 10, 0) = 206.0
    # Use a value where the two paths diverge: 20.54
    # ignore path: round(20.54 * 10, 0) = round(205.4, 0) = 205.0
    # normal path: round(round(20.54, 1) * 10, 0) = round(20.5 * 10, 0) = 205.0 … same
    # Try 20.549:
    # ignore path: round(20.549 * 10, 0) = round(205.49, 0) = 205.0
    # normal path: round(round(20.549, 1) * 10, 0) = round(20.5 * 10, 0) = 205.0 … same
    # Try scale_factor=100, dec_places=1, value=1.055:
    # ignore: round(1.055 * 100, 0) = round(105.5, 0) = 106.0
    # normal: round(round(1.055, 1) * 100, 0) = round(1.1 * 100, 0) = round(110.0, 0) = 110.0 ← diverges!
    endpoint2 = _make_endpoint_info(
        scaled_min_value=0.0,
        scaled_max_value=100.0,
        dec_places=1,
        scale_factor=100,
        endpoint_type="DEFAULT",
    )
    sensor2 = make_sensor(endpoint_info=endpoint2, config=config, unique_id=unique_id)

    with _mock_write(sensor2) as mock_client:
        await sensor2.async_set_native_value(1.055)
    # ignore-decimal path: round(1.055 * 100, 0)
    mock_client.write_endpoint.assert_awaited_once_with(_URL, round(1.055 * 100, 0))


@pytest.mark.asyncio
async def test_force_decimals_uses_scale_factor(make_sensor):
    """force_decimals=True activates the same formula as ignore_decimal_restriction."""
    endpoint = _make_endpoint_info(
        scaled_min_value=0.0,
        scaled_max_value=100.0,
        dec_places=1,
        scale_factor=100,
        endpoint_type="DEFAULT",
    )
    sensor = make_sensor(endpoint_info=endpoint)

    with _mock_write(sensor) as mock_client:
        await sensor.async_set_native_value(1.055, force_decimals=True)
    mock_client.write_endpoint.assert_awaited_once_with(_URL, round(1.055 * 100, 0))


# ---------------------------------------------------------------------------
# API interaction tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_failure_raises_home_assistant_error(make_sensor):
    """write_endpoint returning False must raise HomeAssistantError and skip refresh."""
    coordinator = _make_coordinator()
    sensor = make_sensor(coordinator=coordinator)

    with _mock_write(sensor, returns=False):
        with pytest.raises(HomeAssistantError):
            await sensor.async_set_native_value(20.0)

    coordinator.async_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_coordinator_refreshed_after_successful_write(make_sensor):
    """coordinator.async_refresh must be awaited exactly once after a successful write."""
    coordinator = _make_coordinator()
    sensor = make_sensor(coordinator=coordinator)

    with _mock_write(sensor, returns=True):
        await sensor.async_set_native_value(20.0)

    coordinator.async_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_write_endpoint_called_with_correct_uri_and_value(make_sensor):
    """write_endpoint receives the sensor's URI and the computed raw_value."""
    custom_url = "/user/var/99999"
    endpoint = _make_endpoint_info(
        url=custom_url,
        scaled_min_value=0.0,
        scaled_max_value=100.0,
        dec_places=0,
        scale_factor=1,
        endpoint_type="DEFAULT",
    )
    coordinator = _make_coordinator(url=custom_url)
    sensor = make_sensor(endpoint_info=endpoint, coordinator=coordinator)

    # dec_places=0, scale_factor=1, is_float=False
    # raw = round(round(20.0, 0) * 1, 0) = 20.0
    with _mock_write(sensor) as mock_client:
        await sensor.async_set_native_value(20.0)

    mock_client.write_endpoint.assert_awaited_once_with(custom_url, 20.0)
