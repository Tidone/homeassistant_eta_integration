"""Adds config flow for ETA Sensors."""

import copy
import logging

import voluptuous as vol

from homeassistant.config_entries import CONN_CLASS_CLOUD_POLL, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
import homeassistant.helpers.entity_registry as er

from .api import EtaAPI, ETAEndpoint
from .const import (
    ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION,
    AUTO_SELECT_ALL_ENTITIES,
    CHOSEN_FLOAT_SENSORS,
    CHOSEN_SWITCHES,
    CHOSEN_TEXT_SENSORS,
    CHOSEN_WRITABLE_SENSORS,
    DEFAULT_MAX_PARALLEL_REQUESTS,
    CUSTOM_UNITS,
    DOMAIN,
    ENABLE_DEBUG_LOGGING,
    FLOAT_DICT,
    FORCE_LEGACY_MODE,
    INVISIBLE_UNITS,
    MAX_PARALLEL_REQUESTS,
    OPTIONS_ENUMERATE_NEW_ENDPOINTS,
    OPTIONS_UPDATE_SENSOR_VALUES,
    SWITCHES_DICT,
    TEXT_DICT,
    WRITABLE_DICT,
)

_LOGGER = logging.getLogger(__name__)


def _build_discovered_entity_placeholders(
    float_count: int, switch_count: int, text_count: int, writable_count: int
) -> dict[str, str]:
    """Build placeholders for discovered entity counts."""
    total_count = float_count + switch_count + text_count + writable_count
    return {
        "float_count": str(float_count),
        "switch_count": str(switch_count),
        "text_count": str(text_count),
        "writable_count": str(writable_count),
        "total_count": str(total_count),
    }


