"""Tests for eta_webservices/__init__.py migrations."""

import pytest
from unittest.mock import Mock, MagicMock
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from copy import deepcopy

from custom_components.eta_webservices import async_migrate_entry
from custom_components.eta_webservices.const import (
    CHOSEN_FLOAT_SENSORS,
    CHOSEN_TEXT_SENSORS,
    CHOSEN_WRITABLE_SENSORS,
    CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
    DOMAIN,
    FLOAT_DICT,
    FORCE_LEGACY_MODE,
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
    original_data[CHOSEN_WRITABLE_SENSORS] = original_data.pop("chosen_writable_sensors")
    original_data[WRITABLE_DICT] = original_data.pop("WRITABLE_DICT", {})
    original_data[FORCE_LEGACY_MODE] = original_data.pop("force_legacy_mode")

    # Map fixture keys to const keys in data
    original_options[FLOAT_DICT] = original_options.pop("FLOAT_DICT")
    original_options[TEXT_DICT] = original_options.pop("TEXT_DICT", {})
    original_options[SWITCHES_DICT] = original_options.pop("SWITCHES_DICT", {})
    original_options[CHOSEN_FLOAT_SENSORS] = original_options.pop("chosen_float_sensors")
    original_options[CHOSEN_TEXT_SENSORS] = original_options.pop("chosen_text_sensors")
    original_options[CHOSEN_WRITABLE_SENSORS] = original_options.pop("chosen_writable_sensors")
    original_options[WRITABLE_DICT] = original_options.pop("WRITABLE_DICT", {})
    original_options[FORCE_LEGACY_MODE] = original_options.pop("force_legacy_mode")
    
    # Use deepcopy to ensure original_data is not modified by config_entry.data
    config_entry.data = deepcopy(original_data)
    config_entry.options = deepcopy(original_options)
    
    # Mock async_update_entry
    hass.config_entries.async_update_entry = Mock()
    
    # Execute migration
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
    
    # Verify version was updated
    assert call_kwargs["version"] == 6
    
    # ===== FLOAT_DICT Assertions =====
    # Count entries with custom unit in original FLOAT_DICT
    original_float_count = len(original_data[FLOAT_DICT])
    custom_unit_entries = [
        k for k, v in original_data[FLOAT_DICT].items()
        if v.get("unit") == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
    ]
    expected_float_count = original_float_count - len(custom_unit_entries)
    
    # Entries with standard units should remain in FLOAT_DICT
    assert len(new_data[FLOAT_DICT]) == expected_float_count, \
        f"Expected {expected_float_count} entries in FLOAT_DICT, got {len(new_data[FLOAT_DICT])}"
    
    # None of the entries in FLOAT_DICT should have custom unit
    for entry_key, entry_data in new_data[FLOAT_DICT].items():
        assert entry_data.get("unit") != CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT, \
            f"Entry {entry_key} with custom unit should not be in FLOAT_DICT"
    
    # Verify that all non-custom-unit entries from original FLOAT_DICT are still present
    for orig_key, orig_data in original_data[FLOAT_DICT].items():
        if orig_data.get("unit") != CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT:
            assert orig_key in new_data[FLOAT_DICT], \
                f"Non-custom-unit entry {orig_key} should still be in FLOAT_DICT"
    
    # ===== TEXT_DICT Assertions =====
    # All original text entries should still exist
    for orig_key in original_data[TEXT_DICT]:
        assert orig_key in new_data[TEXT_DICT], \
            f"Original text entry {orig_key} should still be in TEXT_DICT"
    
    # All custom unit entries from FLOAT_DICT should now be in TEXT_DICT
    for custom_unit_key in custom_unit_entries:
        assert custom_unit_key in new_data[TEXT_DICT], \
            f"Entry {custom_unit_key} with custom unit should be in TEXT_DICT"
        assert new_data[TEXT_DICT][custom_unit_key]["unit"] == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT, \
            f"Entry {custom_unit_key} should have custom unit in TEXT_DICT"
    
    # TEXT_DICT should have grown by the number of entries migrated
    original_text_count = len(original_data[TEXT_DICT])
    new_text_count = len(new_data[TEXT_DICT])
    migrated_count = new_text_count - original_text_count
    assert migrated_count == len(custom_unit_entries), \
        f"TEXT_DICT should have {len(custom_unit_entries)} more entries after migration, but has {migrated_count} more"
    
    # ===== CHOSEN_FLOAT_SENSORS Assertions =====
    # Entries without custom unit should remain
    original_chosen_float = original_data[CHOSEN_FLOAT_SENSORS].copy()
    expected_chosen_float = [k for k in original_chosen_float if k not in custom_unit_entries]
    
    assert set(new_data[CHOSEN_FLOAT_SENSORS]) == set(expected_chosen_float), \
        f"CHOSEN_FLOAT_SENSORS mismatch. Expected {set(expected_chosen_float)}, got {set(new_data[CHOSEN_FLOAT_SENSORS])}"
    
    # Entry with custom unit should be removed from CHOSEN_FLOAT_SENSORS
    for custom_unit_key in custom_unit_entries:
        assert custom_unit_key not in new_data[CHOSEN_FLOAT_SENSORS], \
            f"Custom unit entry {custom_unit_key} should be removed from CHOSEN_FLOAT_SENSORS"
    
    # ===== CHOSEN_TEXT_SENSORS Assertions =====
    # Original entries should still be there
    original_chosen_text = original_data[CHOSEN_TEXT_SENSORS].copy()
    # Add custom unit entries that were in CHOSEN_FLOAT_SENSORS
    custom_unit_in_chosen = [k for k in custom_unit_entries if k in original_chosen_float]
    expected_chosen_text = original_chosen_text + custom_unit_in_chosen
    
    assert set(new_data[CHOSEN_TEXT_SENSORS]) == set(expected_chosen_text), \
        f"CHOSEN_TEXT_SENSORS mismatch. Expected {set(expected_chosen_text)}, got {set(new_data[CHOSEN_TEXT_SENSORS])}"
    
    # Entries with custom unit that were in CHOSEN_FLOAT_SENSORS should be added
    for custom_unit_key in custom_unit_entries:
        if custom_unit_key in original_chosen_float:
            assert custom_unit_key in new_data[CHOSEN_TEXT_SENSORS], \
                f"Custom unit entry {custom_unit_key} should be added to CHOSEN_TEXT_SENSORS"
    
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
