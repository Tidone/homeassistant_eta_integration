"""Tests for eta_webservices/__init__.py migrations."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from copy import deepcopy

from custom_components.eta_webservices import async_migrate_entry
from custom_components.eta_webservices.const import (
    CHOSEN_FLOAT_SENSORS,
    CHOSEN_PENDING_SENSORS,
    CHOSEN_SWITCHES,
    CHOSEN_TEXT_SENSORS,
    CHOSEN_WRITABLE_SENSORS,
    CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
    CUSTOM_UNIT_TIMESLOT,
    CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE,
    FLOAT_DICT,
    FORCE_LEGACY_MODE,
    PENDING_DICT,
    TEXT_DICT,
    WRITABLE_DICT,
    SWITCHES_DICT,
)


@pytest.mark.asyncio
async def test_async_migrate_entry_v5_to_v6(load_fixture):
    """Test migration from version 5 to 6 with real fixture data.

    This test verifies:
    - Entries in FLOAT_DICT without custom unit stay in FLOAT_DICT
    - Entries in FLOAT_DICT with custom unit move to TEXT_DICT
    - Chosen entries in CHOSEN_FLOAT_SENSORS with custom unit move to CHOSEN_TEXT_SENSORS
    - All other dicts and lists remain unchanged
    """
    # Setup
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()

    # Create config entry for version 5
    config_entry = MagicMock(spec=ConfigEntry)
    config_entry.version = 5
    config_entry.entry_id = "test_entry_id"

    # Load real fixture data from extracted ETA config
    fixture_file = load_fixture("v5_config_data.json")
    original_data = deepcopy(fixture_file["data"])
    original_options = deepcopy(fixture_file.get("options", {}))

    # Map fixture keys to const keys in data
    original_data[FLOAT_DICT] = original_data.pop("FLOAT_DICT")
    original_data[TEXT_DICT] = original_data.pop("TEXT_DICT", {})
    original_data[SWITCHES_DICT] = original_data.pop("SWITCHES_DICT", {})
    original_data[CHOSEN_FLOAT_SENSORS] = original_data.pop("chosen_float_sensors")
    original_data[CHOSEN_TEXT_SENSORS] = original_data.pop("chosen_text_sensors")
    original_data[CHOSEN_WRITABLE_SENSORS] = original_data.pop(
        "chosen_writable_sensors"
    )
    original_data[WRITABLE_DICT] = original_data.pop("WRITABLE_DICT", {})
    original_data[FORCE_LEGACY_MODE] = original_data.pop("force_legacy_mode")

    # Map fixture keys to const keys in data
    original_options[FLOAT_DICT] = original_options.pop("FLOAT_DICT")
    original_options[TEXT_DICT] = original_options.pop("TEXT_DICT", {})
    original_options[SWITCHES_DICT] = original_options.pop("SWITCHES_DICT", {})
    original_options[CHOSEN_FLOAT_SENSORS] = original_options.pop(
        "chosen_float_sensors"
    )
    original_options[CHOSEN_TEXT_SENSORS] = original_options.pop("chosen_text_sensors")
    original_options[CHOSEN_WRITABLE_SENSORS] = original_options.pop(
        "chosen_writable_sensors"
    )
    original_options[WRITABLE_DICT] = original_options.pop("WRITABLE_DICT", {})
    original_options[FORCE_LEGACY_MODE] = original_options.pop("force_legacy_mode")

    # Use deepcopy to ensure original_data is not modified by config_entry.data
    config_entry.data = deepcopy(original_data)
    config_entry.options = deepcopy(original_options)

    # Mock async_update_entry
    hass.config_entries.async_update_entry = Mock()

    # Execute migration (patch entity registry used by migrate_to_v8)
    with patch("homeassistant.helpers.entity_registry.async_get") as mock_er_get, \
         patch("homeassistant.helpers.entity_registry.async_entries_for_config_entry", return_value=[]):
        mock_er_get.return_value = MagicMock()
        result = await async_migrate_entry(hass, config_entry)

    # Assertions
    assert result is True

    # Merge original options into original data for comparison
    original_data.update(original_options)

    # Get the data that was passed to async_update_entry
    hass.config_entries.async_update_entry.assert_called_once()
    call_kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    new_data = call_kwargs["data"]
    new_options = call_kwargs.get("options", {})

    # Verify version was bumped beyond the starting version
    assert call_kwargs["version"] > config_entry.version

    # ===== FLOAT_DICT Assertions =====
    # Count entries with custom unit in original FLOAT_DICT
    original_float_count = len(original_data[FLOAT_DICT])
    custom_unit_entries = [
        k
        for k, v in original_data[FLOAT_DICT].items()
        if v.get("unit") == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
    ]
    expected_float_count = original_float_count - len(custom_unit_entries)

    # Entries with standard units should remain in FLOAT_DICT
    assert len(new_data[FLOAT_DICT]) == expected_float_count, (
        f"Expected {expected_float_count} entries in FLOAT_DICT, got {len(new_data[FLOAT_DICT])}"
    )

    # None of the entries in FLOAT_DICT should have custom unit
    for entry_key, entry_data in new_data[FLOAT_DICT].items():
        assert entry_data.get("unit") != CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT, (
            f"Entry {entry_key} with custom unit should not be in FLOAT_DICT"
        )

    # Verify that all non-custom-unit entries from original FLOAT_DICT are still present
    for orig_key, orig_data in original_data[FLOAT_DICT].items():
        if orig_data.get("unit") != CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT:
            assert orig_key in new_data[FLOAT_DICT], (
                f"Non-custom-unit entry {orig_key} should still be in FLOAT_DICT"
            )

    # ===== TEXT_DICT Assertions =====
    # All original text entries should still exist
    for orig_key in original_data[TEXT_DICT]:
        assert orig_key in new_data[TEXT_DICT], (
            f"Original text entry {orig_key} should still be in TEXT_DICT"
        )

    # All custom unit entries from FLOAT_DICT should now be in TEXT_DICT
    for custom_unit_key in custom_unit_entries:
        assert custom_unit_key in new_data[TEXT_DICT], (
            f"Entry {custom_unit_key} with custom unit should be in TEXT_DICT"
        )
        assert (
            new_data[TEXT_DICT][custom_unit_key]["unit"]
            == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
        ), f"Entry {custom_unit_key} should have custom unit in TEXT_DICT"

    # TEXT_DICT should have grown by the number of entries migrated
    original_text_count = len(original_data[TEXT_DICT])
    new_text_count = len(new_data[TEXT_DICT])
    migrated_count = new_text_count - original_text_count
    assert migrated_count == len(custom_unit_entries), (
        f"TEXT_DICT should have {len(custom_unit_entries)} more entries after migration, but has {migrated_count} more"
    )

    # ===== CHOSEN_FLOAT_SENSORS Assertions =====
    # Entries without custom unit should remain
    original_chosen_float = original_data[CHOSEN_FLOAT_SENSORS].copy()
    expected_chosen_float = [
        k for k in original_chosen_float if k not in custom_unit_entries
    ]

    assert set(new_data[CHOSEN_FLOAT_SENSORS]) == set(expected_chosen_float), (
        f"CHOSEN_FLOAT_SENSORS mismatch. Expected {set(expected_chosen_float)}, got {set(new_data[CHOSEN_FLOAT_SENSORS])}"
    )

    # Entry with custom unit should be removed from CHOSEN_FLOAT_SENSORS
    for custom_unit_key in custom_unit_entries:
        assert custom_unit_key not in new_data[CHOSEN_FLOAT_SENSORS], (
            f"Custom unit entry {custom_unit_key} should be removed from CHOSEN_FLOAT_SENSORS"
        )

    # ===== CHOSEN_TEXT_SENSORS Assertions =====
    # Original entries should still be there
    original_chosen_text = original_data[CHOSEN_TEXT_SENSORS].copy()
    # Add custom unit entries that were in CHOSEN_FLOAT_SENSORS
    custom_unit_in_chosen = [
        k for k in custom_unit_entries if k in original_chosen_float
    ]
    expected_chosen_text = original_chosen_text + custom_unit_in_chosen

    assert set(new_data[CHOSEN_TEXT_SENSORS]) == set(expected_chosen_text), (
        f"CHOSEN_TEXT_SENSORS mismatch. Expected {set(expected_chosen_text)}, got {set(new_data[CHOSEN_TEXT_SENSORS])}"
    )

    # Entries with custom unit that were in CHOSEN_FLOAT_SENSORS should be added
    for custom_unit_key in custom_unit_entries:
        if custom_unit_key in original_chosen_float:
            assert custom_unit_key in new_data[CHOSEN_TEXT_SENSORS], (
                f"Custom unit entry {custom_unit_key} should be added to CHOSEN_TEXT_SENSORS"
            )

    # ===== Other Assertions =====
    # Other fields should remain unchanged
    assert new_data[CHOSEN_WRITABLE_SENSORS] == original_data[CHOSEN_WRITABLE_SENSORS]
    assert new_data[WRITABLE_DICT] == original_data[WRITABLE_DICT]
    assert new_data[FORCE_LEGACY_MODE] == original_data[FORCE_LEGACY_MODE]

    # Preserve additional config fields
    assert "host" in new_data
    assert "port" in new_data

    # ===== Options Merge Assertions =====
    # Verify that options were merged into the migrated data
    # The migrate_to_v6() function merges options into new_data before processing
    assert new_options == {}, "Options should be empty after migration"


@pytest.mark.asyncio
async def test_migration_v6_to_v7_adds_pending_fields():
    """Migration from v6 to v7 must add PENDING_DICT={} and CHOSEN_PENDING_SENSORS=[].

    Existing sensors must not be affected.
    """
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = Mock()

    config_entry = MagicMock(spec=ConfigEntry)
    config_entry.version = 6
    config_entry.entry_id = "test_entry_id"

    float_sensor_key = "eta_192_168_0_25__kessel_kesseltemperatur"
    float_sensor = {
        "url": "/120/10101/0/0/12080",
        "unit": "°C",
        "endpoint_type": "DEFAULT",
        "friendly_name": "Kessel > Kesseltemperatur",
        "value": 72.3,
        "valid_values": None,
    }

    config_entry.data = {
        FLOAT_DICT: {float_sensor_key: float_sensor},
        SWITCHES_DICT: {},
        TEXT_DICT: {},
        WRITABLE_DICT: {},
        CHOSEN_FLOAT_SENSORS: [float_sensor_key],
        CHOSEN_SWITCHES: [],
        CHOSEN_TEXT_SENSORS: [],
        CHOSEN_WRITABLE_SENSORS: [],
        FORCE_LEGACY_MODE: False,
        "host": "192.168.0.25",
        "port": "8080",
    }
    config_entry.options = {}

    with patch("homeassistant.helpers.entity_registry.async_get") as mock_er_get, \
         patch("homeassistant.helpers.entity_registry.async_entries_for_config_entry", return_value=[]):
        mock_er_get.return_value = MagicMock()
        result = await async_migrate_entry(hass, config_entry)

    assert result is True

    hass.config_entries.async_update_entry.assert_called_once()
    call_kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    new_data = call_kwargs["data"]

    # Version must be bumped beyond the starting version.
    assert call_kwargs["version"] > config_entry.version

    # New fields must be present and empty.
    assert PENDING_DICT in new_data, "PENDING_DICT must be added by migration"
    assert new_data[PENDING_DICT] == {}, "PENDING_DICT must be empty after migration"
    assert CHOSEN_PENDING_SENSORS in new_data, (
        "CHOSEN_PENDING_SENSORS must be added by migration"
    )
    assert new_data[CHOSEN_PENDING_SENSORS] == [], (
        "CHOSEN_PENDING_SENSORS must be empty after migration"
    )

    # Existing sensors must be untouched.
    assert float_sensor_key in new_data[FLOAT_DICT], (
        "Existing float sensor must survive migration"
    )
    assert new_data[CHOSEN_FLOAT_SENSORS] == [float_sensor_key], (
        "Existing chosen float sensors must survive migration"
    )


@pytest.mark.asyncio
async def test_migration_v6_to_v7_with_options():
    """Migration from v6 to v7 preserves options-overridden sensor lists."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = Mock()

    config_entry = MagicMock(spec=ConfigEntry)
    config_entry.version = 6
    config_entry.entry_id = "test_entry_id"

    float_sensor_key = "eta_192_168_0_25__kessel_kesseltemperatur"
    float_sensor = {
        "url": "/120/10101/0/0/12080",
        "unit": "°C",
        "endpoint_type": "DEFAULT",
        "friendly_name": "Kessel > Kesseltemperatur",
        "value": 72.3,
        "valid_values": None,
    }

    # Baseline data — minimal chosen lists
    config_entry.data = {
        FLOAT_DICT: {float_sensor_key: float_sensor},
        SWITCHES_DICT: {},
        TEXT_DICT: {},
        WRITABLE_DICT: {},
        CHOSEN_FLOAT_SENSORS: [],
        CHOSEN_SWITCHES: [],
        CHOSEN_TEXT_SENSORS: [],
        CHOSEN_WRITABLE_SENSORS: [],
        FORCE_LEGACY_MODE: False,
        "host": "192.168.0.25",
        "port": "8080",
    }
    # Options override chosen list
    config_entry.options = {
        FLOAT_DICT: {float_sensor_key: float_sensor},
        SWITCHES_DICT: {},
        TEXT_DICT: {},
        WRITABLE_DICT: {},
        CHOSEN_FLOAT_SENSORS: [float_sensor_key],
        CHOSEN_SWITCHES: [],
        CHOSEN_TEXT_SENSORS: [],
        CHOSEN_WRITABLE_SENSORS: [],
        FORCE_LEGACY_MODE: False,
    }

    with patch("homeassistant.helpers.entity_registry.async_get") as mock_er_get, \
         patch("homeassistant.helpers.entity_registry.async_entries_for_config_entry", return_value=[]):
        mock_er_get.return_value = MagicMock()
        result = await async_migrate_entry(hass, config_entry)
    assert result is True

    call_kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    new_data = call_kwargs["data"]
    new_options = call_kwargs.get("options", {})

    assert call_kwargs["version"] > config_entry.version
    assert PENDING_DICT in new_data
    assert new_data[PENDING_DICT] == {}
    assert CHOSEN_PENDING_SENSORS in new_data
    assert new_data[CHOSEN_PENDING_SENSORS] == []
    # The migration merges options into data, so the options-overridden
    # CHOSEN_FLOAT_SENSORS=[float_sensor_key] wins over data's empty list.
    assert new_data[CHOSEN_FLOAT_SENSORS] == [float_sensor_key]
    # The float sensor from data must still be present
    assert float_sensor_key in new_data[FLOAT_DICT]

    assert new_options == {}, "Options should be empty after migration"


