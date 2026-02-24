"""Number platform for the ETA sensor integration in Home Assistant."""

from __future__ import annotations

from datetime import timedelta
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.number import (
    ENTITY_ID_FORMAT,
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import async_get_current_platform
from homeassistant.helpers.typing import VolDictType

from .api import ETAEndpoint, ETAValidWritableValues
from .const import (
    ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION,
    CHOSEN_WRITABLE_SENSORS,
    CUSTOM_UNIT_UNITLESS,
    DOMAIN,
    INVISIBLE_UNITS,
    WRITABLE_DICT,
    WRITABLE_UPDATE_COORDINATOR,
)
from .coordinator import ETAWritableUpdateCoordinator
from .entity import EtaWritableSensorEntity
from .utils import get_native_unit

_LOGGER = logging.getLogger(__name__)

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
        or config[WRITABLE_DICT][entity]["unit"]
        == CUSTOM_UNIT_UNITLESS  # except unitless endpoints
    ]
    async_add_entities(sensors, update_before_add=True)

    platform = async_get_current_platform()
    platform.async_register_entity_service(
        "write_value_scaled", WRITE_VALUE_SCALED_SCHEMA, "async_set_native_value"
    )


class EtaWritableNumberSensor(NumberEntity, EtaWritableSensorEntity):
    """Representation of a Number Entity."""

    def __init__(  # noqa: D107
        self,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        coordinator: ETAWritableUpdateCoordinator,
    ) -> None:
        _LOGGER.info("ETA Integration - init writable number sensor")

        super().__init__(
            coordinator, config, hass, unique_id, endpoint_info, ENTITY_ID_FORMAT
        )

        self.ignore_decimal_places_restriction = unique_id in config.get(
            ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION, []
        )
        self._attr_device_class = self.determine_device_class(endpoint_info["unit"])
        self.valid_values: ETAValidWritableValues = endpoint_info["valid_values"]  # pyright: ignore[reportAttributeAccessIssue]

        self._attr_native_unit_of_measurement = get_native_unit(endpoint_info["unit"])

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

    def handle_data_updates(self, data: float) -> None:  # noqa: D102
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
            if (
                value < self.valid_values["scaled_min_value"]
                or value > self.valid_values["scaled_max_value"]
            ):
                raise HomeAssistantError(
                    f"Temperature value out of bounds for entity {self.entity_id}"
                )

        eta_client = self._create_eta_client()
        success = await eta_client.write_endpoint(self.uri, raw_value)
        if not success:
            raise HomeAssistantError(
                f"Could not write value for entity {self.entity_id}, see log for details"
            )
        await self.coordinator.async_refresh()

    @staticmethod
    def determine_device_class(unit):
        """Determine the Entity device class based on the sensor's unit."""
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
