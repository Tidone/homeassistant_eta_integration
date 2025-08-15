"""Adds config flow for Blueprint."""

import copy
import logging
import voluptuous as vol
from homeassistant import config_entries
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
    CHOSEN_DEVICES,
    DATA_UPDATE_COORDINATOR,
    FORCE_LEGACY_MODE,
    FORCE_SENSOR_DETECTION,
    ENABLE_DEBUG_LOGGING,
    INVISIBLE_UNITS,
)

_LOGGER = logging.getLogger(__name__)


class EtaFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Eta."""

    VERSION = 5
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        """Initialize."""
        self._errors = {}
        self.data = {}
        self.options = {}
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
                    return await self._show_config_form_user(user_input)
                if user_input[FORCE_LEGACY_MODE]:
                    self._errors["base"] = "legacy_mode_selected"

                if user_input[ENABLE_DEBUG_LOGGING]:
                    self._old_logging_level = _LOGGER.parent.getEffectiveLevel()
                    _LOGGER.parent.setLevel(logging.DEBUG)

                self.data = user_input
                self.data["possible_devices"] = await self._get_possible_devices(
                    user_input[CONF_HOST], user_input[CONF_PORT]
                )

                if not self.data["possible_devices"]:
                    self._errors["base"] = "no_devices_found"
                    return await self._show_config_form_user(user_input)
                return await self.async_step_confirm_scan()
            else:
                self._errors["base"] = (
                    "no_eta_endpoint" if valid == 0 else "unknown_host"
                )

            return await self._show_config_form_user(user_input)

        user_input = {}
        # Provide defaults for form
        user_input[CONF_HOST] = "192.168.60.199"
        user_input[CONF_PORT] = "49999"

        return await self._show_config_form_user(user_input)

    async def async_step_confirm_scan(self, user_input=None):
        """Step to confirm the scan of all devices."""
        if user_input is not None:
            self.data["devices_to_scan"] = self.data["possible_devices"].copy()
            self.data["scanned_devices_data"] = {}
            return await self.async_step_scan_device()

        devices = self.data.get("possible_devices", [])
        return self.async_show_form(
            step_id="confirm_scan",
            description_placeholders={"devices": ", ".join(devices)},
            data_schema=vol.Schema({}),
        )

    async def _scan_device(self, device_name: str):
        """Scan a device and get all its entities."""
        session = async_get_clientsession(self.hass)
        eta_client = EtaAPI(session, self.data[CONF_HOST], self.data[CONF_PORT])

        entities = {
            FLOAT_DICT: {},
            SWITCHES_DICT: {},
            TEXT_DICT: {},
            WRITABLE_DICT: {},
        }

        async def traverse_and_scan(node):
            if not node:
                return

            if uri := node.get("uri"):
                try:
                    metadata = await eta_client.async_get_entity_metadata(uri)
                    if metadata:
                        entity_type = eta_client.classify_entity(metadata)
                        if entity_type == "sensor":
                            if metadata.get("unit") == "":
                                entities[TEXT_DICT][uri] = metadata
                            else:
                                entities[FLOAT_DICT][uri] = metadata
                        elif entity_type == "switch":
                            entities[SWITCHES_DICT][uri] = metadata
                        elif entity_type in ("number", "time"):
                            entities[WRITABLE_DICT][uri] = metadata
                except Exception as e:
                    _LOGGER.warning(f"Could not scan URI {uri}: {e}")

            if children := node.get("children"):
                for child in children:
                    await traverse_and_scan(child)

        structure = await eta_client.get_entity_structure(device_name)
        await traverse_and_scan(structure)

        return entities

    async def async_step_scan_device(self, user_input=None):
        """Step to scan a single device."""
        if not self.data.get("devices_to_scan"):
            # All devices scanned, move to device selection
            self.data[CHOSEN_DEVICES] = self.data["possible_devices"]
            return await self.async_step_select_device()

        device_to_scan = self.data["devices_to_scan"][0]

        if user_input is not None:
            scanned_data = await self._scan_device(device_to_scan)
            self.data["scanned_devices_data"][device_to_scan] = scanned_data

            # Remove the scanned device from the list
            self.data["devices_to_scan"].pop(0)

            # Move to the next device or finish
            return await self.async_step_scan_device()

        return self.async_show_form(
            step_id="scan_device",
            description_placeholders={"device": device_to_scan},
            data_schema=vol.Schema({}),
            last_step=len(self.data["devices_to_scan"]) == 1,
        )

    async def async_step_select_device(self, user_input=None):
        """Step to select a device to configure."""
        if user_input is not None:
            if user_input["device"] == "finish_setup":
                return self.async_create_entry(
                    title=f"ETA at {self.data[CONF_HOST]}",
                    data=self.data,
                    options=self.options,
                )
            self.device_name = user_input["device"]
            return await self.async_step_select_entities()

        devices = self.data.get(CHOSEN_DEVICES, [])
        options = [
            selector.SelectOptionDict(value=device, label=device) for device in devices
        ]
        options.append(
            selector.SelectOptionDict(value="finish_setup", label="Finish Setup")
        )

        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema(
                {
                    vol.Required("device"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_select_entities(self, user_input=None):
        """Step to select entities for a specific device."""
        if user_input is not None:
            # Get all entities for the device from our scanned data
            device_data = self.data["scanned_devices_data"][self.device_name]
            all_entities = {
                **device_data.get(FLOAT_DICT, {}),
                **device_data.get(SWITCHES_DICT, {}),
                **device_data.get(TEXT_DICT, {}),
                **device_data.get(WRITABLE_DICT, {}),
            }

            chosen_for_device = user_input.get("chosen_entities", [])

            # Initialize options lists if they don't exist
            self.options.setdefault(CHOSEN_FLOAT_SENSORS, [])
            self.options.setdefault(CHOSEN_SWITCHES, [])
            self.options.setdefault(CHOSEN_TEXT_SENSORS, [])
            self.options.setdefault(CHOSEN_WRITABLE_SENSORS, [])

            # Use a dummy API client just for classify_entity
            session = async_get_clientsession(self.hass)
            eta_client = EtaAPI(session, self.data[CONF_HOST], self.data[CONF_PORT])

            # Clear out previous selections for THIS DEVICE ONLY
            device_entity_keys = all_entities.keys()
            for category_list in self.options.values():
                for entity_key in list(category_list):
                    if entity_key in device_entity_keys:
                        category_list.remove(entity_key)

            # Add back the new selections for this device
            for key in chosen_for_device:
                entity = all_entities[key]
                entity_type = eta_client.classify_entity(entity)
                if entity_type == "sensor":
                    if entity.get("unit") == "":
                        self.options[CHOSEN_TEXT_SENSORS].append(key)
                    else:
                        self.options[CHOSEN_FLOAT_SENSORS].append(key)
                elif entity_type == "switch":
                    self.options[CHOSEN_SWITCHES].append(key)
                elif entity_type in ("number", "time"):
                    self.options[CHOSEN_WRITABLE_SENSORS].append(key)


            return await self.async_step_select_device()

        # Get all entities for the device from our scanned data
        device_data = self.data["scanned_devices_data"][self.device_name]
        all_entities = {
            **device_data.get(FLOAT_DICT, {}),
            **device_data.get(SWITCHES_DICT, {}),
            **device_data.get(TEXT_DICT, {}),
            **device_data.get(WRITABLE_DICT, {}),
        }

        # Determine currently selected entities for this device
        default_selected = [
            key for key in all_entities if key in self.options.get(CHOSEN_FLOAT_SENSORS, [])
        ]
        default_selected.extend(
            [key for key in all_entities if key in self.options.get(CHOSEN_SWITCHES, [])]
        )
        default_selected.extend(
            [key for key in all_entities if key in self.options.get(CHOSEN_TEXT_SENSORS, [])]
        )
        default_selected.extend(
            [key for key in all_entities if key in self.options.get(CHOSEN_WRITABLE_SENSORS, [])]
        )


        return self.async_show_form(
            step_id="select_entities",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "chosen_entities",
                        default=default_selected,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=key, label=entity["friendly_name"]
                                )
                                for key, entity in all_entities.items()
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            multiple=True,
                        )
                    ),
                }
            ),
            description_placeholders={"device_name": self.device_name},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EtaOptionsFlowHandler(config_entry)

    async def _show_config_form_user(
        self, user_input
    ):  # pylint: disable=unused-argument
        """Show the configuration form to edit host and port data."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=user_input[CONF_HOST]): str,  #
                    vol.Required(CONF_PORT, default=user_input[CONF_PORT]): str,
                    vol.Required(FORCE_LEGACY_MODE, default=False): cv.boolean,
                    vol.Required(ENABLE_DEBUG_LOGGING, default=False): cv.boolean,
                }
            ),
            errors=self._errors,
        )

    async def _show_config_form_endpoint(
        self,
        current_chosen_sensors=[],
        current_chosen_switches=[],
        current_chosen_text_sensors=[],
        current_chosen_writable_sensors=[],
    ):
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
                                    label=f"{sensors_dict[key]['friendly_name']} ({sensors_dict[key]['value']} {sensors_dict[key]['unit'] if sensors_dict[key]['unit'] not in INVISIBLE_UNITS else ""})",
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
                                    label=f"{writable_dict[key]['friendly_name']} ({writable_dict[key]['value']} {writable_dict[key]['unit'] if writable_dict[key]['unit'] not in INVISIBLE_UNITS else ""})",
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

    async def _get_possible_devices(self, host, port) -> list[str]:
        """Get a list of possible devices (fubs) from the ETA API."""
        session = async_get_clientsession(self.hass)
        eta_client = EtaAPI(session, host, port)
        try:
            menu = await eta_client.get_menu()
            raw_devices = menu["eta"]["menu"]["fub"]
            if not isinstance(raw_devices, list):
                raw_devices = [raw_devices]
            return [device["@name"] for device in raw_devices if "@name" in device]
        except Exception as e:
            _LOGGER.error(f"Error getting devices from ETA API: {e}")
            return []

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