@pytest.mark.asyncio
async def test_async_migrate_entry_v1_to_v7():
    """Test the full migration path from version 1 to 8.

    v1 data lacks WRITABLE_DICT, CHOSEN_WRITABLE_SENSORS, and FORCE_LEGACY_MODE.
    The migration must:
    - Add those three fields with their default values.
    - Move float sensors whose unit is CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT to
      TEXT_DICT and adjust CHOSEN_FLOAT/TEXT_SENSORS accordingly (migrate_to_v6).
    - Add PENDING_DICT and CHOSEN_PENDING_SENSORS (migrate_to_v7).
    - Store the result in a single flat data dict, clear options, and set version=8.
    """
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()

    config_entry = MagicMock(spec=ConfigEntry)
    config_entry.version = 1
    config_entry.entry_id = "test_entry_id"
    config_entry.options = {}
    config_entry.data = {
        "host": "192.168.0.25",
        "port": 8080,
        FLOAT_DICT: {
            "sensor_normal": {
                "unit": "%",
                "value": 42.0,
                "url": "/uri/normal",
                "endpoint_type": "DEFAULT",
                "friendly_name": "Normal sensor",
                "valid_values": None,
            },
            "sensor_custom": {
                "unit": CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
                "value": 480.0,
                "url": "/uri/custom",
                "endpoint_type": "DEFAULT",
                "friendly_name": "Custom unit sensor",
                "valid_values": None,
            },
        },
        TEXT_DICT: {},
        CHOSEN_FLOAT_SENSORS: ["sensor_normal", "sensor_custom"],
        CHOSEN_TEXT_SENSORS: [],
    }

    hass.config_entries.async_update_entry = Mock()

    with patch("homeassistant.helpers.entity_registry.async_get") as mock_er_get, \
         patch("homeassistant.helpers.entity_registry.async_entries_for_config_entry", return_value=[]):
        mock_er_get.return_value = MagicMock()
        result = await async_migrate_entry(hass, config_entry)

    assert result is True

    hass.config_entries.async_update_entry.assert_called_once()
    call_kwargs = hass.config_entries.async_update_entry.call_args.kwargs

    assert call_kwargs["version"] > config_entry.version
    assert call_kwargs.get("options") == {}

    new_data = call_kwargs["data"]

    # Fields added by the v1-specific step.
    assert new_data[WRITABLE_DICT] == []
    assert new_data[CHOSEN_WRITABLE_SENSORS] == []
    assert new_data[FORCE_LEGACY_MODE] is False

    # Fields added by migrate_to_v7.
    assert new_data[PENDING_DICT] == {}
    assert new_data[CHOSEN_PENDING_SENSORS] == []

    # migrate_to_v6: custom-unit sensor must leave FLOAT_DICT.
    assert "sensor_normal" in new_data[FLOAT_DICT]
    assert "sensor_custom" not in new_data[FLOAT_DICT]

    # migrate_to_v6: custom-unit sensor must arrive in TEXT_DICT.
    assert "sensor_custom" in new_data[TEXT_DICT]
    assert (
        new_data[TEXT_DICT]["sensor_custom"]["unit"]
        == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
    )

    # migrate_to_v6: CHOSEN_FLOAT_SENSORS updated, CHOSEN_TEXT_SENSORS updated.
    assert "sensor_normal" in new_data[CHOSEN_FLOAT_SENSORS]
    assert "sensor_custom" not in new_data[CHOSEN_FLOAT_SENSORS]
    assert "sensor_custom" in new_data[CHOSEN_TEXT_SENSORS]

    # Connection fields must be preserved.
    assert new_data["host"] == "192.168.0.25"
    assert new_data["port"] == 8080


