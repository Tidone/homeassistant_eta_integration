"""Unit tests for coordinator update interval configuration."""

from datetime import timedelta

import pytest
from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from unittest.mock import MagicMock, patch

from custom_components.eta_webservices.coordinator import (
    ETAErrorUpdateCoordinator,
    ETAPendingNodeCoordinator,
    ETASensorUpdateCoordinator,
    ETAWritableUpdateCoordinator,
)
from custom_components.eta_webservices.const import (
    CHOSEN_FLOAT_SENSORS,
    CHOSEN_PENDING_SENSORS,
    CHOSEN_SWITCHES,
    CHOSEN_TEXT_SENSORS,
    CHOSEN_WRITABLE_SENSORS,
    DEFAULT_UPDATE_INTERVAL,
    FLOAT_DICT,
    PENDING_DICT,
    SWITCHES_DICT,
    TEXT_DICT,
    UPDATE_INTERVAL,
    WRITABLE_DICT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hass():
    """Lightweight MagicMock standing in for HomeAssistant."""
    return MagicMock()


@pytest.fixture
def mock_client_session():
    """Patch async_get_clientsession so coordinators never create a real session."""
    with patch(
        "custom_components.eta_webservices.coordinator.async_get_clientsession",
        return_value=MagicMock(spec=ClientSession),
    ):
        yield


@pytest.fixture(autouse=True)
def mock_frame_report():
    """Suppress HA's frame-helper deprecation check (requires real hass setup)."""
    with patch("homeassistant.helpers.frame.report_usage"):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _interval_config(update_interval=DEFAULT_UPDATE_INTERVAL):
    """Return a minimal config dict for coordinator instantiation."""
    return {
        CONF_HOST: "192.168.0.25",
        CONF_PORT: 8080,
        UPDATE_INTERVAL: update_interval,
        PENDING_DICT: {},
        CHOSEN_FLOAT_SENSORS: [],
        CHOSEN_SWITCHES: [],
        CHOSEN_TEXT_SENSORS: [],
        CHOSEN_WRITABLE_SENSORS: [],
        CHOSEN_PENDING_SENSORS: [],
        FLOAT_DICT: {},
        SWITCHES_DICT: {},
        TEXT_DICT: {},
        WRITABLE_DICT: {},
    }


# ---------------------------------------------------------------------------
# Update interval tests
# ---------------------------------------------------------------------------


def test_sensor_coordinator_uses_configured_interval(mock_hass, mock_client_session):
    """ETASensorUpdateCoordinator uses the exact user-configured interval."""
    coordinator = ETASensorUpdateCoordinator(mock_hass, _interval_config(30))
    assert coordinator.update_interval == timedelta(seconds=30)


def test_writable_coordinator_uses_configured_interval(mock_hass, mock_client_session):
    """ETAWritableUpdateCoordinator uses the exact user-configured interval."""
    coordinator = ETAWritableUpdateCoordinator(mock_hass, _interval_config(30))
    assert coordinator.update_interval == timedelta(seconds=30)


def test_error_coordinator_uses_double_interval(mock_hass, mock_client_session):
    """ETAErrorUpdateCoordinator uses 2× the user-configured interval."""
    coordinator = ETAErrorUpdateCoordinator(mock_hass, _interval_config(30))
    assert coordinator.update_interval == timedelta(seconds=60)


def test_pending_coordinator_uses_five_times_interval(mock_hass, mock_client_session):
    """ETAPendingNodeCoordinator uses 5× the user-configured interval."""
    entry = MagicMock(spec=ConfigEntry)
    entry.pref_disable_polling = False
    coordinator = ETAPendingNodeCoordinator(mock_hass, _interval_config(30), entry)
    assert coordinator.update_interval == timedelta(seconds=150)


def test_coordinators_default_to_60s_when_interval_not_set(
    mock_hass, mock_client_session
):
    """Entries that pre-date this feature (no UPDATE_INTERVAL key) fall back to 60 s."""
    config = _interval_config()
    config.pop(UPDATE_INTERVAL)
    coordinator = ETASensorUpdateCoordinator(mock_hass, config)
    assert coordinator.update_interval == timedelta(seconds=DEFAULT_UPDATE_INTERVAL)


def test_all_coordinators_respect_120s_interval(mock_hass, mock_client_session):
    """Verify multiplier chain at the upper bound (120 s)."""
    entry = MagicMock(spec=ConfigEntry)
    entry.pref_disable_polling = False
    config = _interval_config(120)

    assert ETASensorUpdateCoordinator(mock_hass, config).update_interval == timedelta(
        seconds=120
    )
    assert ETAWritableUpdateCoordinator(mock_hass, config).update_interval == timedelta(
        seconds=120
    )
    assert ETAErrorUpdateCoordinator(mock_hass, config).update_interval == timedelta(
        seconds=240
    )
    assert ETAPendingNodeCoordinator(
        mock_hass, config, entry
    ).update_interval == timedelta(seconds=600)
