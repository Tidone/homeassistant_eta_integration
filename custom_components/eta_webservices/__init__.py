import logging
from homeassistant import config_entries, core
from homeassistant.const import Platform

from .const import DOMAIN, ERROR_UPDATE_COORDINATOR, WRITABLE_UPDATE_COORDINATOR
from .coordinator import ETAErrorUpdateCoordinator, ETAWritableUpdateCoordinator
from .services import async_setup_services
from .const import (
    WRITABLE_DICT,
    CHOSEN_WRITABLE_SENSORS,
    FORCE_LEGACY_MODE,
)

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

    if entry.options:
        config.update(entry.options)

    error_coordinator = ETAErrorUpdateCoordinator(hass, config)
    writable_coordinator = ETAWritableUpdateCoordinator(hass, config)
    config[ERROR_UPDATE_COORDINATOR] = error_coordinator
    config[WRITABLE_UPDATE_COORDINATOR] = writable_coordinator

    await error_coordinator.async_config_entry_first_refresh()
    await writable_coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = config

    # Forward the setup to the sensor platform.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await async_setup_services(hass, entry)

    return True


async def async_migrate_entry(
    hass: core.HomeAssistant, config_entry: config_entries.ConfigEntry
):
    _LOGGER.debug("Migrating from version %s", config_entry.version)
    if config_entry.version == 1:
        new_data = config_entry.data.copy()

        new_data[WRITABLE_DICT] = []
        new_data[CHOSEN_WRITABLE_SENSORS] = []
        new_data[FORCE_LEGACY_MODE] = False

        hass.config_entries.async_update_entry(config_entry, data=new_data, version=5)
    elif config_entry.version == 2:
        new_data = config_entry.data.copy()

        new_data[FORCE_LEGACY_MODE] = False

        hass.config_entries.async_update_entry(config_entry, data=new_data, version=5)
    elif config_entry.version in (3, 4):
        new_data = config_entry.data.copy()
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=5)

    _LOGGER.info("Migration to version %s successful", config_entry.version)
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
