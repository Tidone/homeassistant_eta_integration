"""Sensor platform for the ETA sensor integration in Home Assistant.

Help Links:
 Entity Source: https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/entity.py
 SensorEntity derives from Entity https://github.com/home-assistant/core/blob/dev/homeassistant/components/sensor/__init__.py


author nigl, Tidone
"""

from __future__ import annotations

from datetime import time, timedelta
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.sensor import (
    ENTITY_ID_FORMAT,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_platform import async_get_current_platform
from homeassistant.helpers.typing import VolDictType

from .api import ETAEndpoint, ETAError, ETAValidWritableValues
from .const import (
    CHOSEN_FLOAT_SENSORS,
    CHOSEN_TEXT_SENSORS,
    CHOSEN_WRITABLE_SENSORS,
    CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT,
    CUSTOM_UNIT_TIMESLOT,
    CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE,
    DOMAIN,
    ERROR_UPDATE_COORDINATOR,
    FLOAT_DICT,
    SENSOR_UPDATE_COORDINATOR,
    SUPPORT_WRITE_TIMESLOT,
    SUPPORT_WRITE_TIMESLOT_WITH_TEMPERATURE,
    TEXT_DICT,
    WRITABLE_DICT,
    WRITABLE_UPDATE_COORDINATOR,
)
from .coordinator import (
    ETAErrorUpdateCoordinator,
    ETASensorUpdateCoordinator,
    ETAWritableUpdateCoordinator,
)
from .entity import (
    EtaCoordinatedSensorEntity,
    EtaErrorEntity,
    EtaWritableSensorEntity,
)
from .utils import get_native_unit

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=1)

WRITE_TIMESLOT_SCHEMA: VolDictType = {
    vol.Required("begin"): cv.time,
    vol.Required("end"): cv.time,
}

WRITE_TIMESLOT_PLUS_TEMPERATURE_SCHEMA: VolDictType = {
    vol.Required("temperature"): vol.Number(),
    vol.Required("begin"): cv.time,
    vol.Required("end"): cv.time,
}


