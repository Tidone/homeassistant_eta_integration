"""Common entity definitions for the ETA sensor integration."""

from abc import abstractmethod
from typing import Generic, TypeVar, cast

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import Entity, generate_entity_id
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import EtaAPI, ETAEndpoint
from .const import DEFAULT_MAX_PARALLEL_REQUESTS, MAX_PARALLEL_REQUESTS, REQUEST_SEMAPHORE
from .coordinator import (
    ETAErrorUpdateCoordinator,
    ETASensorUpdateCoordinator,
    ETAWritableUpdateCoordinator,
)
from .utils import create_device_info

_EntityT = TypeVar("_EntityT")


class EtaEntity(Entity):
    """Common entity definition for all ETA entities."""

    def __init__(  # noqa: D107
        self,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        entity_id_format: str,
    ) -> None:
        self._attr_name = endpoint_info["friendly_name"]
        self.session = async_get_clientsession(hass)
        self.host = config.get(CONF_HOST, "")
        self.port = config.get(CONF_PORT, "")
        self.uri = endpoint_info["url"]
        self.max_parallel_requests = int(
            config.get(MAX_PARALLEL_REQUESTS, DEFAULT_MAX_PARALLEL_REQUESTS)
        )
        self.request_semaphore = config.get(REQUEST_SEMAPHORE)

        self._attr_device_info = create_device_info(self.host, self.port)
        self.entity_id = generate_entity_id(entity_id_format, unique_id, hass=hass)
        self._attr_unique_id = unique_id

    def _create_eta_client(self) -> EtaAPI:
        # Reuse configured concurrency settings for all entity-level write operations.
        return EtaAPI(
            self.session,
            self.host,
            self.port,
            max_concurrent_requests=self.max_parallel_requests,
            request_semaphore=self.request_semaphore,
        )


class EtaCoordinatedSensorEntity(
    EtaEntity, CoordinatorEntity[ETASensorUpdateCoordinator], Generic[_EntityT]
):
    """Common coordinated sensor entity definition for normal ETA sensors."""

    def __init__(  # noqa: D107
        self,
        coordinator: ETASensorUpdateCoordinator,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        entity_id_format: str,
    ) -> None:
        EtaEntity.__init__(
            self, config, hass, unique_id, endpoint_info, entity_id_format
        )
        CoordinatorEntity.__init__(self, coordinator)  # pyright: ignore[reportArgumentType]

        self._attr_should_poll = False
        self.handle_data_updates(
            cast(
                _EntityT,
                coordinator.data.get(
                    self.unique_id, endpoint_info["value"]
                ),  # pyright: ignore[reportAttributeAccessIssue]
            )
        )

    @abstractmethod
    def handle_data_updates(self, data: _EntityT) -> None:  # noqa: D102
        raise NotImplementedError

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update attributes when the coordinator updates."""
        if self.unique_id in self.coordinator.data:
            data = self.coordinator.data[self.unique_id]
            self.handle_data_updates(cast(_EntityT, data))
        super()._handle_coordinator_update()


class EtaWritableSensorEntity(
    EtaEntity, CoordinatorEntity[ETAWritableUpdateCoordinator]
):
    """Common sensor entity definition for all ETA sensors."""

    def __init__(  # noqa: D107
        self,
        coordinator: ETAWritableUpdateCoordinator,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        entity_id_format: str,
    ) -> None:
        EtaEntity.__init__(
            self, config, hass, unique_id, endpoint_info, entity_id_format
        )
        CoordinatorEntity.__init__(self, coordinator)  # pyright: ignore[reportArgumentType]

        self.handle_data_updates(float(coordinator.data[self.uri]))

    @abstractmethod
    def handle_data_updates(self, data: float) -> None:  # noqa: D102
        raise NotImplementedError

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update attributes when the coordinator updates."""
        data = self.coordinator.data.get(self.uri, None)
        if data is not None:
            self.handle_data_updates(float(data))
        super()._handle_coordinator_update()


class EtaErrorEntity(CoordinatorEntity[ETAErrorUpdateCoordinator]):
    """Entity definition for all ETA error sensors."""

    def __init__(  # noqa: D107
        self,
        coordinator: ETAErrorUpdateCoordinator,
        config: dict,
        hass: HomeAssistant,
        entity_id_format: str,
        unique_id_suffix: str,
    ) -> None:
        super().__init__(coordinator)

        host = config.get(CONF_HOST, "")
        port = config.get(CONF_PORT, "")

        self._attr_unique_id = (
            "eta_" + host.replace(".", "_") + "_" + str(port) + unique_id_suffix
        )

        self.entity_id = generate_entity_id(
            entity_id_format, self._attr_unique_id, hass=hass
        )

        self._attr_device_info = create_device_info(host, port)

    @abstractmethod
    def handle_data_updates(self, data) -> None:  # noqa: D102
        raise NotImplementedError

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update attributes when the coordinator updates."""
        self.handle_data_updates(self.coordinator.data)
        super()._handle_coordinator_update()