class EtaOptionsFlowHandler(config_entries.OptionsFlow):
    """Blueprint config flow options handler."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.data = {}
        self._errors = {}
        self.device_name = None

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Manage the options."""
        self.data = self.config_entry.data
        self.device_name = self.context.get("device") if self.context else None
        self._errors = {}

        if self.device_name:
            return await self.async_step_select_entities()
        else:
            return await self.async_step_select_device()

    async def async_step_select_device(self, user_input=None):
        """Step to select a device to configure."""
        if user_input is not None:
            self.device_name = user_input["device"]
            return await self.async_step_select_entities()

        devices = self.config_entry.data.get(CHOSEN_DEVICES, [])
        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema(
                {
                    vol.Required("device"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=device, label=device)
                                for device in devices
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_select_entities(self, user_input=None):
        """Step to select entities for a specific device."""
        if user_input is not None:
            # Get existing options
            options = self.config_entry.options.copy()

            # Get all entities for the device
            device_data = self.hass.data[DOMAIN][self.config_entry.entry_id][
                self.device_name
            ].data
            all_entities = {
                **device_data.get(FLOAT_DICT, {}),
                **device_data.get(SWITCHES_DICT, {}),
                **device_data.get(TEXT_DICT, {}),
                **device_data.get(WRITABLE_DICT, {}),
            }

            # Update chosen entities for this device
            chosen_for_device = user_input.get("chosen_entities", [])

            # Helper to update a chosen list
            def update_chosen_list(chosen_list, entity_key, entity_type, expected_type):
                is_chosen = entity_key in chosen_for_device
                is_in_list = entity_key in chosen_list

                if is_chosen and not is_in_list and entity_type == expected_type:
                    chosen_list.append(entity_key)
                elif not is_chosen and is_in_list:
                    chosen_list.remove(entity_key)

            session = async_get_clientsession(self.hass)
            eta_client = EtaAPI(
                session,
                self.config_entry.data[CONF_HOST],
                self.config_entry.data[CONF_PORT],
            )
            for key, entity in all_entities.items():
                entity_type = eta_client.classify_entity(entity)
                update_chosen_list(
                    options.get(CHOSEN_FLOAT_SENSORS, []),
                    key,
                    entity_type,
                    "sensor",
                )
                update_chosen_list(
                    options.get(CHOSEN_SWITCHES, []), key, entity_type, "switch"
                )
                update_chosen_list(
                    options.get(CHOSEN_WRITABLE_SENSORS, []),
                    key,
                    entity_type,
                    "number",
                )
                update_chosen_list(
                    options.get(CHOSEN_WRITABLE_SENSORS, []),
                    key,
                    entity_type,
                    "time",
                )

            return self.async_create_entry(title="", data=options)

        device_data = self.hass.data[DOMAIN][self.config_entry.entry_id][
            self.device_name
        ].data
        all_entities = {
            **device_data.get(FLOAT_DICT, {}),
            **device_data.get(SWITCHES_DICT, {}),
            **device_data.get(TEXT_DICT, {}),
            **device_data.get(WRITABLE_DICT, {}),
        }

        return self.async_show_form(
            step_id="select_entities",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "chosen_entities",
                        default=[
                            *self.config_entry.options.get(CHOSEN_FLOAT_SENSORS, []),
                            *self.config_entry.options.get(CHOSEN_SWITCHES, []),
                            *self.config_entry.options.get(CHOSEN_TEXT_SENSORS, []),
                            *self.config_entry.options.get(CHOSEN_WRITABLE_SENSORS, []),
                        ],
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=key, label=entity["friendly_name"]
                                )
                                for key, entity in all_entities.items()
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            multiple=True,
                        )
                    ),
                }
            ),
            description_placeholders={"device_name": self.device_name},
        )
