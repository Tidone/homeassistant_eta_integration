"""Binary Sensor platform for the ETA sensor integration in Home Assistant."""

from __future__ import annotations

import logging

from homeassistant import config_entries
from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import generate_entity_id

from .const import DOMAIN, ERROR_UPDATE_COORDINATOR
from .coordinator import ETAErrorUpdateCoordinator
from .entity import EtaErrorEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    """Setup binary sensor."""
    config = hass.data[DOMAIN][config_entry.entry_id]

    error_coordinator = config[ERROR_UPDATE_COORDINATOR]

    sensors = [EtaErrorSensor(config, hass, error_coordinator)]
    async_add_entities(sensors, update_before_add=True)


class EtaErrorSensor(BinarySensorEntity, EtaErrorEntity):
    """Representation of a Binary sensor."""

    def __init__(  # noqa: D107
        self, config: dict, hass: HomeAssistant, coordinator: ETAErrorUpdateCoordinator
    ) -> None:
        _LOGGER.info("ETA Integration - init error sensor")

        super().__init__(coordinator, config, hass, ENTITY_ID_FORMAT, "_errors")

        self._attr_has_entity_name = True
        self._attr_translation_key = "state_sensor"

        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

        host = config.get(CONF_HOST, "")

        # replace the unique id and entity id to keep the entity backwards compatible
        self._attr_unique_id = "eta_" + host.replace(".", "_") + "_errors"
        self.entity_id = generate_entity_id(
            ENTITY_ID_FORMAT, self._attr_unique_id, hass=hass
        )

        self.handle_data_updates(self.coordinator.data)

    def handle_data_updates(self, data: list):  # noqa: D102
        self._attr_is_on = len(data) > 0
