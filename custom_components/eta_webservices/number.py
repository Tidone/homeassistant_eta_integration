"""
Platform for ETA number integration in Home Assistant

author Tidone

"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)
from .api import EtaAPI, ETAEndpoint, ETAValidWritableValues
from .entity import EtaWritableSensorEntity

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
    ENTITY_ID_FORMAT,
)

from homeassistant.core import HomeAssistant
from homeassistant import config_entries
from homeassistant.const import EntityCategory
from .coordinator import ETAWritableUpdateCoordinator
from .const import (
    DOMAIN,
    CHOSEN_WRITABLE_SENSORS,
    WRITABLE_DICT,
    WRITABLE_UPDATE_COORDINATOR,
    INVISIBLE_UNITS,
)

SCAN_INTERVAL = timedelta(minutes=1)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    """Setup sensors from a config entry created in the integrations UI."""
    config = hass.data[DOMAIN][config_entry.entry_id]

    coordinator = config[WRITABLE_UPDATE_COORDINATOR]

    chosen_writable_sensors = config[CHOSEN_WRITABLE_SENSORS]
    sensors = [
        EtaWritableNumberSensor(
            config, hass, entity, config[WRITABLE_DICT][entity], coordinator
        )
        for entity in chosen_writable_sensors
        if config[WRITABLE_DICT][entity]["unit"]
        not in INVISIBLE_UNITS  # exclude all endpoints with a custom unit (e.g. time endpoints)
    ]
    async_add_entities(sensors, update_before_add=True)


class EtaWritableNumberSensor(NumberEntity, EtaWritableSensorEntity):
    """Representation of a Number Entity."""

    def __init__(
        self,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        coordinator: ETAWritableUpdateCoordinator,
    ) -> None:
        """
        Initialize sensor.

        To show all values: http://192.168.178.75:8080/user/menu

        """
        _LOGGER.info("ETA Integration - init writable number sensor")

        super().__init__(
            coordinator, config, hass, unique_id, endpoint_info, ENTITY_ID_FORMAT
        )

        self._attr_device_class = self.determine_device_class(endpoint_info["unit"])
        self.valid_values: ETAValidWritableValues = endpoint_info["valid_values"]

        self._attr_native_unit_of_measurement = endpoint_info["unit"]
        if self._attr_native_unit_of_measurement == "":
            self._attr_native_unit_of_measurement = None

        self._attr_entity_category = EntityCategory.CONFIG

        self._attr_mode = NumberMode.BOX
        self._attr_native_min_value = endpoint_info["valid_values"]["scaled_min_value"]
        self._attr_native_max_value = endpoint_info["valid_values"]["scaled_max_value"]
        self._attr_native_step = pow(
            10, endpoint_info["valid_values"]["dec_places"] * -1
        )  # calculate the step size based on the number of decimal places

    def handle_data_updates(self, data: float) -> None:
        self._attr_native_value = data

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        raw_value = round(value * self.valid_values["scale_factor"], self.valid_values["dec_places"])
        eta_client = EtaAPI(self.session, self.host, self.port)
        success = await eta_client.write_endpoint(self.uri, raw_value)
        if not success:
            raise HomeAssistantError("Could not write value, see log for details")
        await self.coordinator.async_refresh()

    @staticmethod
    def determine_device_class(unit):
        unit_dict_eta = {
            "°C": NumberDeviceClass.TEMPERATURE,
            "W": NumberDeviceClass.POWER,
            "A": NumberDeviceClass.CURRENT,
            "Hz": NumberDeviceClass.FREQUENCY,
            "Pa": NumberDeviceClass.PRESSURE,
            "V": NumberDeviceClass.VOLTAGE,
            "W/m²": NumberDeviceClass.IRRADIANCE,
            "bar": NumberDeviceClass.PRESSURE,
            "kW": NumberDeviceClass.POWER,
            "kWh": NumberDeviceClass.ENERGY,
            "kg": NumberDeviceClass.WEIGHT,
            "mV": NumberDeviceClass.VOLTAGE,
            "s": NumberDeviceClass.DURATION,
        }

        if unit in unit_dict_eta:
            return unit_dict_eta[unit]

        return None