def _make_v7_config_entry(text_dict=None, chosen_text=None, writable_dict=None, chosen_writable=None):
    """Build a minimal v7 config entry for migration testing."""
    config_entry = MagicMock(spec=ConfigEntry)
    config_entry.version = 7
    config_entry.entry_id = "test_entry_id"
    config_entry.options = {}
    config_entry.data = {
        FLOAT_DICT: {},
        SWITCHES_DICT: {},
        TEXT_DICT: text_dict or {},
        WRITABLE_DICT: writable_dict or {},
        CHOSEN_FLOAT_SENSORS: [],
        CHOSEN_SWITCHES: [],
        CHOSEN_TEXT_SENSORS: chosen_text or [],
        CHOSEN_WRITABLE_SENSORS: chosen_writable or [],
        FORCE_LEGACY_MODE: False,
        PENDING_DICT: {},
        CHOSEN_PENDING_SENSORS: [],
        "host": "192.168.0.25",
        "port": 8080,
    }
    return config_entry


def _make_entity_entry(unique_id, entity_id):
    entry = MagicMock()
    entry.unique_id = unique_id
    entry.entity_id = entity_id
    return entry


@pytest.mark.asyncio
async def test_migration_v7_to_v8_disables_timeslot_with_writable_counterpart():
    """migrate_to_v8 must disable text-side timeslot entities that have a writable counterpart.

    When a sensor key like 'ts_key' appears in CHOSEN_TEXT_SENSORS with a timeslot unit
    AND 'ts_key_writable' appears in CHOSEN_WRITABLE_SENSORS, the corresponding entity
    registry entry for 'ts_key' must be disabled by the integration.
    Non-timeslot and timeslot-without-writable entries must be left untouched.
    """
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = Mock()

    timeslot_key = "ts_monday"
    timeslot_plus_temp_key = "ts_tuesday"
    standalone_timeslot_key = "ts_wednesday"  # no writable counterpart → must NOT be disabled
    regular_text_key = "text_status"

    text_dict = {
        timeslot_key: {"unit": CUSTOM_UNIT_TIMESLOT, "url": "/u/1", "endpoint_type": "DEFAULT", "friendly_name": "Mon", "value": "", "valid_values": None},
        timeslot_plus_temp_key: {"unit": CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE, "url": "/u/2", "endpoint_type": "DEFAULT", "friendly_name": "Tue", "value": "", "valid_values": None},
        standalone_timeslot_key: {"unit": CUSTOM_UNIT_TIMESLOT, "url": "/u/3", "endpoint_type": "DEFAULT", "friendly_name": "Wed", "value": "", "valid_values": None},
        regular_text_key: {"unit": "", "url": "/u/4", "endpoint_type": "TEXT", "friendly_name": "Status", "value": "on", "valid_values": None},
    }
    writable_dict = {
        timeslot_key + "_writable": {"unit": CUSTOM_UNIT_TIMESLOT, "url": "/u/1", "endpoint_type": "DEFAULT", "friendly_name": "Mon", "value": "", "valid_values": {}},
        timeslot_plus_temp_key + "_writable": {"unit": CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE, "url": "/u/2", "endpoint_type": "DEFAULT", "friendly_name": "Tue", "value": "", "valid_values": {}},
    }
    chosen_text = [timeslot_key, timeslot_plus_temp_key, standalone_timeslot_key, regular_text_key]
    chosen_writable = [timeslot_key + "_writable", timeslot_plus_temp_key + "_writable"]

    config_entry = _make_v7_config_entry(text_dict, chosen_text, writable_dict, chosen_writable)

    # Simulate two existing entity registry entries for the to-be-disabled sensors.
    entity_entries = [
        _make_entity_entry(timeslot_key, "sensor.ts_monday"),
        _make_entity_entry(timeslot_plus_temp_key, "sensor.ts_tuesday"),
        _make_entity_entry(standalone_timeslot_key, "sensor.ts_wednesday"),
        _make_entity_entry(regular_text_key, "sensor.text_status"),
    ]

    mock_registry = MagicMock()
    with patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_registry), \
         patch("homeassistant.helpers.entity_registry.async_entries_for_config_entry", return_value=entity_entries):
        result = await async_migrate_entry(hass, config_entry)

    assert result is True
    assert hass.config_entries.async_update_entry.call_args.kwargs["version"] > config_entry.version

    # Only the two entries with writable counterparts must have been disabled.
    disabled_entity_ids = {
        call.kwargs["entity_id"] if "entity_id" in call.kwargs else call.args[0]
        for call in mock_registry.async_update_entity.call_args_list
    }
    assert "sensor.ts_monday" in disabled_entity_ids
    assert "sensor.ts_tuesday" in disabled_entity_ids
    assert "sensor.ts_wednesday" not in disabled_entity_ids
    assert "sensor.text_status" not in disabled_entity_ids
    assert mock_registry.async_update_entity.call_count == 2


