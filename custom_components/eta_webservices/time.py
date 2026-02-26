"""Time platform for the ETA sensor integration in Home Assistant."""

from __future__ import annotations

from datetime import time, timedelta
import logging

from homeassistant import config_entries
from homeassistant.components.time import ENTITY_ID_FORMAT, TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api import ETAEndpoint
from .const import (
    CHOSEN_WRITABLE_SENSORS,
    CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
    DOMAIN,
    WRITABLE_DICT,
    WRITABLE_UPDATE_COORDINATOR,
)
from .coordinator import ETAWritableUpdateCoordinator
from .entity import EtaWritableSensorEntity

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=1)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    """Setup time sensors from a config entry created in the integrations UI."""
    config = hass.data[DOMAIN][config_entry.entry_id]

    coordinator = config[WRITABLE_UPDATE_COORDINATOR]

    chosen_entities = config[CHOSEN_WRITABLE_SENSORS]
    time_sensors = [
        EtaTime(config, hass, entity, config[WRITABLE_DICT][entity], coordinator)
        for entity in chosen_entities
        if config[WRITABLE_DICT][entity]["unit"] == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
    ]
    async_add_entities(time_sensors, update_before_add=True)


class EtaTime(TimeEntity, EtaWritableSensorEntity):
    """Representation of a Time Sensor."""

    def __init__(  # noqa: D107
        self,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        coordinator: ETAWritableUpdateCoordinator,
    ) -> None:
        _LOGGER.info("ETA Integration - init time sensor")

        super().__init__(
            coordinator, config, hass, unique_id, endpoint_info, ENTITY_ID_FORMAT
        )

        # set an initial value to avoid errors. This will be overwritten by the coordinator immediately after initialization.
        self._attr_native_value = time(hour=19)
        self._attr_should_poll = True

    def handle_data_updates(self, data: float) -> None:
        """Calculate the actual time from the minutes since midnight and set the entity's value."""
        total_minutes = int(data)
        hours = total_minutes // 60
        minutes = total_minutes % 60

        self._attr_native_value = time(hour=hours, minute=minutes)

    async def async_set_value(self, value: time):
        """Calculate the minutes since midnight and write the value to the endpoint."""
        total_minutes = value.hour * 60 + value.minute
        if total_minutes >= 60 * 24:
            raise HomeAssistantError("Invalid time: Must be between 00:00 and 23:59")
        eta_client = self._create_eta_client()
        success = await eta_client.write_endpoint(self.uri, total_minutes)
        if not success:
            raise HomeAssistantError("Could not write value, see log for details")
        await self.coordinator.async_refresh()