def _deduplicate_entities_by_unique_id(entities: list[SensorEntity]) -> list[SensorEntity]:
    """Drop duplicate entities with identical unique IDs.

    In rare edge cases a sensor can temporarily end up in multiple categories
    in config data. Guard against duplicate entity registration at runtime.
    """
    deduplicated_entities: list[SensorEntity] = []
    seen_unique_ids: set[str] = set()

    for entity in entities:
        unique_id = entity.unique_id
        if unique_id is None:
            deduplicated_entities.append(entity)
            continue

        if unique_id in seen_unique_ids:
            _LOGGER.warning(
                "Skipping duplicate sensor entity with unique_id '%s' (entity_id: %s)",
                unique_id,
                entity.entity_id,
            )
            continue

        seen_unique_ids.add(unique_id)
        deduplicated_entities.append(entity)

    return deduplicated_entities


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    """Setup sensors from a config entry created in the integrations UI."""
    config = hass.data[DOMAIN][config_entry.entry_id]

    sensor_coordinator = config[SENSOR_UPDATE_COORDINATOR]
    writable_coordinator = config[WRITABLE_UPDATE_COORDINATOR]

    chosen_float_sensors = config[CHOSEN_FLOAT_SENSORS]
    chosen_writable_sensors = config[CHOSEN_WRITABLE_SENSORS]
    # sensors don't use a coordinator if they are not also selected as writable endpoints,
    sensors = [
        EtaFloatSensor(
            config,
            hass,
            entity,
            config[FLOAT_DICT][entity],
            sensor_coordinator,
        )
        for entity in chosen_float_sensors
        if entity + "_writable" not in chosen_writable_sensors
    ]
    # sensors use a coordinator if they are also selected as writable endpoints,
    # to be able to update the value immediately if the user writes a new value
    # this only handles cases where a sensor is selected as both, a writable sensor and a float sensor
    # the actual writable sensor is handled in the number entity
    sensors.extend(
        [
            EtaFloatWritableSensor(
                config,
                hass,
                entity,
                config[FLOAT_DICT][entity],
                writable_coordinator,
            )
            for entity in chosen_float_sensors
            if entity + "_writable" in chosen_writable_sensors
        ]  # pyright: ignore[reportArgumentType]
    )

    chosen_text_sensors = config[CHOSEN_TEXT_SENSORS]
    # add the text sensors which are not also writable first
    # these entities don't use a coordinator
    sensors.extend(
        [
            EtaTextSensor(
                config,
                hass,
                entity,
                config[TEXT_DICT][entity],
                sensor_coordinator,
            )
            for entity in chosen_text_sensors
            if entity + "_writable" not in chosen_writable_sensors
            and config[TEXT_DICT][entity]["unit"]
            not in [CUSTOM_UNIT_TIMESLOT, CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE]
        ]  # pyright: ignore[reportArgumentType]
    )
    # use a special entity if a text sensor is also added as a writable sensor
    # this entity uses a coordinator to update the value immediately after a user sets it in the writable (time) entity
    sensors.extend(
        [
            EtaTimeWritableSensor(
                config,
                hass,
                entity,
                config[TEXT_DICT][entity],
                writable_coordinator,
            )
            for entity in chosen_text_sensors
            if entity + "_writable" in chosen_writable_sensors
            and config[TEXT_DICT][entity]["unit"] == CUSTOM_UNIT_MINUTES_SINCE_MIDNIGHT
        ]  # pyright: ignore[reportArgumentType]
    )
    # add the non-writable timeslot sensors first
    sensors.extend(
        [
            EtaTimeslotSensor(
                config,
                hass,
                entity,
                config[TEXT_DICT][entity],
                sensor_coordinator,
                should_activate_service=False,
            )
            for entity in chosen_text_sensors
            if config[TEXT_DICT][entity]["unit"]
            in [CUSTOM_UNIT_TIMESLOT, CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE]
        ]  # pyright: ignore[reportArgumentType]
    )
    # then add the writable timeslot sensors
    # These share the same implementation as the text timeslot sensors above,
    # but the entities set their supported features so they can be used in the service call
    sensors.extend(
        [
            EtaTimeslotSensor(
                config,
                hass,
                entity,
                config[WRITABLE_DICT][entity],
                sensor_coordinator,
                should_activate_service=True,
            )
            for entity in chosen_writable_sensors
            if config[WRITABLE_DICT][entity]["unit"]
            in [CUSTOM_UNIT_TIMESLOT, CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE]
        ]  # pyright: ignore[reportArgumentType]
    )
    error_coordinator = config[ERROR_UPDATE_COORDINATOR]
    sensors.extend(
        [
            EtaNbrErrorsSensor(config, hass, error_coordinator),
            EtaLatestErrorSensor(config, hass, error_coordinator),
        ]  # pyright: ignore[reportArgumentType]
    )
    # Final safety net: avoid HA startup failures if config data still contains
    # the same unique_id in multiple sensor categories.
    sensors = _deduplicate_entities_by_unique_id(sensors)
    async_add_entities(sensors, update_before_add=False)

    # activate the service for all selected writable sensors with the unit CUSTOM_UNIT_TIMESLOT
    if any(
        config[WRITABLE_DICT][entity]["unit"] == CUSTOM_UNIT_TIMESLOT
        for entity in chosen_writable_sensors
    ):
        platform = async_get_current_platform()
        platform.async_register_entity_service(
            "write_timeslot",
            WRITE_TIMESLOT_SCHEMA,
            "async_update_timeslot_service",
            required_features=[SUPPORT_WRITE_TIMESLOT],
        )

    # activate the service for all selected writable sensors with the unit CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE
    if any(
        config[WRITABLE_DICT][entity]["unit"] == CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE
        for entity in chosen_writable_sensors
    ):
        platform = async_get_current_platform()
        platform.async_register_entity_service(
            "write_timeslot_plus_temperature",
            WRITE_TIMESLOT_PLUS_TEMPERATURE_SCHEMA,
            "async_update_timeslot_service",
            required_features=[SUPPORT_WRITE_TIMESLOT_WITH_TEMPERATURE],
        )


