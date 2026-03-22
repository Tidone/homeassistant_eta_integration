"""Unit tests for coordinator update interval configuration."""

from datetime import timedelta

import pytest
from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from unittest.mock import AsyncMock, MagicMock, patch

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
    COORDINATOR_WARNING_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    FLOAT_DICT,
    LAST_COORDINATOR_WARNING_TIMESTAMP,
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


# ---------------------------------------------------------------------------
# Warning behaviour tests
# ---------------------------------------------------------------------------

_TIME_MODULE = "custom_components.eta_webservices.coordinator.time"
_LOGGER_MODULE = "custom_components.eta_webservices.coordinator._LOGGER"
_INTERVAL = 60  # update_interval used in all warning tests


# -- ETASensorUpdateCoordinator ---------------------------------------------


async def test_sensor_coordinator_warns_when_update_exceeds_interval(
    mock_hass, mock_client_session
):
    """A warning is logged when elapsed > update_interval and no recent warning exists."""
    config = _interval_config(_INTERVAL)
    coordinator = ETASensorUpdateCoordinator(mock_hass, config)

    with patch(_TIME_MODULE) as mock_time, patch(_LOGGER_MODULE) as mock_logger:
        mock_time.monotonic.side_effect = [0.0, _INTERVAL + 10.0]
        mock_time.time.return_value = COORDINATOR_WARNING_INTERVAL + 1.0

        await coordinator._async_update_data()

    mock_logger.warning.assert_called_once()
    assert config[LAST_COORDINATOR_WARNING_TIMESTAMP] == COORDINATOR_WARNING_INTERVAL + 1.0


async def test_sensor_coordinator_no_warn_when_update_within_interval(
    mock_hass, mock_client_session
):
    """No warning is logged when elapsed <= update_interval."""
    config = _interval_config(_INTERVAL)
    coordinator = ETASensorUpdateCoordinator(mock_hass, config)

    with patch(_TIME_MODULE) as mock_time, patch(_LOGGER_MODULE) as mock_logger:
        mock_time.monotonic.side_effect = [0.0, _INTERVAL - 10.0]
        mock_time.time.return_value = COORDINATOR_WARNING_INTERVAL + 1.0

        await coordinator._async_update_data()

    mock_logger.warning.assert_not_called()


async def test_sensor_coordinator_no_second_warn_within_warning_interval(
    mock_hass, mock_client_session
):
    """A second warning is suppressed when less than COORDINATOR_WARNING_INTERVAL has passed."""
    config = _interval_config(_INTERVAL)
    coordinator = ETASensorUpdateCoordinator(mock_hass, config)
    # Simulate a recent warning 1 second ago.
    recent_ts = 5000.0
    config[LAST_COORDINATOR_WARNING_TIMESTAMP] = recent_ts

    with patch(_TIME_MODULE) as mock_time, patch(_LOGGER_MODULE) as mock_logger:
        mock_time.monotonic.side_effect = [0.0, _INTERVAL + 10.0]
        mock_time.time.return_value = recent_ts + 1.0  # only 1 s since last warning

        await coordinator._async_update_data()

    mock_logger.warning.assert_not_called()


async def test_sensor_coordinator_warns_again_after_warning_interval(
    mock_hass, mock_client_session
):
    """A warning fires again once COORDINATOR_WARNING_INTERVAL seconds have elapsed."""
    config = _interval_config(_INTERVAL)
    coordinator = ETASensorUpdateCoordinator(mock_hass, config)

    with patch(_TIME_MODULE) as mock_time, patch(_LOGGER_MODULE) as mock_logger:
        # First call: fires warning, timestamp recorded as 1000.0.
        # Second call: COORDINATOR_WARNING_INTERVAL + 1 s have passed → fires again.
        mock_time.monotonic.side_effect = [
            0.0, _INTERVAL + 10.0,  # first call
            0.0, _INTERVAL + 10.0,  # second call
        ]
        # time.time() must exceed COORDINATOR_WARNING_INTERVAL on the first call
        # (since LAST_COORDINATOR_WARNING_TIMESTAMP defaults to 0).
        first_ts = float(COORDINATOR_WARNING_INTERVAL + 1)
        second_ts = first_ts + COORDINATOR_WARNING_INTERVAL + 1.0
        mock_time.time.side_effect = [
            first_ts, first_ts,    # first call: check + record
            second_ts, second_ts,  # second call: check + record
        ]

        await coordinator._async_update_data()
        await coordinator._async_update_data()

    assert mock_logger.warning.call_count == 2


