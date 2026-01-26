"""Switch platform for the ETA sensor integration in Home Assistant."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant import config_entries
from homeassistant.components.switch import ENTITY_ID_FORMAT, SwitchEntity
from homeassistant.core import HomeAssistant

from .api import EtaAPI, ETAEndpoint
from .const import CHOSEN_SWITCHES, DOMAIN, SWITCHES_DICT
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

    chosen_entities = config[CHOSEN_SWITCHES]
    switches = [
        EtaSwitch(config, hass, entity, config[SWITCHES_DICT][entity])
        for entity in chosen_entities
    ]
    async_add_entities(switches, update_before_add=True)


class EtaSwitch(EtaEntity, SwitchEntity):
    """Representation of a Switch."""

    def __init__(  # noqa: D107
        self,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
    ) -> None:
        _LOGGER.info("ETA Integration - init switch")

        super().__init__(config, hass, unique_id, endpoint_info, ENTITY_ID_FORMAT)

        self._attr_icon = "mdi:power"

        self.on_value = endpoint_info["valid_values"].get("on_value", 1803)  # pyright: ignore[reportOptionalMemberAccess]
        self.off_value = endpoint_info["valid_values"].get("off_value", 1802)  # pyright: ignore[reportOptionalMemberAccess]
        self._attr_is_on = False
        self._attr_should_poll = True

    async def async_update(self):
        """Fetch new state data for the switch.

        This is the only method that should fetch new data for Home Assistant.
        """
        eta_client = EtaAPI(self.session, self.host, self.port)
        value = await eta_client.get_switch_state(self.uri)
        if value == self.on_value:
            self._attr_is_on = True
        else:
            self._attr_is_on = False

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        eta_client = EtaAPI(self.session, self.host, self.port)
        res = await eta_client.set_switch_state(self.uri, self.on_value)
        if res:
            self._attr_is_on = True

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        eta_client = EtaAPI(self.session, self.host, self.port)
        res = await eta_client.set_switch_state(self.uri, self.off_value)
        if res:
            self._attr_is_on = False
