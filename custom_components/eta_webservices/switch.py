"""Switch platform for the ETA sensor integration in Home Assistant."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant import config_entries
from homeassistant.components.switch import ENTITY_ID_FORMAT, SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ETAEndpoint
from .const import CHOSEN_SWITCHES, DOMAIN, SENSOR_UPDATE_COORDINATOR, SWITCHES_DICT
from .coordinator import ETASensorUpdateCoordinator
from .entity import EtaEntity

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=1)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    """Setup switches from a config entry created in the integrations UI."""
    config = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = config[SENSOR_UPDATE_COORDINATOR]

    chosen_entities = config[CHOSEN_SWITCHES]
    switches = [
        EtaSwitch(config, hass, entity, config[SWITCHES_DICT][entity], coordinator)
        for entity in chosen_entities
    ]
    async_add_entities(switches, update_before_add=False)


class EtaSwitch(EtaEntity, SwitchEntity, CoordinatorEntity[ETASensorUpdateCoordinator]):
    """Representation of a Switch."""

    def __init__(  # noqa: D107
        self,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        coordinator: ETASensorUpdateCoordinator,
    ) -> None:
        _LOGGER.info("ETA Integration - init switch")

        EtaEntity.__init__(
            self, config, hass, unique_id, endpoint_info, ENTITY_ID_FORMAT
        )
        CoordinatorEntity.__init__(self, coordinator)  # pyright: ignore[reportArgumentType]

        self._attr_icon = "mdi:power"

        self.on_value = endpoint_info["valid_values"].get("on_value", 1803)  # pyright: ignore[reportOptionalMemberAccess]
        self.off_value = endpoint_info["valid_values"].get("off_value", 1802)  # pyright: ignore[reportOptionalMemberAccess]
        self._attr_should_poll = False
        self._attr_is_on = bool(coordinator.data.get(self.unique_id, False))

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update attributes when the coordinator updates."""
        if self.unique_id in self.coordinator.data:
            self._attr_is_on = bool(self.coordinator.data[self.unique_id])
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        eta_client = self._create_eta_client()
        res = await eta_client.set_switch_state(self.uri, self.on_value)
        if res:
            self._attr_is_on = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        eta_client = self._create_eta_client()
        res = await eta_client.set_switch_state(self.uri, self.off_value)
        if res:
            self._attr_is_on = False
            self.async_write_ha_state()
