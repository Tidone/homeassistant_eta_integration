from abc import abstractmethod
import logging
from typing import Any, Generic, TypeVar, cast

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import Entity, generate_entity_id
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ETAEndpoint, EtaAPI
from .coordinator import ETAErrorUpdateCoordinator, EtaDataUpdateCoordinator
from .utils import create_device_info

_LOGGER = logging.getLogger(__name__)

_EntityT = TypeVar("_EntityT")


class EtaEntity(Entity):
    def __init__(
        self,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        entity_id_format: str,
    ) -> None:
        self._attr_name = endpoint_info["friendly_name"]
        self.session = async_get_clientsession(hass)
        self.host = config.get(CONF_HOST)
        self.port = config.get(CONF_PORT)
        self.uri = endpoint_info["url"]

        self.entity_id = generate_entity_id(entity_id_format, unique_id, hass=hass)
        self._attr_unique_id = unique_id


class EtaCoordinatorEntity(CoordinatorEntity, EtaEntity):
    """Base class for ETA entities that use a coordinator."""

    def __init__(
        self,
        coordinator: EtaDataUpdateCoordinator,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        entity_id_format: str,
        device_info,
    ):
        EtaEntity.__init__(
            self, config, hass, unique_id, endpoint_info, entity_id_format
        )
        CoordinatorEntity.__init__(self, coordinator)
        self._attr_device_info = device_info

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled by default."""
        return False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update attributes when the coordinator updates."""
        if self.unique_id in self.coordinator.data:
            self._attr_native_value = self.coordinator.data[self.unique_id]
            self.async_write_ha_state()


class EtaErrorEntity(CoordinatorEntity[ETAErrorUpdateCoordinator]):
    def __init__(
        self,
        coordinator: ETAErrorUpdateCoordinator,
        config: dict,
        hass: HomeAssistant,
        entity_id_format: str,
        unique_id_suffix: str,
    ) -> None:
        super().__init__(coordinator)

        host = config.get(CONF_HOST)
        port = config.get(CONF_PORT)

        self._attr_unique_id = (
            "eta_" + host.replace(".", "_") + "_" + str(port) + unique_id_suffix
        )

        self.entity_id = generate_entity_id(
            entity_id_format, self._attr_unique_id, hass=hass
        )

        self._attr_device_info = create_device_info(host, port)

    @abstractmethod
    def handle_data_updates(self, data) -> None:
        raise NotImplementedError

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update attributes when the coordinator updates."""
        self.handle_data_updates(self.coordinator.data)
        super()._handle_coordinator_update()