@pytest.mark.asyncio
async def test_migration_v7_to_v8_no_entities_to_disable():
    """migrate_to_v8 must not touch the entity registry when there are no timeslot
    sensors with writable counterparts — including when the registry is empty."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = Mock()

    # Only a plain float sensor — no timeslot sensors at all.
    config_entry = _make_v7_config_entry(
        chosen_text=["regular_text"],
        text_dict={"regular_text": {"unit": "", "url": "/u/1", "endpoint_type": "TEXT", "friendly_name": "S", "value": "x", "valid_values": None}},
    )

    mock_registry = MagicMock()
    with patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_registry), \
         patch("homeassistant.helpers.entity_registry.async_entries_for_config_entry", return_value=[]):
        result = await async_migrate_entry(hass, config_entry)

    assert result is True
    mock_registry.async_update_entity.assert_not_called()


@pytest.mark.asyncio
async def test_migration_v7_to_v8_timeslot_without_writable_not_disabled():
    """Timeslot text sensors that have no writable counterpart must not be disabled."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = Mock()

    timeslot_key = "ts_standalone"
    config_entry = _make_v7_config_entry(
        text_dict={timeslot_key: {"unit": CUSTOM_UNIT_TIMESLOT, "url": "/u/1", "endpoint_type": "DEFAULT", "friendly_name": "S", "value": "", "valid_values": None}},
        chosen_text=[timeslot_key],
        chosen_writable=[],  # no writable counterpart
    )

    entity_entries = [_make_entity_entry(timeslot_key, "sensor.ts_standalone")]
    mock_registry = MagicMock()
    with patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_registry), \
         patch("homeassistant.helpers.entity_registry.async_entries_for_config_entry", return_value=entity_entries):
        result = await async_migrate_entry(hass, config_entry)

    assert result is True
    mock_registry.async_update_entity.assert_not_called()
