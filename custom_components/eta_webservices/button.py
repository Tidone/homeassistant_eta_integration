"""Button platform for the ETA sensor integration in Home Assistant."""

from __future__ import annotations

from homeassistant.components.button import ENTITY_ID_FORMAT, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ERROR_UPDATE_COORDINATOR
from .coordinator import ETAErrorUpdateCoordinator
from .utils import create_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup button."""
    config = hass.data[DOMAIN][config_entry.entry_id]
    error_coordinator = config[ERROR_UPDATE_COORDINATOR]

    buttons = [
        EtaResendErrorEventsButton(config, hass, error_coordinator),
    ]

    async_add_entities(buttons)


class EtaResendErrorEventsButton(ButtonEntity):
    """Representation of a Button."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(  # noqa: D107
        self, config: dict, hass: HomeAssistant, coordinator: ETAErrorUpdateCoordinator
    ) -> None:
        host = config.get(CONF_HOST, "")
        port = config.get(CONF_PORT, "")
        self.coordinator = coordinator

        self._attr_translation_key = "send_error_events_btn"
        self._attr_unique_id = (
            "eta_" + host.replace(".", "_") + "_" + str(port) + "_send_events_btn"
        )
        self.entity_id = generate_entity_id(
            ENTITY_ID_FORMAT, self._attr_unique_id, hass=hass
        )
        self._attr_device_info = create_device_info(host, port)
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        """Force the error update coordinator to resend all error events."""
        # Delete the old error list to force the coordinator to resend all events
        self.coordinator.data = []
        await self.coordinator.async_refresh()