# -- ETAWritableUpdateCoordinator -------------------------------------------


def _make_writable_coordinator(mock_hass, update_interval=_INTERVAL):
    """Return an ETAWritableUpdateCoordinator with a mocked ETA client."""
    config = _interval_config(update_interval)
    coordinator = ETAWritableUpdateCoordinator(mock_hass, config)
    mock_client = MagicMock()
    mock_client.get_all_data = AsyncMock(return_value={})
    coordinator._create_eta_client = MagicMock(return_value=mock_client)
    return coordinator


async def test_writable_coordinator_warns_when_update_exceeds_interval(
    mock_hass, mock_client_session
):
    """A warning is logged when elapsed > update_interval and no recent warning exists."""
    coordinator = _make_writable_coordinator(mock_hass)

    with patch(_TIME_MODULE) as mock_time, patch(_LOGGER_MODULE) as mock_logger:
        mock_time.monotonic.side_effect = [0.0, _INTERVAL + 10.0]
        mock_time.time.return_value = COORDINATOR_WARNING_INTERVAL + 1.0

        await coordinator._async_update_data()

    mock_logger.warning.assert_called_once()
    assert (
        coordinator.config[LAST_COORDINATOR_WARNING_TIMESTAMP]
        == COORDINATOR_WARNING_INTERVAL + 1.0
    )


async def test_writable_coordinator_no_warn_when_update_within_interval(
    mock_hass, mock_client_session
):
    """No warning is logged when elapsed <= update_interval."""
    coordinator = _make_writable_coordinator(mock_hass)

    with patch(_TIME_MODULE) as mock_time, patch(_LOGGER_MODULE) as mock_logger:
        mock_time.monotonic.side_effect = [0.0, _INTERVAL - 10.0]
        mock_time.time.return_value = COORDINATOR_WARNING_INTERVAL + 1.0

        await coordinator._async_update_data()

    mock_logger.warning.assert_not_called()


async def test_writable_coordinator_no_second_warn_within_warning_interval(
    mock_hass, mock_client_session
):
    """A second warning is suppressed when less than COORDINATOR_WARNING_INTERVAL has passed."""
    coordinator = _make_writable_coordinator(mock_hass)
    recent_ts = 5000.0
    coordinator.config[LAST_COORDINATOR_WARNING_TIMESTAMP] = recent_ts

    with patch(_TIME_MODULE) as mock_time, patch(_LOGGER_MODULE) as mock_logger:
        mock_time.monotonic.side_effect = [0.0, _INTERVAL + 10.0]
        mock_time.time.return_value = recent_ts + 1.0

        await coordinator._async_update_data()

    mock_logger.warning.assert_not_called()


async def test_writable_coordinator_warns_again_after_warning_interval(
    mock_hass, mock_client_session
):
    """A warning fires again once COORDINATOR_WARNING_INTERVAL seconds have elapsed."""
    coordinator = _make_writable_coordinator(mock_hass)

    with patch(_TIME_MODULE) as mock_time, patch(_LOGGER_MODULE) as mock_logger:
        mock_time.monotonic.side_effect = [
            0.0, _INTERVAL + 10.0,
            0.0, _INTERVAL + 10.0,
        ]
        first_ts = float(COORDINATOR_WARNING_INTERVAL + 1)
        second_ts = first_ts + COORDINATOR_WARNING_INTERVAL + 1.0
        mock_time.time.side_effect = [
            first_ts, first_ts,
            second_ts, second_ts,
        ]

        await coordinator._async_update_data()
        await coordinator._async_update_data()

    assert mock_logger.warning.call_count == 2
