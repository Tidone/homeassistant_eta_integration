"""Binary Sensor platform for the ETA sensor integration in Home Assistant."""

from __future__ import annotations

import logging

from homeassistant import config_entries
from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import CONF_HOST, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ETAEndpoint
from .const import (
    CHOSEN_SWITCHES,
    DOMAIN,
    ERROR_UPDATE_COORDINATOR,
    SENSOR_UPDATE_COORDINATOR,
    SWITCHES_DICT,
)
from .coordinator import ETAErrorUpdateCoordinator, ETASensorUpdateCoordinator
from .entity import EtaEntity, EtaErrorEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    """Setup binary sensor."""
    config = hass.data[DOMAIN][config_entry.entry_id]

    error_coordinator = config[ERROR_UPDATE_COORDINATOR]
    coordinator = config[SENSOR_UPDATE_COORDINATOR]

    chosen_entities = config[CHOSEN_SWITCHES]

    sensors: list[BinarySensorEntity] = [
        EtaErrorSensor(config, hass, error_coordinator)
    ]
    sensors.extend(
        [
            EtaBinarySensor(
                config, hass, entity, config[SWITCHES_DICT][entity], coordinator
            )
            for entity in chosen_entities
            if not config[SWITCHES_DICT][entity].get("is_writable", True)
        ]
    )
    async_add_entities(sensors, update_before_add=False)


class EtaErrorSensor(BinarySensorEntity, EtaErrorEntity):
    """Representation of a Binary sensor."""

    def __init__(  # noqa: D107
        self, config: dict, hass: HomeAssistant, coordinator: ETAErrorUpdateCoordinator
    ) -> None:
        _LOGGER.debug("ETA Integration - init error sensor")

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


class EtaBinarySensor(
    EtaEntity, BinarySensorEntity, CoordinatorEntity[ETASensorUpdateCoordinator]
):
    """Representation of a Switch."""

    def __init__(  # noqa: D107
        self,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        coordinator: ETASensorUpdateCoordinator,
    ) -> None:
        _LOGGER.debug("ETA Integration - init switch")

        EtaEntity.__init__(
            self, config, hass, unique_id, endpoint_info, ENTITY_ID_FORMAT
        )
        CoordinatorEntity.__init__(self, coordinator)  # pyright: ignore[reportArgumentType]

        self._attr_icon = "mdi:power"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        data = self.coordinator.data.get(self.uri)
        self._attr_is_on = bool(data) if data is not None else None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update attributes when the coordinator updates."""
        data = self.coordinator.data.get(self.uri)
        if self.coordinator.data:
            self._attr_is_on = bool(data) if data is not None else None
        super()._handle_coordinator_update()
