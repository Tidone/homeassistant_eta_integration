"""Adds config flow for Blueprint."""

import copy
import logging
import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, OptionsFlow, CONN_CLASS_CLOUD_POLL
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.entity_registry import (
    async_entries_for_config_entry,
    async_get,
)
import homeassistant.helpers.config_validation as cv
from .api import ETAEndpoint, EtaAPI
from .const import (
    DOMAIN,
    FLOAT_DICT,
    SWITCHES_DICT,
    TEXT_DICT,
    WRITABLE_DICT,
    CHOSEN_FLOAT_SENSORS,
    CHOSEN_SWITCHES,
    CHOSEN_TEXT_SENSORS,
    CHOSEN_WRITABLE_SENSORS,
    FORCE_LEGACY_MODE,
    FORCE_SENSOR_DETECTION,
    ENABLE_DEBUG_LOGGING,
    INVISIBLE_UNITS,
)

_LOGGER = logging.getLogger(__name__)


class EtaFlowHandler(ConfigFlow, domain=DOMAIN):
    """Config flow for Eta."""

    VERSION = 5
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

                if user_input[ENABLE_DEBUG_LOGGING]:
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
            else:
                self._errors["base"] = (
                    "no_eta_endpoint" if valid == 0 else "unknown_host"
                )

            return await self._show_config_form_user(user_input)

        user_input = {}
        # Provide defaults for form
        user_input[CONF_HOST] = "0.0.0.0"
        user_input[CONF_PORT] = "8080"

        return await self._show_config_form_user(user_input)

    async def async_step_select_entities(self, user_input: dict = None):
        """Second step in config flow to add a repo to watch."""
        if user_input is not None:
            # add chosen entities to data
            self.data[CHOSEN_FLOAT_SENSORS] = user_input.get(CHOSEN_FLOAT_SENSORS, [])
            self.data[CHOSEN_SWITCHES] = user_input.get(CHOSEN_SWITCHES, [])
            self.data[CHOSEN_TEXT_SENSORS] = user_input.get(CHOSEN_TEXT_SENSORS, [])
            self.data[CHOSEN_WRITABLE_SENSORS] = user_input.get(
                CHOSEN_WRITABLE_SENSORS, []
            )

            # Restore old logging level
            if self._old_logging_level != logging.NOTSET:
                _LOGGER.parent.setLevel(self._old_logging_level)

            # User is done, create the config entry.
            return self.async_create_entry(
                title=f"ETA at {self.data[CONF_HOST]}", data=self.data
            )

        return await self._show_config_form_endpoint()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
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

        return self.async_show_form(
            step_id="select_entities",
            data_schema=vol.Schema(
                {
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
        except:
            return -1
        return 1 if does_endpoint_exist else 0

    async def _is_correct_api_version(self, host, port):
        session = async_get_clientsession(self.hass)
        eta_client = EtaAPI(session, host, port)

        return await eta_client.is_correct_api_version()


class EtaOptionsFlowHandler(OptionsFlow):
    """Blueprint config flow options handler."""

    @property
    def config_entry(self):
        return self.hass.config_entries.async_get_entry(self.handler)

    def __init__(self) -> None:
        """Initialize HACS options flow."""
        self.data = {}
        self._errors = {}

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

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        self.data = self.hass.data[DOMAIN][self.config_entry.entry_id]

        # query the list of writable sensors if it is currently empty
        # this happens if a user updates from config v1 (pre-writable-sensors) to v2
        if len(self.data[WRITABLE_DICT]) == 0:
            _, _, _, self.data[WRITABLE_DICT] = await self._get_possible_endpoints(
                self.data[CONF_HOST], self.data[CONF_PORT], self.data[FORCE_LEGACY_MODE]
            )

        if self.data.get(FORCE_SENSOR_DETECTION, False):
            _LOGGER.info("Forcing new endpoint discovery")
            self.data[FORCE_SENSOR_DETECTION] = False
            (
                new_float_sensors,
                new_switches,
                new_text_sensors,
                new_writable_sensors,
            ) = await self._get_possible_endpoints(
                self.data[CONF_HOST], self.data[CONF_PORT], self.data[FORCE_LEGACY_MODE]
            )
            added_sensor_count = 0
            # Add newly detected sensors without changing the old ones
            for key in new_float_sensors:
                if key not in self.data[FLOAT_DICT]:
                    added_sensor_count += 1
                    self.data[FLOAT_DICT][key] = new_float_sensors[key]

            for key in new_switches:
                if key not in self.data[SWITCHES_DICT]:
                    added_sensor_count += 1
                    self.data[SWITCHES_DICT][key] = new_switches[key]

            for key in new_text_sensors:
                if key not in self.data[TEXT_DICT]:
                    added_sensor_count += 1
                    self.data[TEXT_DICT][key] = new_text_sensors[key]

            for key in new_writable_sensors:
                if key not in self.data[WRITABLE_DICT]:
                    added_sensor_count += 1
                    self.data[WRITABLE_DICT][key] = new_writable_sensors[key]

            _LOGGER.info("Added %i new sensors", added_sensor_count)

        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Manage the options."""
        entity_registry = async_get(self.hass)
        entries = async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )

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
            removed_entities = [
                entity_map_sensors[entity_id]
                for entity_id in entity_map_sensors
                if entity_id not in user_input[CHOSEN_FLOAT_SENSORS]
            ]
            removed_entities.extend(
                [
                    entity_map_switches[entity_id]
                    for entity_id in entity_map_switches
                    if entity_id not in user_input[CHOSEN_SWITCHES]
                ]
            )
            removed_entities.extend(
                [
                    entity_map_text_sensors[entity_id]
                    for entity_id in entity_map_text_sensors
                    if entity_id not in user_input[CHOSEN_TEXT_SENSORS]
                ]
            )
            removed_entities.extend(
                [
                    entity_map_writable_sensors[entity_id]
                    for entity_id in entity_map_writable_sensors
                    if entity_id not in user_input[CHOSEN_WRITABLE_SENSORS]
                ]
            )
            for e in removed_entities:
                # Unregister from HA
                entity_registry.async_remove(e.entity_id)

            data = {
                CHOSEN_FLOAT_SENSORS: user_input[CHOSEN_FLOAT_SENSORS],
                CHOSEN_SWITCHES: user_input[CHOSEN_SWITCHES],
                CHOSEN_TEXT_SENSORS: user_input[CHOSEN_TEXT_SENSORS],
                CHOSEN_WRITABLE_SENSORS: user_input[CHOSEN_WRITABLE_SENSORS],
                FLOAT_DICT: self.data[FLOAT_DICT],
                SWITCHES_DICT: self.data[SWITCHES_DICT],
                TEXT_DICT: self.data[TEXT_DICT],
                WRITABLE_DICT: self.data[WRITABLE_DICT],
                CONF_HOST: self.data[CONF_HOST],
                CONF_PORT: self.data[CONF_PORT],
            }

            return self.async_create_entry(title="", data=data)
        return await self._show_config_form_endpoint(
            list(entity_map_sensors.keys()),
            list(entity_map_switches.keys()),
            list(entity_map_text_sensors.keys()),
            list(entity_map_writable_sensors.keys()),
        )

    async def _show_config_form_endpoint(
        self,
        current_chosen_sensors,
        current_chosen_switches,
        current_chosen_text_sensors,
        current_chosen_writable_sensors,
    ):
        """Show the configuration form to select which endpoints should become entities."""
        # Create shallow copies of the dicts to make sure the del operators below won't delete the original data
        sensors_dict: dict[str, ETAEndpoint] = copy.copy(self.data[FLOAT_DICT])
        switches_dict: dict[str, ETAEndpoint] = copy.copy(self.data[SWITCHES_DICT])
        text_dict: dict[str, ETAEndpoint] = copy.copy(self.data[TEXT_DICT])
        writable_dict: dict[str, ETAEndpoint] = copy.copy(self.data[WRITABLE_DICT])

        session = async_get_clientsession(self.hass)
        eta_client = EtaAPI(session, self.data[CONF_HOST], self.data[CONF_PORT])

        is_correct_api_version = await eta_client.is_correct_api_version()
        if not is_correct_api_version:
            self._errors["base"] = "wrong_api_version"

        # Update current values
        for entity in list(sensors_dict.keys()):
            try:
                sensors_dict[entity]["value"], _ = await eta_client.get_data(
                    sensors_dict[entity]["url"]
                )
            except Exception:
                _LOGGER.error(
                    "Exception while updating the value for endpoint '%s' (%s), removing sensor from the lists",
                    sensors_dict[entity]["friendly_name"],
                    sensors_dict[entity]["url"],
                )
                del sensors_dict[entity]
                self._errors["base"] = "value_update_error"

        for entity in list(switches_dict.keys()):
            try:
                switches_dict[entity]["value"], _ = await eta_client.get_data(
                    switches_dict[entity]["url"]
                )
            except Exception:
                _LOGGER.error(
                    "Exception while updating the value for endpoint '%s' (%s), removing sensor from the lists",
                    switches_dict[entity]["friendly_name"],
                    switches_dict[entity]["url"],
                )
                del switches_dict[entity]
                self._errors["base"] = "value_update_error"
        for entity in list(text_dict.keys()):
            try:
                text_dict[entity]["value"], _ = await eta_client.get_data(
                    text_dict[entity]["url"]
                )
            except Exception:
                _LOGGER.error(
                    "Exception while updating the value for endpoint '%s' (%s), removing sensor from the lists",
                    text_dict[entity]["friendly_name"],
                    text_dict[entity]["url"],
                )
                del text_dict[entity]
                self._errors["base"] = "value_update_error"
        for entity in list(writable_dict.keys()):
            try:
                writable_dict[entity]["value"], _ = await eta_client.get_data(
                    writable_dict[entity]["url"]
                )
            except Exception:
                _LOGGER.error(
                    "Exception while updating the value for endpoint '%s' (%s), removing sensor from the lists",
                    writable_dict[entity]["friendly_name"],
                    writable_dict[entity]["url"],
                )
                del writable_dict[entity]
                self._errors["base"] = "value_update_error"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CHOSEN_FLOAT_SENSORS, default=current_chosen_sensors
                    ): selector.SelectSelector(
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
                    vol.Optional(
                        CHOSEN_SWITCHES, default=current_chosen_switches
                    ): selector.SelectSelector(
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
                    vol.Optional(
                        CHOSEN_TEXT_SENSORS, default=current_chosen_text_sensors
                    ): selector.SelectSelector(
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
                    vol.Optional(
                        CHOSEN_WRITABLE_SENSORS, default=current_chosen_writable_sensors
                    ): selector.SelectSelector(
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
        )