def _determine_device_class(unit):
    unit_dict_eta = {
        "°C": SensorDeviceClass.TEMPERATURE,
        "W": SensorDeviceClass.POWER,
        "A": SensorDeviceClass.CURRENT,
        "Hz": SensorDeviceClass.FREQUENCY,
        "Pa": SensorDeviceClass.PRESSURE,
        "V": SensorDeviceClass.VOLTAGE,
        "W/m²": SensorDeviceClass.IRRADIANCE,
        "bar": SensorDeviceClass.PRESSURE,
        "kW": SensorDeviceClass.POWER,
        "kWh": SensorDeviceClass.ENERGY,
        "kg": SensorDeviceClass.WEIGHT,
        "mV": SensorDeviceClass.VOLTAGE,
        "s": SensorDeviceClass.DURATION,
        "%rH": SensorDeviceClass.HUMIDITY,
    }

    if unit in unit_dict_eta:
        return unit_dict_eta[unit]

    return None


def _coerce_numeric_value(value: float | int | str | None) -> float | None:
    """Convert ETA values for numeric sensors, or return None if not numeric.

    ETA may temporarily return text placeholders (e.g. "---", "Aus") for
    sensors that are normally numeric. In that case we keep the entity type
    stable and publish an unavailable state for that update cycle.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)

    normalized_value = str(value).strip().replace(",", ".")
    if normalized_value == "":
        return None

    try:
        return float(normalized_value)
    except ValueError:
        return None


class EtaFloatSensor(SensorEntity, EtaCoordinatedSensorEntity[float]):
    """Representation of a Float Sensor."""

    def __init__(  # noqa: D107
        self,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        coordinator: ETASensorUpdateCoordinator,
    ) -> None:
        _LOGGER.info("ETA Integration - init float sensor")

        super().__init__(
            coordinator, config, hass, unique_id, endpoint_info, ENTITY_ID_FORMAT
        )

        self._attr_device_class = _determine_device_class(endpoint_info["unit"])

        self._attr_native_unit_of_measurement = get_native_unit(endpoint_info["unit"])

        if self._attr_device_class == SensorDeviceClass.ENERGY:
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    def handle_data_updates(self, data: float | str) -> None:  # noqa: D102
        numeric_value = _coerce_numeric_value(data)
        if numeric_value is None:
            _LOGGER.debug(
                "Sensor %s received non-numeric value '%s'; setting state to unavailable",
                self.entity_id,
                data,
            )
            self._attr_native_value = None
            return
        self._attr_native_value = numeric_value


class EtaFloatWritableSensor(SensorEntity, EtaWritableSensorEntity):
    """Representation of a Float Sensor with a coordinator."""

    def __init__(  # noqa: D107
        self,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        coordinator: ETAWritableUpdateCoordinator,
    ) -> None:
        _LOGGER.info("ETA Integration - init float sensor with coordinator")

        super().__init__(
            coordinator, config, hass, unique_id, endpoint_info, ENTITY_ID_FORMAT
        )

        self._attr_device_class = _determine_device_class(endpoint_info["unit"])

        self._attr_native_unit_of_measurement = get_native_unit(endpoint_info["unit"])

        if self._attr_device_class == SensorDeviceClass.ENERGY:
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT

    def handle_data_updates(self, data: float | str) -> None:  # noqa: D102
        numeric_value = _coerce_numeric_value(data)
        if numeric_value is None:
            _LOGGER.debug(
                "Writable sensor %s received non-numeric value '%s'; setting state to unavailable",
                self.entity_id,
                data,
            )
            self._attr_native_value = None
            return
        self._attr_native_value = numeric_value


class EtaTextSensor(SensorEntity, EtaCoordinatedSensorEntity[str]):
    """Representation of a Text Sensor."""

    def __init__(  # noqa: D107
        self,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        coordinator: ETASensorUpdateCoordinator,
    ) -> None:
        _LOGGER.info("ETA Integration - init text sensor")

        super().__init__(
            coordinator, config, hass, unique_id, endpoint_info, ENTITY_ID_FORMAT
        )

    def handle_data_updates(self, data: str) -> None:  # noqa: D102
        self._attr_native_value = data


class EtaTimeslotSensor(SensorEntity, EtaCoordinatedSensorEntity[str]):
    """Representation of a Text Sensor representing timeslots."""

    def __init__(  # noqa: D107
        self,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        coordinator: ETASensorUpdateCoordinator,
        should_activate_service: bool,
    ) -> None:
        _LOGGER.info("ETA Integration - init timeslot sensor")

        self.temperature_unit = "°C"
        super().__init__(
            coordinator, config, hass, unique_id, endpoint_info, ENTITY_ID_FORMAT
        )
        self.valid_values: ETAValidWritableValues = endpoint_info["valid_values"]  # pyright: ignore[reportAttributeAccessIssue]

        # Set supported features based on unit type and writability
        if should_activate_service:
            if endpoint_info["unit"] == CUSTOM_UNIT_TIMESLOT_PLUS_TEMPERATURE:
                self._attr_supported_features = SUPPORT_WRITE_TIMESLOT_WITH_TEMPERATURE
            elif endpoint_info["unit"] == CUSTOM_UNIT_TIMESLOT:
                self._attr_supported_features = SUPPORT_WRITE_TIMESLOT
            else:
                self._attr_supported_features = 0
        else:
            self._attr_supported_features = 0

    async def async_update_timeslot_service(
        self, begin: time, end: time, temperature: float | None = None
    ) -> None:
        """Handle the write_timeslot service call."""
        # If a temperature is provided validate that the entity supports it
        if temperature is not None and not (
            self._attr_supported_features
            and (
                self._attr_supported_features & SUPPORT_WRITE_TIMESLOT_WITH_TEMPERATURE
            )
        ):
            # We should not get here, but it's better to be safe than sorry
            raise HomeAssistantError(
                f"Entity {self.entity_id} does not support setting the temperature for the timeslot"
            )
        if (
            self._attr_supported_features
            and (
                self._attr_supported_features & SUPPORT_WRITE_TIMESLOT_WITH_TEMPERATURE
            )
            and temperature is None
        ):
            raise HomeAssistantError(
                f"Entity {self.entity_id} needs a temperature for the timeslot"
            )

        raw_value = None
        if temperature:
            raw_value = round(temperature, self.valid_values["dec_places"])
            raw_value *= self.valid_values["scale_factor"]
            raw_value = round(raw_value, 0)
            if (
                temperature < self.valid_values["scaled_min_value"]
                or temperature > self.valid_values["scaled_max_value"]
            ):
                raise HomeAssistantError(
                    f"Temperature value out of bounds for entity {self.entity_id}"
                )

        raw_begin = round((begin.hour * 60 + begin.minute) / 15)
        raw_end = round((end.hour * 60 + end.minute) / 15)

        if (
            raw_begin < 0
            or raw_begin > 24 * 60 / 15
            or raw_end < 0
            or raw_end > 24 * 60 / 15
            or raw_begin > raw_end
        ):
            raise HomeAssistantError(f"Invalid timeslot for entity {self.entity_id}")

        eta_client = self._create_eta_client()
        success = await eta_client.write_endpoint(
            self.uri, raw_value, raw_begin, raw_end
        )
        if not success:
            raise HomeAssistantError(
                f"Could not write value for entity {self.entity_id}, see log for details"
            )
        await self.coordinator.async_refresh()

    def _parse_timeslot_value(self, value: str) -> tuple[str, str, str | None]:
        """Parse a timeslot value string.

        Args:
            value: String in format "HH:MM - HH:MM" or "HH:MM - HH:MM <number>"

        Returns:
            Tuple of (start_time, end_time, optional_value)
            where optional_value is None if not present
        """
        # Split by " - " to separate start time from the rest
        parts = value.split("-")
        if len(parts) != 2:
            return "", "", None  # Invalid format

        start_time = parts[0].strip()

        # Split the second part by space to get end time and optional value
        end_parts = parts[1].strip().split()
        end_time = end_parts[0]

        # Check if there's a third value
        optional_value = end_parts[1] if len(end_parts) > 1 else None

        return start_time, end_time, optional_value

    def handle_data_updates(self, data: str) -> None:  # noqa: D102
        start_time, end_time, temperature = self._parse_timeslot_value(str(data))

        if start_time == "" or end_time == "":
            self._attr_native_value = str(data)
            return

        if temperature:
            self._attr_native_value = (
                f"{start_time} - {end_time}: {temperature} {self.temperature_unit}"
            )
        else:
            self._attr_native_value = f"{start_time} - {end_time}"


class EtaTimeWritableSensor(SensorEntity, EtaWritableSensorEntity):
    """Representation of a Text Sensor (displaying a time) with a coordinator."""

    def __init__(  # noqa: D107
        self,
        config: dict,
        hass: HomeAssistant,
        unique_id: str,
        endpoint_info: ETAEndpoint,
        coordinator: ETAWritableUpdateCoordinator,
    ) -> None:
        _LOGGER.info("ETA Integration - init text sensor with coordinator")

        super().__init__(
            coordinator, config, hass, unique_id, endpoint_info, ENTITY_ID_FORMAT
        )

    def handle_data_updates(self, data: float) -> None:  # noqa: D102
        # the coordinator returns the minutes since midnight, not the textual representation
        # so we have to calculate the textual representation here
        total_minutes = int(data)
        hours = total_minutes // 60
        minutes = total_minutes % 60

        self._attr_native_value = f"{hours:02d}:{minutes:02d}"


class EtaNbrErrorsSensor(SensorEntity, EtaErrorEntity):
    """Representation of a sensor showing the number of active errors."""

    def __init__(  # noqa: D107
        self, config: dict, hass: HomeAssistant, coordinator: ETAErrorUpdateCoordinator
    ) -> None:
        super().__init__(
            coordinator, config, hass, ENTITY_ID_FORMAT, "_nbr_active_errors"
        )

        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_state_class = SensorStateClass.MEASUREMENT

        self._attr_native_value = 0
        self._attr_native_unit_of_measurement = None

        self._attr_has_entity_name = True
        self._attr_translation_key = "nbr_active_errors_sensor"

        self.handle_data_updates(self.coordinator.data)

    def handle_data_updates(self, data: list):  # noqa: D102
        self._attr_native_value = len(data)


class EtaLatestErrorSensor(SensorEntity, EtaErrorEntity):
    """Representation of a sensor showing the latest active error."""

    def __init__(  # noqa: D107
        self, config: dict, hass: HomeAssistant, coordinator: ETAErrorUpdateCoordinator
    ) -> None:
        super().__init__(coordinator, config, hass, ENTITY_ID_FORMAT, "_latest_error")

        self._attr_entity_category = EntityCategory.DIAGNOSTIC

        self._attr_native_value = ""
        self._attr_native_unit_of_measurement = None

        self._attr_has_entity_name = True
        self._attr_translation_key = "latest_error_sensor"

        self.handle_data_updates(self.coordinator.data)

    def handle_data_updates(self, data: list[ETAError]):  # noqa: D102
        if len(data) == 0:
            self._attr_native_value = "-"
            return

        sorted_errors = sorted(data, key=lambda d: d["time"])
        self._attr_native_value = sorted_errors[-1]["msg"]
