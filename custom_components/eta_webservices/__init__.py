"""The ETA Sensors integration."""

import asyncio
import logging
from typing import Any

from homeassistant import config_entries, core
from homeassistant.const import Platform

from .const import (
    CHOSEN_FLOAT_SENSORS,
    CHOSEN_TEXT_SENSORS,
    CHOSEN_WRITABLE_SENSORS,
    CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
    DEFAULT_MAX_PARALLEL_REQUESTS,
    DOMAIN,
    ERROR_UPDATE_COORDINATOR,
    FLOAT_DICT,
    FORCE_LEGACY_MODE,
    MAX_PARALLEL_REQUESTS,
    REQUEST_SEMAPHORE,
    SENSOR_UPDATE_COORDINATOR,
    TEXT_DICT,
    WRITABLE_DICT,
    WRITABLE_UPDATE_COORDINATOR,
)
from .coordinator import (
    ETAErrorUpdateCoordinator,
    ETASensorUpdateCoordinator,
    ETAWritableUpdateCoordinator,
)
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Set up platform from a ConfigEntry."""
    hass.data.setdefault(DOMAIN, {})
    config = dict(entry.data)
    # Registers update listener to update config entry when options are updated.
    unsub_options_update_listener = entry.add_update_listener(options_update_listener)
    # Store a reference to the unsubscribe function to cleanup if an entry is unloaded.
    config["unsub_options_update_listener"] = unsub_options_update_listener

    # Merge the options with the config
    # The options are set if a user configures the integration after the initial set-up
    if entry.options:
        config.update(entry.options)

    config[MAX_PARALLEL_REQUESTS] = int(
        config.get(MAX_PARALLEL_REQUESTS, DEFAULT_MAX_PARALLEL_REQUESTS)
    )
    # Share one limiter across all API users of this config entry
    # so startup and periodic updates cannot overload slower ETA units.
    config[REQUEST_SEMAPHORE] = asyncio.Semaphore(config[MAX_PARALLEL_REQUESTS])

    error_coordinator = ETAErrorUpdateCoordinator(hass, config)
    sensor_coordinator = ETASensorUpdateCoordinator(hass, config)
    writable_coordinator = ETAWritableUpdateCoordinator(hass, config)
    config[ERROR_UPDATE_COORDINATOR] = error_coordinator
    config[SENSOR_UPDATE_COORDINATOR] = sensor_coordinator
    config[WRITABLE_UPDATE_COORDINATOR] = writable_coordinator

    # Prime coordinators once before entities are added to avoid initial update bursts.
    await error_coordinator.async_config_entry_first_refresh()
    await sensor_coordinator.async_config_entry_first_refresh()
    await writable_coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = config

    # Forward the setup to the sensor platform.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await async_setup_services(hass, entry)

    return True


async def async_migrate_entry(  # noqa: D103
    hass: core.HomeAssistant, config_entry: config_entries.ConfigEntry
):
    # Move all sensors with the custom CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT unit
    # from the list of float sensors to the list of text sensors
    # also make sure to move currently selected sensors
    def migrate_to_v6(new_data: dict[str, Any]):
        # Merge the options with the initial data to make sure we operate on the most recent data
        if config_entry.options:
            new_data.update(config_entry.options)

        chosen_custom_unit_sensors = [
            entry
            for entry in new_data[CHOSEN_FLOAT_SENSORS]
            if new_data[FLOAT_DICT][entry]["unit"] == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
        ]
        # remove sensors with custom units from the CHOSEN_FLOAT_SENSORS list
        new_data[CHOSEN_FLOAT_SENSORS] = [
            entry
            for entry in new_data[CHOSEN_FLOAT_SENSORS]
            if entry not in chosen_custom_unit_sensors
        ]
        # and add them to the CHOSEN_TEXT_SENSORS list instead
        new_data[CHOSEN_TEXT_SENSORS].extend(chosen_custom_unit_sensors)

        # now do the same with the FLOAT_DICT dict
        custom_unit_sensors = {
            k: v
            for k, v in new_data[FLOAT_DICT].items()
            if v.get("unit", "") == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
        }
        # remove sensors with custom units from the FLOAT_DICT
        new_data[FLOAT_DICT] = {
            k: v
            for k, v in new_data[FLOAT_DICT].items()
            if k not in custom_unit_sensors
        }
        # and add them to the TEXT_DICT instead
        new_data[TEXT_DICT].update(custom_unit_sensors)

    _LOGGER.debug("Migrating from version %s", config_entry.version)

    new_version = 6

    if config_entry.version == 1:
        new_data = config_entry.data.copy()

        new_data[WRITABLE_DICT] = []
        new_data[CHOSEN_WRITABLE_SENSORS] = []
        new_data[FORCE_LEGACY_MODE] = False

        migrate_to_v6(new_data)

        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            options={},
            version=new_version,
        )
    elif config_entry.version == 2:
        new_data = config_entry.data.copy()

        new_data[FORCE_LEGACY_MODE] = False

        migrate_to_v6(new_data)

        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            options={},
            version=new_version,
        )
    elif config_entry.version in (3, 4, 5):
        new_data = config_entry.data.copy()
        migrate_to_v6(new_data)
        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            options={},
            version=new_version,
        )
    else:
        _LOGGER.warning("No migration path to version %s found", new_version)
        return True

    _LOGGER.info("Migration to version %s successful", new_version)
    return True


async def options_update_listener(
    hass: core.HomeAssistant, config_entry: config_entries.ConfigEntry
):
    """Handle options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Remove options_update_listener.
        hass.data[DOMAIN][entry.entry_id]["unsub_options_update_listener"]()

        # Remove config entry from domain.
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
