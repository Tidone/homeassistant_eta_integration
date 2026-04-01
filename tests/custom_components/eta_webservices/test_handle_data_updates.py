"""Tests that _handle_coordinator_update clears the entity state when the entity's
key is absent from the coordinator's data dict.

Covers every non-error entity class across sensor.py, number.py, time.py, and switch.py.
- sensor/number/time entities: _attr_native_value → None
- EtaSwitch: _attr_is_on → None
Error entities (EtaNbrErrorsSensor, EtaLatestErrorSensor) are excluded because they receive
the full error list from the coordinator rather than a value keyed by entity — the
"missing key → None" pattern does not apply to them.
"""

from unittest.mock import MagicMock, patch

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from custom_components.eta_webservices.const import (
    ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION,
    CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
    CUSTOM_UNIT_TIMESLOT,
)
from custom_components.eta_webservices.number import EtaWritableNumberSensor
from custom_components.eta_webservices.switch import EtaSwitch
from custom_components.eta_webservices.sensor import (
    EtaFloatSensor,
    EtaTextSensor,
    EtaTimeslotSensor,
    EtaTimeWritableSensor,
)
from custom_components.eta_webservices.time import EtaTime

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_UNIQUE_ID = "test_entity"
_URL = "/test/url/123"
_OTHER_UNIQUE_ID = "other_entity"
_OTHER_URL = "/other/url/456"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config():
    return {
        CONF_HOST: "192.168.0.25",
        CONF_PORT: 9091,
        ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION: [],
    }


def _make_switch_endpoint(url=_URL):
    """Minimal endpoint info for EtaSwitch (valid_values must be a dict)."""
    return {
        "url": url,
        "value": True,
        "valid_values": {"on_value": 1803, "off_value": 1802},
        "friendly_name": "ETA > Test Switch",
        "unit": "",
        "endpoint_type": "DEFAULT",
    }


def _make_float_endpoint(url=_URL, unit="°C"):
    """Minimal endpoint info for read-only (non-writable) sensors."""
    return {
        "url": url,
        "value": 42.0,
        "valid_values": None,
        "friendly_name": "ETA > Test Sensor",
        "unit": unit,
        "endpoint_type": "DEFAULT",
    }


def _make_writable_endpoint(url=_URL, unit="°C"):
    """Minimal endpoint info for writable sensors (valid_values must be a dict)."""
    return {
        "url": url,
        "value": 42.0,
        "valid_values": {
            "scaled_min_value": 0.0,
            "scaled_max_value": 100.0,
            "scale_factor": 10,
            "dec_places": 1,
        },
        "friendly_name": "ETA > Test Sensor",
        "unit": unit,
        "endpoint_type": "DEFAULT",
    }


def _make_sensor_coordinator(value=42.0):
    """Coordinator keyed by URI (used by EtaCoordinatedSensorEntity subclasses)."""
    c = MagicMock()
    c.data = {_URL: value}
    return c


def _make_writable_coordinator(value=42.0):
    """Coordinator keyed by URI (used by EtaWritableSensorEntity subclasses)."""
    c = MagicMock()
    c.data = {_URL: value}
    return c


def _assert_clears_native_value(entity, coordinator, dummy_data):
    """Core assertion used by every test.

    1. Replaces coordinator.data with dummy_data (has entries, but not the entity's key).
    2. Calls _handle_coordinator_update() (patching async_write_ha_state to prevent
       HA state-machine errors when the entity isn't registered with a real platform).
    3. Asserts _attr_native_value is None.
    """
    coordinator.data = dummy_data
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()
    assert entity._attr_native_value is None


# ---------------------------------------------------------------------------
# sensor.py — EtaFloatSensor
# ---------------------------------------------------------------------------


def test_eta_float_sensor_clears_value_when_key_missing(hass: HomeAssistant):
    """EtaFloatSensor._attr_native_value is None when its URI is absent from data."""
    coordinator = _make_sensor_coordinator(42.0)
    with patch("custom_components.eta_webservices.entity.async_get_clientsession"):
        entity = EtaFloatSensor(
            _make_config(), hass, _UNIQUE_ID, _make_float_endpoint(), coordinator
        )

    assert entity._attr_native_value is not None  # sanity: starts with a real value

    _assert_clears_native_value(entity, coordinator, {_OTHER_URL: 0.0})


# ---------------------------------------------------------------------------
# sensor.py — EtaTextSensor
# ---------------------------------------------------------------------------


