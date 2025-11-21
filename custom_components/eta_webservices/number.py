"""
Platform for ETA number integration in Home Assistant

author Tidone

"""

from __future__ import annotations

import logging
import voluptuous as vol
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
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import async_get_current_platform
from homeassistant.helpers.typing import VolDictType
from .coordinator import ETAWritableUpdateCoordinator
from .const import (
    DOMAIN,
    CHOSEN_WRITABLE_SENSORS,
    WRITABLE_DICT,
    WRITABLE_UPDATE_COORDINATOR,
    INVISIBLE_UNITS,
    ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION,
)

SCAN_INTERVAL = timedelta(minutes=1)

WRITE_VALUE_SCALED_SCHEMA: VolDictType = {
    vol.Required("value"): vol.Number(),
    vol.Required("force_decimals"): cv.boolean,
}


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

    platform = async_get_current_platform()
    platform.async_register_entity_service(
        "write_value_scaled", WRITE_VALUE_SCALED_SCHEMA, "async_set_native_value"
    )


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

        self.ignore_decimal_places_restriction = unique_id in config.get(
            ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION, []
        )
        self._attr_device_class = self.determine_device_class(endpoint_info["unit"])
        self.valid_values: ETAValidWritableValues = endpoint_info["valid_values"]

        self._attr_native_unit_of_measurement = endpoint_info["unit"]
        if self._attr_native_unit_of_measurement == "":
            self._attr_native_unit_of_measurement = None

        self._attr_entity_category = EntityCategory.CONFIG

        self._attr_mode = NumberMode.BOX
        self._attr_native_min_value = self.valid_values["scaled_min_value"]
        self._attr_native_max_value = self.valid_values["scaled_max_value"]
        if self.ignore_decimal_places_restriction:
            # set the step size based on the scale factor, i.e. use as many decimal places as the scale factor allows
            self._attr_native_step = pow(
                10, (len(str(self.valid_values["scale_factor"])) - 1) * -1
            )
        else:
            # calculate the step size based on the number of decimal places
            self._attr_native_step = pow(10, self.valid_values["dec_places"] * -1)

    def handle_data_updates(self, data: float) -> None:
        self._attr_native_value = data

    async def async_set_native_value(
        self, value: float, force_decimals: bool = False
    ) -> None:
        """Update the current value."""
        if self.ignore_decimal_places_restriction or force_decimals:
            _LOGGER.debug(
                "ETA Integration - HACK: Ignoring decimal places restriction for writable sensor %s",
                self._attr_name,
            )
            # scale the value based on the scale factor and ignore the dec_places, i.e. set as many decimal places as the scale factor allows
            raw_value = round(value * self.valid_values["scale_factor"], 0)
        else:
            raw_value = round(value, self.valid_values["dec_places"])
            raw_value *= self.valid_values["scale_factor"]
            raw_value = round(raw_value, 0)

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