def _sanitize_selected_entity_ids(
    selected_float_sensors: list[str],
    selected_switches: list[str],
    selected_text_sensors: list[str],
    selected_writable_sensors: list[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Ensure selected entity IDs are unique across categories.

    The same unique_id must never be selected in multiple regular sensor
    categories, otherwise HA will reject duplicated entities on setup.
    """
    sanitized_float_sensors = list(dict.fromkeys(selected_float_sensors))
    float_set = set(sanitized_float_sensors)

    sanitized_switches = [
        sensor_id
        for sensor_id in dict.fromkeys(selected_switches)
        if sensor_id not in float_set
    ]
    switch_set = set(sanitized_switches)

    sanitized_text_sensors = [
        sensor_id
        for sensor_id in dict.fromkeys(selected_text_sensors)
        if sensor_id not in float_set and sensor_id not in switch_set
    ]
    sanitized_writable_sensors = list(dict.fromkeys(selected_writable_sensors))

    removed_from_switches = len(selected_switches) - len(sanitized_switches)
    removed_from_text_sensors = len(selected_text_sensors) - len(
        sanitized_text_sensors
    )
    if removed_from_switches > 0 or removed_from_text_sensors > 0:
        _LOGGER.info(
            "Removed duplicate selected entity IDs across categories: "
            "switches=%d, text_sensors=%d",
            removed_from_switches,
            removed_from_text_sensors,
        )

    return (
        sanitized_float_sensors,
        sanitized_switches,
        sanitized_text_sensors,
        sanitized_writable_sensors,
    )


class EtaFlowHandler(ConfigFlow, domain=DOMAIN):
    """Config flow for Eta."""

    VERSION = 6
    CONNECTION_CLASS = CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        """Initialize."""
        self._errors = {}
        self.data = {}
        self._old_logging_level = logging.NOTSET

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        # Uncomment the next 2 lines if only a single instance of the integration is allowed:
        # if self._async_current_entries():
        #     return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            platform_entries = self._async_current_entries()
            for entry in platform_entries:
                if entry.data.get(CONF_HOST, "") == user_input[CONF_HOST]:
                    return self.async_abort(reason="single_instance_allowed")
            valid = await self._test_url(user_input[CONF_HOST], user_input[CONF_PORT])
            if valid == 1:
                is_correct_api_version = await self._is_correct_api_version(
                    user_input[CONF_HOST], user_input[CONF_PORT]
                )
                if not is_correct_api_version:
                    self._errors["base"] = "wrong_api_version"
                elif user_input[FORCE_LEGACY_MODE]:
                    self._errors["base"] = "legacy_mode_selected"

                if user_input[ENABLE_DEBUG_LOGGING] and _LOGGER.parent is not None:
                    self._old_logging_level = _LOGGER.parent.getEffectiveLevel()
                    _LOGGER.parent.setLevel(logging.DEBUG)

                self.data = user_input

                (
                    self.data[FLOAT_DICT],
                    self.data[SWITCHES_DICT],
                    self.data[TEXT_DICT],
                    self.data[WRITABLE_DICT],
                ) = await self._get_possible_endpoints(
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    user_input[FORCE_LEGACY_MODE],
                )

                return await self.async_step_select_entities()

            self._errors["base"] = "no_eta_endpoint" if valid == 0 else "unknown_host"

            return await self._show_config_form_user(user_input)

        user_input = {}
        # Provide defaults for form
        user_input[CONF_HOST] = "0.0.0.0"
        user_input[CONF_PORT] = "8080"

        return await self._show_config_form_user(user_input)

    async def async_step_select_entities(self, user_input=None):
        """Second step in config flow to add a repo to watch."""
        if user_input is not None:
            auto_select_all_entities = user_input.get(AUTO_SELECT_ALL_ENTITIES, False)
            # add chosen entities to data
            if auto_select_all_entities:
                selected_float_sensors = list(self.data[FLOAT_DICT].keys())
                selected_switches = list(self.data[SWITCHES_DICT].keys())
                selected_text_sensors = list(self.data[TEXT_DICT].keys())
                selected_writable_sensors = list(self.data[WRITABLE_DICT].keys())
            else:
                selected_float_sensors = user_input.get(CHOSEN_FLOAT_SENSORS, [])
                selected_switches = user_input.get(CHOSEN_SWITCHES, [])
                selected_text_sensors = user_input.get(CHOSEN_TEXT_SENSORS, [])
                selected_writable_sensors = user_input.get(
                    CHOSEN_WRITABLE_SENSORS, []
                )

            (
                self.data[CHOSEN_FLOAT_SENSORS],
                self.data[CHOSEN_SWITCHES],
                self.data[CHOSEN_TEXT_SENSORS],
                self.data[CHOSEN_WRITABLE_SENSORS],
            ) = _sanitize_selected_entity_ids(
                selected_float_sensors,
                selected_switches,
                selected_text_sensors,
                selected_writable_sensors,
            )

            # Restore old logging level
            if self._old_logging_level != logging.NOTSET and _LOGGER.parent is not None:
                _LOGGER.parent.setLevel(self._old_logging_level)

            # User is done, create the config entry.
            self.data.setdefault(MAX_PARALLEL_REQUESTS, DEFAULT_MAX_PARALLEL_REQUESTS)
            return self.async_create_entry(
                title=f"ETA at {self.data[CONF_HOST]}", data=self.data
            )

        return await self._show_config_form_endpoint()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):  # noqa: D102
        return EtaOptionsFlowHandler()

    async def _show_config_form_user(self, user_input):  # pylint: disable=unused-argument
        """Show the configuration form to edit host and port data."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=user_input[CONF_HOST]): str,
                    vol.Required(CONF_PORT, default=user_input[CONF_PORT]): str,
                    vol.Required(FORCE_LEGACY_MODE, default=False): cv.boolean,
                    vol.Required(ENABLE_DEBUG_LOGGING, default=False): cv.boolean,
                }
            ),
            errors=self._errors,
        )

    async def _show_config_form_endpoint(self):
        """Show the configuration form to select which endpoints should become entities."""
        sensors_dict: dict[str, ETAEndpoint] = self.data[FLOAT_DICT]
        switches_dict: dict[str, ETAEndpoint] = self.data[SWITCHES_DICT]
        text_dict: dict[str, ETAEndpoint] = self.data[TEXT_DICT]
        writable_dict: dict[str, ETAEndpoint] = self.data[WRITABLE_DICT]
        float_count = len(sensors_dict)
        switch_count = len(switches_dict)
        text_count = len(text_dict)
        writable_count = len(writable_dict)
        count_placeholders = _build_discovered_entity_placeholders(
            float_count, switch_count, text_count, writable_count
        )

        return self.async_show_form(
            step_id="select_entities",
            data_schema=vol.Schema(
                {
                    vol.Required(AUTO_SELECT_ALL_ENTITIES, default=False): cv.boolean,
                    vol.Optional(CHOSEN_FLOAT_SENSORS): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=key,
                                    label=f"{sensors_dict[key]['friendly_name']} ({sensors_dict[key]['value']} {sensors_dict[key]['unit'] if sensors_dict[key]['unit'] not in INVISIBLE_UNITS else ''})",
                                )
                                for key in sensors_dict
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            multiple=True,
                        )
                    ),
                    vol.Optional(CHOSEN_SWITCHES): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=key,
                                    label=f"{switches_dict[key]['friendly_name']} ({switches_dict[key]['value']})",
                                )
                                for key in switches_dict
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            multiple=True,
                        )
                    ),
                    vol.Optional(CHOSEN_TEXT_SENSORS): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=key,
                                    label=f"{text_dict[key]['friendly_name']} ({text_dict[key]['value']})",
                                )
                                for key in text_dict
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            multiple=True,
                        )
                    ),
                    vol.Optional(CHOSEN_WRITABLE_SENSORS): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=key,
                                    label=f"{writable_dict[key]['friendly_name']} ({writable_dict[key]['value']} {writable_dict[key]['unit'] if writable_dict[key]['unit'] not in INVISIBLE_UNITS else ''})",
                                )
                                for key in writable_dict
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            multiple=True,
                        )
                    ),
                }
            ),
            errors=self._errors,
            description_placeholders=count_placeholders,
        )

    async def _get_possible_endpoints(self, host, port, force_legacy_mode):
        session = async_get_clientsession(self.hass)
        eta_client = EtaAPI(session, host, port)
        float_dict = {}
        switches_dict = {}
        text_dict = {}
        writable_dict = {}
        await eta_client.get_all_sensors(
            force_legacy_mode, float_dict, switches_dict, text_dict, writable_dict
        )

        _LOGGER.debug(
            "Queried sensors: Number of float sensors: %i, Number of switches: %i, Number of text sensors: %i, Number of writable sensors: %i",
            len(float_dict),
            len(switches_dict),
            len(text_dict),
            len(writable_dict),
        )

        return float_dict, switches_dict, text_dict, writable_dict

    async def _test_url(self, host, port):
        """Return true if host port is valid."""
        session = async_get_clientsession(self.hass)
        eta_client = EtaAPI(session, host, port)

        try:
            does_endpoint_exist = await eta_client.does_endpoint_exists()
        except:  # noqa: E722
            return -1
        return 1 if does_endpoint_exist else 0

    async def _is_correct_api_version(self, host, port):
        session = async_get_clientsession(self.hass)
        eta_client = EtaAPI(session, host, port)

        return await eta_client.is_correct_api_version()