def test_eta_text_sensor_clears_value_when_key_missing(hass: HomeAssistant):
    """EtaTextSensor._attr_native_value is None when its URI is absent from data."""
    coordinator = _make_sensor_coordinator("Ein")
    with patch("custom_components.eta_webservices.entity.async_get_clientsession"):
        entity = EtaTextSensor(
            _make_config(), hass, _UNIQUE_ID, _make_float_endpoint(unit=""), coordinator
        )

    assert entity._attr_native_value is not None

    _assert_clears_native_value(entity, coordinator, {_OTHER_URL: "Aus"})


# ---------------------------------------------------------------------------
# sensor.py — EtaTimeslotSensor
# ---------------------------------------------------------------------------


def test_eta_timeslot_sensor_clears_value_when_key_missing(hass: HomeAssistant):
    """EtaTimeslotSensor._attr_native_value is None when its URI is absent from data."""
    coordinator = _make_sensor_coordinator("15:00 - 16:00")
    with patch("custom_components.eta_webservices.entity.async_get_clientsession"):
        entity = EtaTimeslotSensor(
            _make_config(),
            hass,
            _UNIQUE_ID,
            _make_float_endpoint(unit=CUSTOM_UNIT_TIMESLOT),
            coordinator,
            should_activate_service=False,
        )

    assert entity._attr_native_value is not None

    _assert_clears_native_value(entity, coordinator, {_OTHER_URL: "09:00 - 10:00"})


# ---------------------------------------------------------------------------
# sensor.py — EtaTimeWritableSensor
# ---------------------------------------------------------------------------


def test_eta_time_writable_sensor_clears_value_when_key_missing(hass: HomeAssistant):
    """EtaTimeWritableSensor._attr_native_value is None when its URI is absent from data."""
    coordinator = _make_writable_coordinator(42.0)
    with patch("custom_components.eta_webservices.entity.async_get_clientsession"):
        entity = EtaTimeWritableSensor(
            _make_config(),
            hass,
            _UNIQUE_ID,
            _make_float_endpoint(unit=CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT),
            coordinator,
        )

    assert entity._attr_native_value is not None

    _assert_clears_native_value(entity, coordinator, {_OTHER_URL: 42.0})


# ---------------------------------------------------------------------------
# number.py — EtaWritableNumberSensor
# ---------------------------------------------------------------------------


def test_eta_writable_number_sensor_clears_value_when_key_missing(hass: HomeAssistant):
    """EtaWritableNumberSensor._attr_native_value is None when its URI is absent from data."""
    coordinator = _make_writable_coordinator(42.0)
    with patch("custom_components.eta_webservices.entity.async_get_clientsession"):
        entity = EtaWritableNumberSensor(
            _make_config(), hass, _UNIQUE_ID, _make_writable_endpoint(), coordinator
        )

    assert entity._attr_native_value is not None

    _assert_clears_native_value(entity, coordinator, {_OTHER_URL: 0.0})


# ---------------------------------------------------------------------------
# time.py — EtaTime
# ---------------------------------------------------------------------------


def test_eta_time_clears_value_when_key_missing(hass: HomeAssistant):
    """EtaTime._attr_native_value is None when its URI is absent from data.

    EtaTime always sets _attr_native_value = time(hour=19) after its parent __init__,
    so the entity starts with a non-None value regardless of coordinator data.
    """
    coordinator = _make_writable_coordinator(42.0)
    with patch("custom_components.eta_webservices.entity.async_get_clientsession"):
        entity = EtaTime(
            _make_config(),
            hass,
            _UNIQUE_ID,
            _make_writable_endpoint(unit=CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT),
            coordinator,
        )

    assert entity._attr_native_value is not None  # time(hour=19) after construction

    _assert_clears_native_value(entity, coordinator, {_OTHER_URL: 0.0})


# ---------------------------------------------------------------------------
# switch.py — EtaSwitch
# ---------------------------------------------------------------------------


def test_eta_switch_clears_is_on_when_key_missing(hass: HomeAssistant):
    """EtaSwitch._attr_is_on is None when its unique_id is absent from data.

    EtaSwitch does not use the handle_data_updates pattern; it sets _attr_is_on
    directly in its own _handle_coordinator_update override.
    """
    coordinator = _make_sensor_coordinator(True)
    with patch("custom_components.eta_webservices.entity.async_get_clientsession"):
        entity = EtaSwitch(
            _make_config(), hass, _UNIQUE_ID, _make_switch_endpoint(), coordinator
        )

    assert entity._attr_is_on is not None  # sanity: True after construction

    coordinator.data = {_OTHER_URL: True}
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()
    assert entity._attr_is_on is None
