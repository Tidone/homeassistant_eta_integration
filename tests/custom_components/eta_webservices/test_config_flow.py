"""Unit tests for config_flow helper logic."""

import pytest
from unittest.mock import AsyncMock, Mock, MagicMock, patch
from homeassistant.const import CONF_HOST, CONF_PORT

from custom_components.eta_webservices.config_flow import (
    _is_invalid_host_input,
    _sanitize_selected_entity_ids,
    EtaOptionsFlowHandler,
)
from custom_components.eta_webservices.const import (
    ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION,
    CHOSEN_FLOAT_SENSORS,
    CHOSEN_PENDING_SENSORS,
    CHOSEN_SWITCHES,
    CHOSEN_TEXT_SENSORS,
    CHOSEN_WRITABLE_SENSORS,
    CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
    DEFAULT_UPDATE_INTERVAL,
    FLOAT_DICT,
    FORCE_LEGACY_MODE,
    MAX_PARALLEL_REQUESTS,
    PENDING_DICT,
    SWITCHES_DICT,
    TEXT_DICT,
    UPDATE_INTERVAL,
    WRITABLE_DICT,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_runtime_config(overrides=None):
    """Return a minimal but complete runtime-config dict.

    Pass a plain dict to override individual keys — const values are used as
    dict keys so they resolve to their string values correctly.
    """
    base = {
        CONF_HOST: "192.168.0.25",
        CONF_PORT: 8080,
        FLOAT_DICT: {},
        SWITCHES_DICT: {},
        TEXT_DICT: {},
        WRITABLE_DICT: {},
        PENDING_DICT: {},
        CHOSEN_FLOAT_SENSORS: [],
        CHOSEN_SWITCHES: [],
        CHOSEN_TEXT_SENSORS: [],
        CHOSEN_WRITABLE_SENSORS: [],
        CHOSEN_PENDING_SENSORS: [],
        FORCE_LEGACY_MODE: False,
        MAX_PARALLEL_REQUESTS: 5,
        UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
        ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION: [],
    }
    if overrides:
        base.update(overrides)
    return base


def _make_flow(
    runtime_config=None,
    *,
    enumerate_new_endpoints=False,
    update_sensor_values=False,
    max_parallel_requests=5,
    update_interval=DEFAULT_UPDATE_INTERVAL,
):
    """Return an EtaOptionsFlowHandler wired up for unit testing."""
    flow = EtaOptionsFlowHandler()
    flow.hass = MagicMock()
    flow.enumerate_new_endpoints = enumerate_new_endpoints
    flow.update_sensor_values = update_sensor_values
    flow.max_parallel_requests = max_parallel_requests
    flow.update_interval = update_interval
    if runtime_config is not None:
        flow._get_runtime_config = Mock(return_value=runtime_config)
    flow.async_abort = Mock(return_value="aborted")
    flow.async_step_user = AsyncMock(return_value="step_user_result")
    flow._on_options_progress = Mock()
    return flow


def _make_sensor(url="/uri/sensor", unit="°C", value=42.0):
    return {
        "url": url,
        "unit": unit,
        "value": value,  # type: ignore[assignment]
        "endpoint_type": "DEFAULT",
        "friendly_name": "Test sensor",
        "valid_values": None,
    }


# ---------------------------------------------------------------------------
# _sanitize_selected_entity_ids
# ---------------------------------------------------------------------------


def test_sanitize_selected_entity_ids_removes_cross_category_duplicates():
    """IDs selected in multiple regular sensor groups must be deduplicated."""
    selected_float_sensors = ["a", "b", "a"]
    selected_switches = ["b", "c", "c"]
    selected_text_sensors = ["a", "c", "d", "d"]
    selected_writable_sensors = ["w1", "w1"]
    selected_pending_sensors = ["a", "d", "e", "e"]

    (
        sanitized_float_sensors,
        sanitized_switches,
        sanitized_text_sensors,
        sanitized_writable_sensors,
        sanitized_pending_sensors,
    ) = _sanitize_selected_entity_ids(
        selected_float_sensors,
        selected_switches,
        selected_text_sensors,
        selected_writable_sensors,
        selected_pending_sensors,
    )

    assert sanitized_float_sensors == ["a", "b"]
    assert sanitized_switches == ["c"]
    assert sanitized_text_sensors == ["d"]
    assert sanitized_writable_sensors == ["w1"]
    assert sanitized_pending_sensors == ["e"]


def test_sanitize_selected_entity_ids_keeps_non_overlapping_selections():
    """Selections without overlaps should remain unchanged."""
    selected_float_sensors = ["float_1"]
    selected_switches = ["switch_1"]
    selected_text_sensors = ["text_1"]
    selected_writable_sensors = ["writable_1", "writable_2"]
    selected_pending_sensors = ["pending_1"]

    (
        sanitized_float_sensors,
        sanitized_switches,
        sanitized_text_sensors,
        sanitized_writable_sensors,
        sanitized_pending_sensors,
    ) = _sanitize_selected_entity_ids(
        selected_float_sensors,
        selected_switches,
        selected_text_sensors,
        selected_writable_sensors,
        selected_pending_sensors,
    )

    assert sanitized_float_sensors == selected_float_sensors
    assert sanitized_switches == selected_switches
    assert sanitized_text_sensors == selected_text_sensors
    assert sanitized_writable_sensors == selected_writable_sensors
    assert sanitized_pending_sensors == selected_pending_sensors


def test_is_invalid_host_input_rejects_malformed_hosts():
    """Malformed host inputs must be rejected before discovery starts."""
    assert _is_invalid_host_input(":")
    assert _is_invalid_host_input("%")
    assert _is_invalid_host_input("host name")
    assert _is_invalid_host_input("foo_bar.local")
    assert _is_invalid_host_input("-eta.local")
    assert _is_invalid_host_input("eta-.local")
    assert _is_invalid_host_input("http://172.24.120.210")
    assert _is_invalid_host_input("172.24.120.210/path")
    assert _is_invalid_host_input("[172.24.120.210]")
    assert _is_invalid_host_input("[::")


def test_is_invalid_host_input_accepts_valid_hosts():
    """Normal hostname/IP inputs should be accepted."""
    assert not _is_invalid_host_input("172.24.120.210")
    assert not _is_invalid_host_input("eta.local")
    assert not _is_invalid_host_input("[2001:db8::1]")


# ---------------------------------------------------------------------------
# _prepare_data_structures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_data_structures_raises_when_runtime_config_unavailable():
    """Raises RuntimeError when runtime config is None (integration busy)."""
    flow = _make_flow(runtime_config=None)
    flow._get_runtime_config = Mock(return_value=None)

    with pytest.raises(RuntimeError):
        await flow._prepare_data_structures()


@pytest.mark.asyncio
async def test_prepare_data_structures_copies_all_keys_from_runtime_config():
    """All 13 runtime-config keys are copied into self.data."""
    config = _make_runtime_config(
        {
            FLOAT_DICT: {"s1": _make_sensor()},
            CHOSEN_FLOAT_SENSORS: ["s1"],
            FORCE_LEGACY_MODE: True,
        }
    )
    flow = _make_flow(config)

    await flow._prepare_data_structures()

    assert len(flow.data) == len(config), "flow.data has unexpected number of keys"

    for key in config:
        assert key in flow.data, f"Key {key!r} missing from flow.data"
        assert flow.data[key] == config[key], f"flow.data[{key!r}] mismatch"


@pytest.mark.asyncio
async def test_prepare_data_structures_data_is_shallow_copied():
    """Dict values are shallow-copied; mutating flow.data must not touch the original."""
    original_float = {"s1": _make_sensor()}
    config = _make_runtime_config({FLOAT_DICT: original_float})
    flow = _make_flow(config)

    await flow._prepare_data_structures()

    # Add a new key to the copied dict — original must be unaffected.
    flow.data[FLOAT_DICT]["s2"] = _make_sensor(url="/uri/s2")
    assert "s2" not in original_float


@pytest.mark.asyncio
async def test_prepare_data_structures_stores_max_parallel_requests():
    """self.data[MAX_PARALLEL_REQUESTS] equals flow.max_parallel_requests."""
    config = _make_runtime_config()
    flow = _make_flow(config, max_parallel_requests=3)

    await flow._prepare_data_structures()

    assert flow.data[MAX_PARALLEL_REQUESTS] == 3


@pytest.mark.asyncio
async def test_prepare_data_structures_stores_update_interval():
    """self.data[UPDATE_INTERVAL] equals flow.update_interval."""
    config = _make_runtime_config()
    flow = _make_flow(config, update_interval=30)

    await flow._prepare_data_structures()

    assert flow.data[UPDATE_INTERVAL] == 30


@pytest.mark.asyncio
async def test_prepare_data_structures_advanced_option_defaults_to_empty_list():
    """ADVANCED_OPTIONS key absent from config → defaults to []."""
    config = _make_runtime_config()
    # Ensure the key is not present.
    config.pop(ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION, None)
    flow = _make_flow(config)

    await flow._prepare_data_structures()

    assert flow.data[ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION] == []


@pytest.mark.asyncio
async def test_prepare_data_structures_advanced_option_preserved_when_present():
    """ADVANCED_OPTIONS key present in config → value is copied as-is."""
    config = _make_runtime_config()
    config[ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION] = ["sensor_a"]
    flow = _make_flow(config)

    await flow._prepare_data_structures()

    assert flow.data[ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION] == ["sensor_a"]


@pytest.mark.asyncio
async def test_prepare_data_structures_sanitizes_chosen_sensors():
    """Key present in both CHOSEN_FLOAT_SENSORS and CHOSEN_SWITCHES is deduplicated."""
    config = _make_runtime_config(
        {
            FLOAT_DICT: {"x": _make_sensor()},
            SWITCHES_DICT: {"x": _make_sensor()},
            CHOSEN_FLOAT_SENSORS: ["x"],
            CHOSEN_SWITCHES: ["x"],
        }
    )
    flow = _make_flow(config)

    await flow._prepare_data_structures()

    assert "x" in flow.data[CHOSEN_FLOAT_SENSORS]
    assert "x" not in flow.data[CHOSEN_SWITCHES]


@pytest.mark.asyncio
async def test_prepare_data_structures_completes_and_does_not_call_async_step_user():
    """_prepare_data_structures completes without calling async_step_user (caller handles that)."""
    config = _make_runtime_config()
    flow = _make_flow(config)

    await flow._prepare_data_structures()

    flow.async_step_user.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_data_structures_calls_update_sensor_values_when_requested():
    """update_sensor_values=True triggers _update_sensor_values, not discovery."""
    config = _make_runtime_config()
    flow = _make_flow(config, update_sensor_values=True)
    flow._update_sensor_values = AsyncMock()
    flow._get_possible_endpoints_with_progress = AsyncMock()

    await flow._prepare_data_structures()

    flow._update_sensor_values.assert_awaited_once()
    flow._get_possible_endpoints_with_progress.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_data_structures_does_not_call_update_sensor_values_without_flag():
    """Both flags False → _update_sensor_values is never called."""
    config = _make_runtime_config()
    flow = _make_flow(config)
    flow._update_sensor_values = AsyncMock()

    await flow._prepare_data_structures()

    flow._update_sensor_values.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_data_structures_runs_full_discovery_pipeline():
    """enumerate_new_endpoints=True calls all discovery helpers."""
    config = _make_runtime_config()
    flow = _make_flow(config, enumerate_new_endpoints=True)
    empty = ({}, {}, {}, {}, {})
    flow._get_possible_endpoints_with_progress = AsyncMock(return_value=empty)
    flow._verify_pending_sensors = Mock(return_value=0)
    flow._handle_new_sensors = Mock(return_value=0)
    flow._handle_deleted_sensors = Mock(return_value=0)
    flow._handle_sensor_value_updates_from_enumeration = Mock()
    flow._update_sensor_values = AsyncMock()

    await flow._prepare_data_structures()

    flow._get_possible_endpoints_with_progress.assert_awaited_once_with(
        config[CONF_HOST],
        config[CONF_PORT],
        config[FORCE_LEGACY_MODE],
        progress_callback=flow._on_options_progress,
    )
    flow._verify_pending_sensors.assert_called_once()
    flow._handle_new_sensors.assert_called_once()
    flow._handle_deleted_sensors.assert_called_once()
    flow._handle_sensor_value_updates_from_enumeration.assert_called_once()
    flow._update_sensor_values.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_data_structures_discovery_passes_correct_arguments():
    """Each discovery helper receives the exact dicts returned by _get_possible_endpoints_with_progress."""
    config = _make_runtime_config()
    flow = _make_flow(config, enumerate_new_endpoints=True)

    new_floats = {"f1": _make_sensor(url="/f1")}
    new_switches = {"sw1": _make_sensor(url="/sw1")}
    new_text = {"t1": _make_sensor(url="/t1")}
    new_writable = {"w1": _make_sensor(url="/w1")}
    new_pending = {"p1": _make_sensor(url="/p1")}

    flow._get_possible_endpoints_with_progress = AsyncMock(
        return_value=(new_floats, new_switches, new_text, new_writable, new_pending)
    )
    flow._verify_pending_sensors = Mock(return_value=0)
    flow._handle_new_sensors = Mock(return_value=0)
    flow._handle_deleted_sensors = Mock(return_value=0)
    flow._handle_sensor_value_updates_from_enumeration = Mock()

    await flow._prepare_data_structures()

    flow._verify_pending_sensors.assert_called_once_with(
        new_pending, new_floats, flow.data[FLOAT_DICT]
    )
    flow._handle_new_sensors.assert_called_once_with(
        new_floats, new_switches, new_text, new_writable, new_pending
    )
    flow._handle_deleted_sensors.assert_called_once_with(
        new_floats, new_switches, new_text, new_writable, new_pending
    )
    flow._handle_sensor_value_updates_from_enumeration.assert_called_once_with(
        new_floats, new_switches, new_text, new_writable
    )


@pytest.mark.asyncio
async def test_prepare_data_structures_skips_discovery_when_only_update_values():
    """update_sensor_values=True (without enumerate) must not call _get_possible_endpoints_with_progress."""
    config = _make_runtime_config()
    flow = _make_flow(config, update_sensor_values=True, enumerate_new_endpoints=False)
    flow._get_possible_endpoints_with_progress = AsyncMock()
    flow._update_sensor_values = AsyncMock()

    await flow._prepare_data_structures()

    flow._get_possible_endpoints_with_progress.assert_not_called()


# ---------------------------------------------------------------------------
# _verify_pending_sensors
# ---------------------------------------------------------------------------


def test_verify_pending_sensors_no_overlap():
    """Pending sensor not in current floats stays pending; returns 0."""
    flow = EtaOptionsFlowHandler()
    current_floats = {"existing": _make_sensor(url="/existing")}
    new_pending = {"p1": _make_sensor(url="/p1")}
    new_floats = {}

    result = flow._verify_pending_sensors(new_pending, new_floats, current_floats)

    assert result == 0
    assert "p1" in new_pending
    assert "p1" not in new_floats


def test_verify_pending_sensors_overlap_removes_from_pending():
    """Pending sensor present in current floats is moved to new_floats; returns 1."""
    flow = EtaOptionsFlowHandler()
    promoted_sensor = _make_sensor(url="/promoted")
    current_floats = {"promoted": promoted_sensor}
    new_pending = {"promoted": _make_sensor(url="/promoted")}
    new_floats = {}

    result = flow._verify_pending_sensors(new_pending, new_floats, current_floats)

    assert result == 1
    assert "promoted" not in new_pending
    assert new_floats["promoted"] is promoted_sensor


def test_verify_pending_sensors_multiple_overlaps():
    """Two of three pending sensors overlap → both moved, returns 2."""
    flow = EtaOptionsFlowHandler()
    current_floats = {
        "p1": _make_sensor(url="/p1"),
        "p2": _make_sensor(url="/p2"),
    }
    new_pending = {
        "p1": _make_sensor(url="/p1"),
        "p2": _make_sensor(url="/p2"),
        "p3": _make_sensor(url="/p3"),
    }
    new_floats = {}

    result = flow._verify_pending_sensors(new_pending, new_floats, current_floats)

    assert result == 2
    assert "p1" not in new_pending
    assert "p2" not in new_pending
    assert "p3" in new_pending
    assert "p1" in new_floats
    assert "p2" in new_floats


# ---------------------------------------------------------------------------
# _handle_new_sensors
# ---------------------------------------------------------------------------


def _flow_with_data(overrides=None):
    flow = EtaOptionsFlowHandler()
    flow.data = {
        FLOAT_DICT: {},
        SWITCHES_DICT: {},
        TEXT_DICT: {},
        WRITABLE_DICT: {},
        PENDING_DICT: {},
        CHOSEN_FLOAT_SENSORS: [],
        CHOSEN_SWITCHES: [],
        CHOSEN_TEXT_SENSORS: [],
        CHOSEN_WRITABLE_SENSORS: [],
        CHOSEN_PENDING_SENSORS: [],
    }
    if overrides:
        flow.data.update(overrides)
    flow.unavailable_sensors = {}
    return flow


def test_handle_new_sensors_adds_new_float():
    """A float sensor absent from self.data is added; returns 1."""
    flow = _flow_with_data()
    new_sensor = _make_sensor(url="/f1")

    result = flow._handle_new_sensors({"f1": new_sensor}, {}, {}, {}, {})

    assert result == 1
    assert flow.data[FLOAT_DICT]["f1"] is new_sensor


def test_handle_new_sensors_skips_existing_float():
    """An already-known float sensor is not duplicated; returns 0."""
    existing = _make_sensor(url="/f1")
    flow = _flow_with_data({FLOAT_DICT: {"f1": existing}})

    result = flow._handle_new_sensors({"f1": _make_sensor(url="/f1")}, {}, {}, {}, {})

    assert result == 0
    assert flow.data[FLOAT_DICT]["f1"] is existing


def test_handle_new_sensors_one_per_category():
    """One new sensor in each of the five categories → returns 5."""
    flow = _flow_with_data()

    result = flow._handle_new_sensors(
        {"f1": _make_sensor(url="/f1")},
        {"sw1": _make_sensor(url="/sw1")},
        {"t1": _make_sensor(url="/t1")},
        {"w1": _make_sensor(url="/w1")},
        {"p1": _make_sensor(url="/p1")},
    )

    assert result == 5
    assert "f1" in flow.data[FLOAT_DICT]
    assert "sw1" in flow.data[SWITCHES_DICT]
    assert "t1" in flow.data[TEXT_DICT]
    assert "w1" in flow.data[WRITABLE_DICT]
    assert "p1" in flow.data[PENDING_DICT]


def test_handle_new_sensors_all_already_present():
    """No new sensors when all are already in self.data; returns 0."""
    flow = _flow_with_data(
        {
            FLOAT_DICT: {"f1": _make_sensor()},
            SWITCHES_DICT: {"sw1": _make_sensor()},
        }
    )

    result = flow._handle_new_sensors(
        {"f1": _make_sensor()}, {"sw1": _make_sensor()}, {}, {}, {}
    )

    assert result == 0


def test_handle_new_sensors_adds_pending():
    """A new pending sensor is added to PENDING_DICT; returns 1."""
    flow = _flow_with_data()

    result = flow._handle_new_sensors({}, {}, {}, {}, {"p1": _make_sensor(url="/p1")})

    assert result == 1
    assert "p1" in flow.data[PENDING_DICT]


# ---------------------------------------------------------------------------
# _handle_deleted_sensors
# ---------------------------------------------------------------------------


def test_handle_deleted_sensors_non_chosen_float_deleted():
    """Float absent from new discovery is removed; not stored as unavailable."""
    flow = _flow_with_data({FLOAT_DICT: {"gone": _make_sensor()}})

    result = flow._handle_deleted_sensors({}, {}, {}, {}, {})

    assert result == 1
    assert "gone" not in flow.data[FLOAT_DICT]
    assert "gone" not in flow.unavailable_sensors


def test_handle_deleted_sensors_chosen_float_tracked_as_unavailable():
    """Chosen float sensor deleted → moved to unavailable_sensors, removed from chosen list."""
    sensor = _make_sensor()
    flow = _flow_with_data(
        {
            FLOAT_DICT: {"gone": sensor},
            CHOSEN_FLOAT_SENSORS: ["gone"],
        }
    )

    result = flow._handle_deleted_sensors({}, {}, {}, {}, {})

    assert result == 1
    assert "gone" not in flow.data[FLOAT_DICT]
    assert "gone" not in flow.data[CHOSEN_FLOAT_SENSORS]
    assert flow.unavailable_sensors["gone"] is sensor


def test_handle_deleted_sensors_sensor_still_present():
    """Float still in new discovery is not deleted; returns 0."""
    sensor = _make_sensor(url="/s1")
    flow = _flow_with_data({FLOAT_DICT: {"s1": sensor}})

    result = flow._handle_deleted_sensors({"s1": sensor}, {}, {}, {}, {})

    assert result == 0
    assert "s1" in flow.data[FLOAT_DICT]


def test_handle_deleted_sensors_chosen_pending_cleaned_up():
    """Pending sensor absent from new discovery is removed from PENDING_DICT and chosen list."""
    flow = _flow_with_data(
        {
            PENDING_DICT: {"p1": _make_sensor(url="/p1")},
            CHOSEN_PENDING_SENSORS: ["p1"],
        }
    )

    result = flow._handle_deleted_sensors({}, {}, {}, {}, {})

    assert result == 1
    assert "p1" not in flow.data[PENDING_DICT]
    assert "p1" not in flow.data[CHOSEN_PENDING_SENSORS]


def test_handle_deleted_sensors_multiple_categories():
    """Deletions across float, switch, and text categories are counted together."""
    flow = _flow_with_data(
        {
            FLOAT_DICT: {"f1": _make_sensor()},
            SWITCHES_DICT: {"sw1": _make_sensor()},
            TEXT_DICT: {"t1": _make_sensor()},
        }
    )

    result = flow._handle_deleted_sensors({}, {}, {}, {}, {})

    assert result == 3
    assert flow.data[FLOAT_DICT] == {}
    assert flow.data[SWITCHES_DICT] == {}
    assert flow.data[TEXT_DICT] == {}


# ---------------------------------------------------------------------------
# _handle_sensor_value_updates_from_enumeration
# ---------------------------------------------------------------------------


def test_handle_sensor_value_updates_float_and_switch():
    """Float and switch values are updated from the new discovery dicts."""
    flow = _flow_with_data(
        {
            FLOAT_DICT: {"f1": _make_sensor(url="/f1", value=0.0)},
            SWITCHES_DICT: {"sw1": _make_sensor(url="/sw1", value=0.0)},
        }
    )

    flow._handle_sensor_value_updates_from_enumeration(
        {"f1": {**_make_sensor(url="/f1"), "value": 99.0}},
        {"sw1": {**_make_sensor(url="/sw1"), "value": 1.0}},
        {},
        {},
    )

    assert flow.data[FLOAT_DICT]["f1"]["value"] == 99.0
    assert flow.data[SWITCHES_DICT]["sw1"]["value"] == 1.0


def test_handle_sensor_value_updates_text_and_writable():
    """Text and writable values are updated from the new discovery dicts."""
    flow = _flow_with_data(
        {
            TEXT_DICT: {"t1": _make_sensor(url="/t1", value="old")},
            WRITABLE_DICT: {"w1": _make_sensor(url="/w1", value=0.0)},
        }
    )

    flow._handle_sensor_value_updates_from_enumeration(
        {},
        {},
        {"t1": {**_make_sensor(url="/t1"), "value": "new"}},
        {"w1": {**_make_sensor(url="/w1"), "value": 7.0}},
    )

    assert flow.data[TEXT_DICT]["t1"]["value"] == "new"
    assert flow.data[WRITABLE_DICT]["w1"]["value"] == 7.0


def test_handle_sensor_value_updates_exception_is_swallowed():
    """A KeyError (sensor missing from new dict) must not propagate."""
    flow = _flow_with_data(
        {
            FLOAT_DICT: {"f1": _make_sensor(url="/f1", value=0.0)},
        }
    )

    # new_float_sensors is missing "f1" → will raise KeyError inside the method.
    flow._handle_sensor_value_updates_from_enumeration({}, {}, {}, {})

    # No exception raised; f1 value is untouched.
    assert flow.data[FLOAT_DICT]["f1"]["value"] == 0.0


# ---------------------------------------------------------------------------
# _update_sensor_values
# ---------------------------------------------------------------------------


def _flow_for_update_sensor_values(overrides=None):
    flow = _flow_with_data(overrides)
    flow.hass = MagicMock()
    flow.data[CONF_HOST] = "192.168.0.25"
    flow.data[CONF_PORT] = 8080
    flow.data[MAX_PARALLEL_REQUESTS] = 5
    flow.data[UPDATE_INTERVAL] = DEFAULT_UPDATE_INTERVAL
    return flow


@pytest.mark.asyncio
async def test_update_sensor_values_updates_float_value():
    """Float sensor URL present in API response → value updated."""
    sensor = _make_sensor(url="/f1", value=0.0)
    flow = _flow_for_update_sensor_values({FLOAT_DICT: {"f1": sensor}})

    with (
        patch("custom_components.eta_webservices.config_flow.async_get_clientsession"),
        patch("custom_components.eta_webservices.config_flow.EtaAPI") as mock_cls,
    ):
        mock_eta = MagicMock()
        mock_eta.get_all_data = AsyncMock(return_value={"/f1": 55.0})
        mock_cls.return_value = mock_eta

        await flow._update_sensor_values()

    assert flow.data[FLOAT_DICT]["f1"]["value"] == 55.0
    assert flow._errors.get("base") != "value_update_error"


@pytest.mark.asyncio
async def test_update_sensor_values_updates_all_dicts():
    """Switch, text, and writable values are all updated from the API response."""
    flow = _flow_for_update_sensor_values(
        {
            SWITCHES_DICT: {"sw1": _make_sensor(url="/sw1", value=0.0)},
            TEXT_DICT: {"t1": _make_sensor(url="/t1")},
            WRITABLE_DICT: {"w1": _make_sensor(url="/w1", value=0.0)},
        }
    )

    with (
        patch("custom_components.eta_webservices.config_flow.async_get_clientsession"),
        patch("custom_components.eta_webservices.config_flow.EtaAPI") as mock_cls,
    ):
        mock_eta = MagicMock()
        mock_eta.get_all_data = AsyncMock(
            return_value={
                "/sw1": "on",
                "/t1": "new_text",
                "/w1": 7.0,
            }
        )
        mock_cls.return_value = mock_eta

        await flow._update_sensor_values()

    assert flow.data[SWITCHES_DICT]["sw1"]["value"] == "on"
    assert flow.data[TEXT_DICT]["t1"]["value"] == "new_text"
    assert flow.data[WRITABLE_DICT]["w1"]["value"] == 7.0


@pytest.mark.asyncio
async def test_update_sensor_values_sets_error_when_url_missing():
    """Float sensor URL absent from API response → value_update_error set."""
    sensor = _make_sensor(url="/f1", value=0.0)
    flow = _flow_for_update_sensor_values({FLOAT_DICT: {"f1": sensor}})

    with (
        patch("custom_components.eta_webservices.config_flow.async_get_clientsession"),
        patch("custom_components.eta_webservices.config_flow.EtaAPI") as mock_cls,
    ):
        mock_eta = MagicMock()
        mock_eta.get_all_data = AsyncMock(return_value={})  # URL absent
        mock_cls.return_value = mock_eta

        await flow._update_sensor_values()

    assert flow._errors.get("base") == "value_update_error"


@pytest.mark.asyncio
async def test_update_sensor_values_custom_unit_text_uses_force_string_handling():
    """Text sensor with a custom unit is requested with force_string_handling=True."""
    sensor = _make_sensor(url="/t1", unit=CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT)
    flow = _flow_for_update_sensor_values({TEXT_DICT: {"t1": sensor}})

    with (
        patch("custom_components.eta_webservices.config_flow.async_get_clientsession"),
        patch("custom_components.eta_webservices.config_flow.EtaAPI") as mock_cls,
    ):
        mock_eta = MagicMock()
        mock_eta.get_all_data = AsyncMock(return_value={"/t1": "480"})
        mock_cls.return_value = mock_eta

        await flow._update_sensor_values()

    called_sensor_list = mock_eta.get_all_data.call_args[0][0]
    assert called_sensor_list["/t1"].get("force_string_handling") is True


@pytest.mark.asyncio
async def test_update_sensor_values_standard_unit_text_does_not_force_string():
    """Text sensor with a standard unit is requested with force_string_handling=False."""
    sensor = _make_sensor(url="/t1", unit="°C")
    flow = _flow_for_update_sensor_values({TEXT_DICT: {"t1": sensor}})

    with (
        patch("custom_components.eta_webservices.config_flow.async_get_clientsession"),
        patch("custom_components.eta_webservices.config_flow.EtaAPI") as mock_cls,
    ):
        mock_eta = MagicMock()
        mock_eta.get_all_data = AsyncMock(return_value={"/t1": 32.0})
        mock_cls.return_value = mock_eta

        await flow._update_sensor_values()

    called_sensor_list = mock_eta.get_all_data.call_args[0][0]
    assert called_sensor_list["/t1"].get("force_string_handling") is False


# ---------------------------------------------------------------------------
# async_step_parallel_requests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_requests_step_shows_form_with_both_fields():
    """No user_input → shows form containing MAX_PARALLEL_REQUESTS and UPDATE_INTERVAL."""
    config = _make_runtime_config()
    flow = _make_flow(config)
    flow.async_show_form = Mock(return_value="form_result")

    result = await flow.async_step_parallel_requests(user_input=None)

    assert result == "form_result"
    schema_keys = {
        str(k) for k in flow.async_show_form.call_args.kwargs["data_schema"].schema
    }
    assert MAX_PARALLEL_REQUESTS in schema_keys
    assert UPDATE_INTERVAL in schema_keys


@pytest.mark.asyncio
async def test_parallel_requests_step_saves_update_interval():
    """User submits → update_interval integer is stored in the options entry data."""
    config = _make_runtime_config()
    flow = _make_flow(config)
    flow.async_create_entry = Mock(return_value="entry_result")

    result = await flow.async_step_parallel_requests(
        user_input={MAX_PARALLEL_REQUESTS: "5", UPDATE_INTERVAL: "30"}
    )

    assert result == "entry_result"
    saved_data = flow.async_create_entry.call_args.kwargs["data"]
    assert saved_data[UPDATE_INTERVAL] == 30


@pytest.mark.asyncio
async def test_parallel_requests_step_aborts_when_no_runtime_config():
    """_get_runtime_config returns None → step aborts immediately."""
    flow = EtaOptionsFlowHandler()
    flow._get_runtime_config = Mock(return_value=None)
    flow.async_abort = Mock(return_value="aborted")

    result = await flow.async_step_parallel_requests(user_input=None)

    assert result == "aborted"