class EtaOptionsFlowHandler(OptionsFlow):
    """Blueprint config flow options handler."""

    @property
    def config_entry(self):  # noqa: D102
        return self.hass.config_entries.async_get_entry(self.handler)

    def __init__(self) -> None:
        """Initialize HACS options flow."""
        self.data = {}
        self._errors = {}
        self.update_sensor_values = False
        self.enumerate_new_endpoints = False
        self.auto_select_all_entities = False
        self.max_parallel_requests = DEFAULT_MAX_PARALLEL_REQUESTS
        self.unavailable_sensors: dict = {}
        self.advanced_options_writable_sensors = []

    async def _get_possible_endpoints(self, host, port, force_legacy_mode):
        session = async_get_clientsession(self.hass)
        eta_client = EtaAPI(session, host, port)
        float_dict = {}
        switches_dict = {}
        text_dict = {}
        writable_dict = {}
        await eta_client.get_all_sensors(
            force_legacy_mode, float_dict, switches_dict, text_dict, writable_dict
        )

        return float_dict, switches_dict, text_dict, writable_dict

    async def async_step_init(self, user_input=None):  # noqa: D102
        if user_input is not None:
            self.update_sensor_values = user_input[OPTIONS_UPDATE_SENSOR_VALUES]
            self.enumerate_new_endpoints = user_input[OPTIONS_ENUMERATE_NEW_ENDPOINTS]
            self.max_parallel_requests = int(user_input[MAX_PARALLEL_REQUESTS])
            return await self._update_data_structures()

        return await self._show_initial_option_screen()

    async def _show_initial_option_screen(self):
        """Show the initial option form."""
        parallel_request_options = ["1", "2", "3", "5", "8", "10", "15"]
        default_parallel_requests = self.hass.data[DOMAIN][
            self.config_entry.entry_id  # pyright: ignore[reportOptionalMemberAccess]
        ].get(MAX_PARALLEL_REQUESTS, DEFAULT_MAX_PARALLEL_REQUESTS)
        default_parallel_requests = str(default_parallel_requests)
        if default_parallel_requests not in parallel_request_options:
            default_parallel_requests = str(DEFAULT_MAX_PARALLEL_REQUESTS)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        OPTIONS_UPDATE_SENSOR_VALUES, default=False
                    ): cv.boolean,
                    vol.Required(
                        OPTIONS_ENUMERATE_NEW_ENDPOINTS, default=False
                    ): cv.boolean,
                    vol.Required(
                        MAX_PARALLEL_REQUESTS, default=default_parallel_requests
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=value, label=str(value))
                                for value in parallel_request_options
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            multiple=False,
                        )
                    ),
                }
            ),
            errors=self._errors,
        )

    async def _update_sensor_values(self):
        session = async_get_clientsession(self.hass)
        eta_client = EtaAPI(
            session,
            self.data[CONF_HOST],
            self.data[CONF_PORT],
            max_concurrent_requests=self.data[MAX_PARALLEL_REQUESTS],
        )

        sensor_list: dict[str, dict[str, bool]] = {
            value["url"]: {} for value in self.data[FLOAT_DICT].values()
        }
        sensor_list.update(
            {value["url"]: {} for value in self.data[SWITCHES_DICT].values()}
        )
        sensor_list.update(
            {
                value["url"]: {"force_string_handling": value["unit"] in CUSTOM_UNITS}
                for value in self.data[TEXT_DICT].values()
            }
        )
        sensor_list.update(
            {
                value["url"]: {"force_string_handling": value["unit"] in CUSTOM_UNITS}
                for value in self.data[WRITABLE_DICT].values()
            }
        )
        # first request the values for all possible sensors
        all_data = await eta_client.get_all_data(sensor_list)

        # then loop through our lists of sensors and update the values
        for entity in list(self.data[FLOAT_DICT].keys()):
            if self.data[FLOAT_DICT][entity]["url"] not in all_data:
                _LOGGER.exception(
                    "Exception while updating the value for endpoint '%s' (%s)",
                    self.data[FLOAT_DICT][entity]["friendly_name"],
                    self.data[FLOAT_DICT][entity]["url"],
                )
                self._errors["base"] = "value_update_error"
            else:
                self.data[FLOAT_DICT][entity]["value"] = all_data[
                    self.data[FLOAT_DICT][entity]["url"]
                ]

        for entity in list(self.data[SWITCHES_DICT].keys()):
            if self.data[SWITCHES_DICT][entity]["url"] not in all_data:
                _LOGGER.exception(
                    "Exception while updating the value for endpoint '%s' (%s)",
                    self.data[SWITCHES_DICT][entity]["friendly_name"],
                    self.data[SWITCHES_DICT][entity]["url"],
                )
                self._errors["base"] = "value_update_error"
            else:
                self.data[SWITCHES_DICT][entity]["value"] = all_data[
                    self.data[SWITCHES_DICT][entity]["url"]
                ]

        for entity in list(self.data[TEXT_DICT].keys()):
            if self.data[TEXT_DICT][entity]["url"] not in all_data:
                _LOGGER.exception(
                    "Exception while updating the value for endpoint '%s' (%s)",
                    self.data[TEXT_DICT][entity]["friendly_name"],
                    self.data[TEXT_DICT][entity]["url"],
                )
                self._errors["base"] = "value_update_error"
            else:
                self.data[TEXT_DICT][entity]["value"] = all_data[
                    self.data[TEXT_DICT][entity]["url"]
                ]

        for entity in list(self.data[WRITABLE_DICT].keys()):
            if self.data[WRITABLE_DICT][entity]["url"] not in all_data:
                _LOGGER.exception(
                    "Exception while updating the value for endpoint '%s' (%s)",
                    self.data[WRITABLE_DICT][entity]["friendly_name"],
                    self.data[WRITABLE_DICT][entity]["url"],
                )
                self._errors["base"] = "value_update_error"
            else:
                self.data[WRITABLE_DICT][entity]["value"] = all_data[
                    self.data[WRITABLE_DICT][entity]["url"]
                ]

    def _handle_new_sensors(
        self,
        new_float_sensors: dict,
        new_switches: dict,
        new_text_sensors: dict,
        new_writable_sensors: dict,
    ):
        added_sensor_count = 0
        # Add newly detected sensors to the lists of available sensors
        for key, value in new_float_sensors.items():
            if key not in self.data[FLOAT_DICT]:
                added_sensor_count += 1
                self.data[FLOAT_DICT][key] = value

        for key, value in new_switches.items():
            if key not in self.data[SWITCHES_DICT]:
                added_sensor_count += 1
                self.data[SWITCHES_DICT][key] = value

        for key, value in new_text_sensors.items():
            if key not in self.data[TEXT_DICT]:
                added_sensor_count += 1
                self.data[TEXT_DICT][key] = value

        for key, value in new_writable_sensors.items():
            if key not in self.data[WRITABLE_DICT]:
                added_sensor_count += 1
                self.data[WRITABLE_DICT][key] = value

        return added_sensor_count

    def _handle_deleted_sensors(
        self,
        new_float_sensors: dict,
        new_switches: dict,
        new_text_sensors: dict,
        new_writable_sensors: dict,
    ):
        deleted_sensor_count = 0
        # Delete sensors which are no longer available
        for key in list(self.data[FLOAT_DICT].keys()):
            # Loop over a copy of the keys of the dict to be able to delete items in-place
            if key not in new_float_sensors:
                deleted_sensor_count += 1
                if key in self.data[CHOSEN_FLOAT_SENSORS]:
                    # Remember deleted chosen sensors to be able to show them to the user later
                    self.data[CHOSEN_FLOAT_SENSORS].remove(key)
                    self.unavailable_sensors[key] = self.data[FLOAT_DICT][key]
                del self.data[FLOAT_DICT][key]

        for key in list(self.data[SWITCHES_DICT].keys()):
            # Loop over a copy of the keys of the dict to be able to delete items in-place
            if key not in new_switches:
                deleted_sensor_count += 1
                if key in self.data[CHOSEN_SWITCHES]:
                    # Remember deleted chosen sensors to be able to show them to the user later
                    self.data[CHOSEN_SWITCHES].remove(key)
                    self.unavailable_sensors[key] = self.data[SWITCHES_DICT][key]
                del self.data[SWITCHES_DICT][key]

        for key in list(self.data[TEXT_DICT].keys()):
            # Loop over a copy of the keys of the dict to be able to delete items in-place
            if key not in new_text_sensors:
                deleted_sensor_count += 1
                if key in self.data[CHOSEN_TEXT_SENSORS]:
                    # Remember deleted chosen sensors to be able to show them to the user later
                    self.data[CHOSEN_TEXT_SENSORS].remove(key)
                    self.unavailable_sensors[key] = self.data[TEXT_DICT][key]
                del self.data[TEXT_DICT][key]

        for key in list(self.data[WRITABLE_DICT].keys()):
            # Loop over a copy of the keys of the dict to be able to delete items in-place
            if key not in new_writable_sensors:
                deleted_sensor_count += 1
                if key in self.data[CHOSEN_WRITABLE_SENSORS]:
                    # Remember deleted chosen sensors to be able to show them to the user later
                    self.data[CHOSEN_WRITABLE_SENSORS].remove(key)
                    self.unavailable_sensors[key] = self.data[WRITABLE_DICT][key]
                del self.data[WRITABLE_DICT][key]

        return deleted_sensor_count

    def _handle_sensor_value_updates_from_enumeration(
        self,
        new_float_sensors: dict,
        new_switches: dict,
        new_text_sensors: dict,
        new_writable_sensors: dict,
    ):
        try:
            for key in self.data[FLOAT_DICT]:
                self.data[FLOAT_DICT][key]["value"] = new_float_sensors[key]["value"]
            for key in self.data[SWITCHES_DICT]:
                self.data[SWITCHES_DICT][key]["value"] = new_switches[key]["value"]
            for key in self.data[TEXT_DICT]:
                self.data[TEXT_DICT][key]["value"] = new_text_sensors[key]["value"]
            for key in self.data[WRITABLE_DICT]:
                self.data[WRITABLE_DICT][key]["value"] = new_writable_sensors[key][
                    "value"
                ]
        except Exception:
            _LOGGER.exception("Exception while updating sensor values")

    async def _update_data_structures(self):
        # Make a copy of the data structure to make sure we don't alter the original data
        for key in [
            CONF_HOST,
            CONF_PORT,
            FLOAT_DICT,
            SWITCHES_DICT,
            TEXT_DICT,
            WRITABLE_DICT,
            CHOSEN_FLOAT_SENSORS,
            CHOSEN_SWITCHES,
            CHOSEN_TEXT_SENSORS,
            CHOSEN_WRITABLE_SENSORS,
            FORCE_LEGACY_MODE,
        ]:
            self.data[key] = copy.copy(
                self.hass.data[DOMAIN][self.config_entry.entry_id][key]  # pyright: ignore[reportOptionalMemberAccess]
            )
        (
            self.data[CHOSEN_FLOAT_SENSORS],
            self.data[CHOSEN_SWITCHES],
            self.data[CHOSEN_TEXT_SENSORS],
            self.data[CHOSEN_WRITABLE_SENSORS],
        ) = _sanitize_selected_entity_ids(
            self.data[CHOSEN_FLOAT_SENSORS],
            self.data[CHOSEN_SWITCHES],
            self.data[CHOSEN_TEXT_SENSORS],
            self.data[CHOSEN_WRITABLE_SENSORS],
        )
        # ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION can be unset, so we have to handle it separately
        self.data[ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION] = self.hass.data[
            DOMAIN
        ][self.config_entry.entry_id].get(  # pyright: ignore[reportOptionalMemberAccess]
            ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION, []
        )
        self.data[MAX_PARALLEL_REQUESTS] = self.max_parallel_requests

        if self.enumerate_new_endpoints:
            _LOGGER.info("Discovering new endpoints")
            (
                new_float_sensors,
                new_switches,
                new_text_sensors,
                new_writable_sensors,
            ) = await self._get_possible_endpoints(
                self.data[CONF_HOST], self.data[CONF_PORT], self.data[FORCE_LEGACY_MODE]
            )

            added_sensor_count = self._handle_new_sensors(
                new_float_sensors, new_switches, new_text_sensors, new_writable_sensors
            )
            _LOGGER.info("Added %i new sensors", added_sensor_count)

            deleted_sensor_count = self._handle_deleted_sensors(
                new_float_sensors, new_switches, new_text_sensors, new_writable_sensors
            )
            _LOGGER.info("Deleted %i unavailable sensors", deleted_sensor_count)

            self._handle_sensor_value_updates_from_enumeration(
                new_float_sensors, new_switches, new_text_sensors, new_writable_sensors
            )
            _LOGGER.info("Updated sensor values")

        elif self.update_sensor_values:
            # Update current sensor values only if requested and no re-enumeration is running.
            await self._update_sensor_values()

        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Manage the options."""
        entity_registry = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(
            entity_registry,
            self.config_entry.entry_id,  # pyright: ignore[reportOptionalMemberAccess]
        )

        # If a sensor has been moved to a different category when updating the lists of sensors, it will is deleted from the chosen_*_sensors lists.
        # However, if the entity id is still the same the sensor may be moved to the correct category here.
        entity_map_sensors = {
            e.unique_id: e for e in entries if e.unique_id in self.data[FLOAT_DICT]
        }
        entity_map_switches = {
            e.unique_id: e for e in entries if e.unique_id in self.data[SWITCHES_DICT]
        }
        entity_map_text_sensors = {
            e.unique_id: e for e in entries if e.unique_id in self.data[TEXT_DICT]
        }
        entity_map_writable_sensors = {
            e.unique_id: e for e in entries if e.unique_id in self.data[WRITABLE_DICT]
        }

        if user_input is not None:
            self.auto_select_all_entities = user_input.get(
                AUTO_SELECT_ALL_ENTITIES, False
            )
            selected_float_sensors = (
                list(self.data[FLOAT_DICT].keys())
                if self.auto_select_all_entities
                else user_input[CHOSEN_FLOAT_SENSORS]
            )
            selected_switches = (
                list(self.data[SWITCHES_DICT].keys())
                if self.auto_select_all_entities
                else user_input[CHOSEN_SWITCHES]
            )
            selected_text_sensors = (
                list(self.data[TEXT_DICT].keys())
                if self.auto_select_all_entities
                else user_input[CHOSEN_TEXT_SENSORS]
            )
            selected_writable_sensors = (
                list(self.data[WRITABLE_DICT].keys())
                if self.auto_select_all_entities
                else user_input[CHOSEN_WRITABLE_SENSORS]
            )
            (
                selected_float_sensors,
                selected_switches,
                selected_text_sensors,
                selected_writable_sensors,
            ) = _sanitize_selected_entity_ids(
                selected_float_sensors,
                selected_switches,
                selected_text_sensors,
                selected_writable_sensors,
            )
            removed_entities = [
                entity_map_sensors[entity_id]
                for entity_id in entity_map_sensors
                if entity_id not in selected_float_sensors
            ]
            removed_entities.extend(
                [
                    entity_map_switches[entity_id]
                    for entity_id in entity_map_switches
                    if entity_id not in selected_switches
                ]
            )
            removed_entities.extend(
                [
                    entity_map_text_sensors[entity_id]
                    for entity_id in entity_map_text_sensors
                    if entity_id not in selected_text_sensors
                ]
            )
            removed_entities.extend(
                [
                    entity_map_writable_sensors[entity_id]
                    for entity_id in entity_map_writable_sensors
                    if entity_id not in selected_writable_sensors
                ]
            )
            for e in removed_entities:
                # Unregister from HA
                entity_registry.async_remove(e.entity_id)

            data = {
                CHOSEN_FLOAT_SENSORS: selected_float_sensors,
                CHOSEN_SWITCHES: selected_switches,
                CHOSEN_TEXT_SENSORS: selected_text_sensors,
                CHOSEN_WRITABLE_SENSORS: selected_writable_sensors,
                FLOAT_DICT: self.data[FLOAT_DICT],
                SWITCHES_DICT: self.data[SWITCHES_DICT],
                TEXT_DICT: self.data[TEXT_DICT],
                WRITABLE_DICT: self.data[WRITABLE_DICT],
                MAX_PARALLEL_REQUESTS: self.data[MAX_PARALLEL_REQUESTS],
                CONF_HOST: self.data[CONF_HOST],
                CONF_PORT: self.data[CONF_PORT],
                ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION: self.data[
                    ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION
                ],
                FORCE_LEGACY_MODE: self.data[FORCE_LEGACY_MODE],
            }

            # only show advanced options for writable sensors that do not have a custom unit like time sensors
            self.advanced_options_writable_sensors = [
                entity
                for entity in data[CHOSEN_WRITABLE_SENSORS]
                if data[WRITABLE_DICT][entity]["unit"] not in CUSTOM_UNITS
            ]

            # If the user selected at least one writable sensor, show
            # an additional options page to configure advanced settings.
            if len(self.advanced_options_writable_sensors) > 0:
                # store interim data and show extra options step
                self.data = data
                return await self.async_step_advanced_options()

            return self.async_create_entry(title="", data=data)

        return await self._show_config_form_endpoint(
            list(entity_map_sensors.keys()),
            list(entity_map_switches.keys()),
            list(entity_map_text_sensors.keys()),
            list(entity_map_writable_sensors.keys()),
        )

    async def async_step_advanced_options(self, user_input=None):
        """Handle the advanced options step (only if writable sensors are selected for now)."""

        if user_input is not None:
            self.data[ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION] = user_input[
                ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION
            ]

            return self.async_create_entry(title="", data=self.data)

        return await self._show_advanced_options_screen()

    async def _show_advanced_options_screen(self):
        """Show the extra options form for writable sensors."""

        # don't show errors from previous pages here
        self._errors = {}

        return self.async_show_form(
            step_id="advanced_options",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION,
                        default=self.data.get(
                            ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION, []
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=key,
                                    label=f"{self.data[WRITABLE_DICT][key]['friendly_name']} ({self.data[WRITABLE_DICT][key]['value']} {self.data[WRITABLE_DICT][key]['unit'] if self.data[WRITABLE_DICT][key]['unit'] not in INVISIBLE_UNITS else ''})",
                                )
                                for key in self.advanced_options_writable_sensors
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            multiple=True,
                        )
                    ),
                }
            ),
            errors=self._errors,
        )

    async def _show_config_form_endpoint(
        self,
        current_chosen_sensors,
        current_chosen_switches,
        current_chosen_text_sensors,
        current_chosen_writable_sensors,
    ):
        """Show the configuration form to select which endpoints should become entities."""
        if len(self.unavailable_sensors) > 0:
            self._errors["base"] = "unavailable_sensors"

        float_count = len(self.data[FLOAT_DICT])
        switch_count = len(self.data[SWITCHES_DICT])
        text_count = len(self.data[TEXT_DICT])
        writable_count = len(self.data[WRITABLE_DICT])
        count_placeholders = _build_discovered_entity_placeholders(
            float_count, switch_count, text_count, writable_count
        )

        schema = {
            vol.Required(
                AUTO_SELECT_ALL_ENTITIES, default=self.auto_select_all_entities
            ): cv.boolean,
            vol.Optional(
                CHOSEN_FLOAT_SENSORS, default=current_chosen_sensors
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=key,
                            label=f"{self.data[FLOAT_DICT][key]['friendly_name']} ({self.data[FLOAT_DICT][key]['value']} {self.data[FLOAT_DICT][key]['unit'] if self.data[FLOAT_DICT][key]['unit'] not in INVISIBLE_UNITS else ''})",
                        )
                        for key in self.data[FLOAT_DICT]
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    multiple=True,
                )
            ),
            vol.Optional(
                CHOSEN_SWITCHES, default=current_chosen_switches
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=key,
                            label=f"{self.data[SWITCHES_DICT][key]['friendly_name']} ({self.data[SWITCHES_DICT][key]['value']})",
                        )
                        for key in self.data[SWITCHES_DICT]
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    multiple=True,
                )
            ),
            vol.Optional(
                CHOSEN_TEXT_SENSORS, default=current_chosen_text_sensors
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=key,
                            label=f"{self.data[TEXT_DICT][key]['friendly_name']} ({self.data[TEXT_DICT][key]['value']})",
                        )
                        for key in self.data[TEXT_DICT]
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    multiple=True,
                )
            ),
            vol.Optional(
                CHOSEN_WRITABLE_SENSORS, default=current_chosen_writable_sensors
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=key,
                            label=f"{self.data[WRITABLE_DICT][key]['friendly_name']} ({self.data[WRITABLE_DICT][key]['value']} {self.data[WRITABLE_DICT][key]['unit'] if self.data[WRITABLE_DICT][key]['unit'] not in INVISIBLE_UNITS else ''})",
                        )
                        for key in self.data[WRITABLE_DICT]
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    multiple=True,
                )
            ),
        }

        if len(self.unavailable_sensors) > 0:
            # Add list of unavailable sensors to the schema if necessary
            unavailable_sensor_keys = "\n\n".join(
                [
                    f"{value['friendly_name']}\n ({key})"
                    for key, value in self.unavailable_sensors.items()
                ]
            )
            schema.update(
                {
                    vol.Optional(
                        "unavailable_sensors", default=unavailable_sensor_keys
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            multiline=True,
                        )
                    ),
                }
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema),
            errors=self._errors,
            description_placeholders=count_placeholders,
        )
