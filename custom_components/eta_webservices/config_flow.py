"""Adds config flow for ETA Sensors."""

import asyncio
import copy
import ipaddress
import logging
import re

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
    CHOSEN_PENDING_SENSORS,
    CHOSEN_SWITCHES,
    CHOSEN_TEXT_SENSORS,
    CHOSEN_WRITABLE_SENSORS,
    CUSTOM_UNITS,
    DEFAULT_MAX_PARALLEL_REQUESTS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    ENABLE_DEBUG_LOGGING,
    FLOAT_DICT,
    FORCE_LEGACY_MODE,
    INVISIBLE_UNITS,
    MAX_PARALLEL_REQUESTS,
    OPTIONS_ACTION_PARALLEL_ONLY,
    OPTIONS_ACTION_REDISCOVER_AND_UPDATE,
    OPTIONS_ACTION_UPDATE_SELECTED,
    OPTIONS_UPDATE_ACTION,
    PENDING_DICT,
    SWITCHES_DICT,
    TEXT_DICT,
    UPDATE_INTERVAL,
    WRITABLE_DICT,
)

_LOGGER = logging.getLogger(__name__)
_HOSTNAME_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def _format_endpoint_label(endpoint: ETAEndpoint) -> str:
    """Format a display label for an endpoint selector option."""
    unit = endpoint.get("unit", "")
    if unit and unit not in INVISIBLE_UNITS:
        return f"{endpoint['friendly_name']} ({endpoint['value']} {unit})"
    return f"{endpoint['friendly_name']} ({endpoint['value']})"


def _build_discovered_entity_placeholders(
    float_count: int,
    switch_count: int,
    text_count: int,
    writable_count: int,
    pending_count: int,
) -> dict[str, str]:
    """Build placeholders for discovered entity counts."""
    total_count = (
        float_count + switch_count + text_count + writable_count + pending_count
    )
    return {
        "float_count": str(float_count),
        "switch_count": str(switch_count),
        "text_count": str(text_count),
        "writable_count": str(writable_count),
        "total_count": str(total_count),
        "pending_count": str(pending_count),
    }


def _build_endpoint_selection_schema(
    data: dict,
    auto_select_default: bool = False,
    defaults: dict | None = None,
    unavailable_sensors: dict | None = None,
) -> dict:
    """Build the voluptuous schema dict for the endpoint selection form.

    Args:
        data: The flow's data dict containing the sensor category dicts.
        auto_select_default: Default value for the AUTO_SELECT_ALL_ENTITIES toggle.
        defaults: Optional dict mapping CHOSEN_* const keys to pre-selected lists.
        unavailable_sensors: When non-empty, adds a read-only text field listing them.
    """
    defaults = defaults or {}
    float_dict: dict[str, ETAEndpoint] = data[FLOAT_DICT]
    switches_dict: dict[str, ETAEndpoint] = data[SWITCHES_DICT]
    text_dict: dict[str, ETAEndpoint] = data[TEXT_DICT]
    writable_dict: dict[str, ETAEndpoint] = data[WRITABLE_DICT]
    pending_dict: dict[str, ETAEndpoint] = data.get(PENDING_DICT, {})

    schema: dict = {
        vol.Required(AUTO_SELECT_ALL_ENTITIES, default=auto_select_default): cv.boolean,
        vol.Optional(
            CHOSEN_FLOAT_SENSORS,
            **(
                {}
                if CHOSEN_FLOAT_SENSORS not in defaults
                else {"default": defaults[CHOSEN_FLOAT_SENSORS]}
            ),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(
                        value=key, label=_format_endpoint_label(float_dict[key])
                    )
                    for key in float_dict
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
                multiple=True,
            )
        ),
        vol.Optional(
            CHOSEN_SWITCHES,
            **(
                {}
                if CHOSEN_SWITCHES not in defaults
                else {"default": defaults[CHOSEN_SWITCHES]}
            ),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(
                        value=key, label=_format_endpoint_label(switches_dict[key])
                    )
                    for key in switches_dict
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
                multiple=True,
            )
        ),
        vol.Optional(
            CHOSEN_TEXT_SENSORS,
            **(
                {}
                if CHOSEN_TEXT_SENSORS not in defaults
                else {"default": defaults[CHOSEN_TEXT_SENSORS]}
            ),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(
                        value=key, label=_format_endpoint_label(text_dict[key])
                    )
                    for key in text_dict
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
                multiple=True,
            )
        ),
        vol.Optional(
            CHOSEN_WRITABLE_SENSORS,
            **(
                {}
                if CHOSEN_WRITABLE_SENSORS not in defaults
                else {"default": defaults[CHOSEN_WRITABLE_SENSORS]}
            ),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(
                        value=key, label=_format_endpoint_label(writable_dict[key])
                    )
                    for key in writable_dict
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
                multiple=True,
            )
        ),
    }

    if pending_dict:
        current_chosen_pending = defaults.get(
            CHOSEN_PENDING_SENSORS, data.get(CHOSEN_PENDING_SENSORS, [])
        )
        schema[vol.Optional(CHOSEN_PENDING_SENSORS, default=current_chosen_pending)] = (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=key,
                            label=f"{pending_dict[key]['friendly_name']} (pending — activates automatically)",
                        )
                        for key in pending_dict
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    multiple=True,
                )
            )
        )

    if unavailable_sensors:
        unavailable_sensor_keys = "\n\n".join(
            [
                f"{value['friendly_name']}\n ({key})"
                for key, value in unavailable_sensors.items()
            ]
        )
        schema[vol.Optional("unavailable_sensors", default=unavailable_sensor_keys)] = (
            selector.TextSelector(
                selector.TextSelectorConfig(
                    multiline=True,
                )
            )
        )

    return schema


def _sanitize_selected_entity_ids(
    selected_float_sensors: list[str],
    selected_switches: list[str],
    selected_text_sensors: list[str],
    selected_writable_sensors: list[str],
    selected_pending_sensors: list[str],
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
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
    text_set = set(sanitized_text_sensors)
    sanitized_pending_sensors = [
        sensor_id
        for sensor_id in dict.fromkeys(selected_pending_sensors)
        if sensor_id not in float_set
        and sensor_id not in switch_set
        and sensor_id not in text_set
    ]
    sanitized_writable_sensors = list(dict.fromkeys(selected_writable_sensors))

    removed_from_switches = len(selected_switches) - len(sanitized_switches)
    removed_from_text_sensors = len(selected_text_sensors) - len(sanitized_text_sensors)
    removed_from_pending_sensors = len(selected_pending_sensors) - len(
        sanitized_pending_sensors
    )
    if (
        removed_from_switches > 0
        or removed_from_text_sensors > 0
        or removed_from_pending_sensors > 0
    ):
        _LOGGER.info(
            "Removed duplicate selected entity IDs across categories: "
            "switches=%d, text_sensors=%d, pending_sensors=%d",
            removed_from_switches,
            removed_from_text_sensors,
            removed_from_pending_sensors,
        )

    return (
        sanitized_float_sensors,
        sanitized_switches,
        sanitized_text_sensors,
        sanitized_writable_sensors,
        sanitized_pending_sensors,
    )


def _is_invalid_host_input(host: str) -> bool:
    """Return True if host input is malformed or unusable for ETA requests."""
    normalized_host = host.strip()
    if not normalized_host:
        return True

    # Users should only enter host/IP, never full URLs or paths.
    # This also prevents port forwarding via DDNS servies,
    # but leaving the ETA terminal accessible from the internet is a terrible idea anyway.
    if "/" in normalized_host:
        return True

    # Bracketed form is only valid for IPv6 literals like [2001:db8::1].
    if normalized_host.startswith("[") or normalized_host.endswith("]"):
        if not (normalized_host.startswith("[") and normalized_host.endswith("]")):
            return True
        inner_host = normalized_host[1:-1]
        try:
            parsed_ip = ipaddress.ip_address(inner_host)
        except ValueError:
            return True
        return parsed_ip.version != 6 or parsed_ip.is_unspecified

    # Unbracketed colon hosts are malformed for host:port URI construction.
    if ":" in normalized_host:
        return True

    # Accept valid IPv4 directly.
    try:
        return ipaddress.ip_address(normalized_host).is_unspecified
    except ValueError:
        pass

    # Otherwise require a valid hostname (RFC-like labels).
    if len(normalized_host) > 253:
        return True
    labels = normalized_host.rstrip(".").split(".")
    if not labels:
        return True
    if any(not label for label in labels):
        return True
    if any(_HOSTNAME_LABEL_RE.match(label) is None for label in labels):
        return True

    return False


class EtaFlowHandler(ConfigFlow, domain=DOMAIN):
    """Config flow for Eta."""

    VERSION = 7
    CONNECTION_CLASS = CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        """Initialize."""
        self._errors = {}
        self.data = {}
        self._old_logging_level = logging.NOTSET
        self._endpoint_discovery_task: asyncio.Task | None = None
        self._endpoint_discovery_error: str | None = None
        self._pending_user_error: str | None = None

    def _on_discovery_progress(self, message: str, progress: float | None) -> None:
        """Forward discovery progress updates to HA's progress tracking."""
        _LOGGER.debug("Discovery progress: %s", message)
        if progress is not None:
            self.async_update_progress(progress)

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}
        if self._pending_user_error is not None:
            self._errors["base"] = self._pending_user_error
            self._pending_user_error = None

        # Uncomment the next 2 lines if only a single instance of the integration is allowed:
        # if self._async_current_entries():
        #     return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            user_input[CONF_HOST] = str(user_input[CONF_HOST]).strip()
            if _is_invalid_host_input(user_input[CONF_HOST]):
                self._errors["base"] = "unknown_host"
                return await self._show_config_form_user(user_input)

            platform_entries = self._async_current_entries()
            for entry in platform_entries:
                if entry.data.get(CONF_HOST, "") == user_input[CONF_HOST]:
                    return self.async_abort(reason="single_instance_allowed")
            if user_input[ENABLE_DEBUG_LOGGING] and _LOGGER.parent is not None:
                self._old_logging_level = _LOGGER.parent.getEffectiveLevel()
                _LOGGER.parent.setLevel(logging.DEBUG)

            self.data = user_input
            self._endpoint_discovery_error = None
            self._endpoint_discovery_task = self.hass.async_create_task(
                self._async_validate_and_discover_endpoints(
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    user_input[FORCE_LEGACY_MODE],
                )
            )
            return await self.async_step_discover_entities()

        user_input = {}
        # Keep previously entered values when coming back from the progress screen.
        user_input[CONF_HOST] = self.data.get(CONF_HOST, "0.0.0.0")
        user_input[CONF_PORT] = self.data.get(CONF_PORT, "8080")

        return await self._show_config_form_user(user_input)

    @callback
    def async_remove(self) -> None:
        """Clean up resources if the config flow is aborted/removed."""
        if (
            self._endpoint_discovery_task is not None
            and not self._endpoint_discovery_task.done()
        ):
            self._endpoint_discovery_task.cancel()
        self._restore_logging_level()

    async def async_step_discover_entities(self, user_input=None):
        """Show a dedicated progress step while endpoint discovery runs."""
        if self._endpoint_discovery_task is None:
            return await self.async_step_user(self.data)

        if not self._endpoint_discovery_task.done():
            return self.async_show_progress(
                step_id="discover_entities",
                progress_action="discover_entities",
                progress_task=self._endpoint_discovery_task,
            )

        if self._endpoint_discovery_error is not None:
            self._restore_logging_level()
            self._pending_user_error = self._endpoint_discovery_error
            self._endpoint_discovery_task = None
            self._endpoint_discovery_error = None
            return self.async_show_progress_done(next_step_id="user")

        self._endpoint_discovery_task = None
        return self.async_show_progress_done(next_step_id="select_entities")

    async def _async_validate_and_discover_endpoints(
        self, host: str, port: str, force_legacy_mode: bool
    ) -> None:
        """Validate connectivity and discover endpoints in background."""
        self._on_discovery_progress("Testing ETA endpoint", 0.01)
        try:
            try:
                # Wait a bit to make sure the UI has finished the transition to the progress view before we do the connectivity test.
                # This should fix a race condition with the UI where the test finishes
                # before the progress dialog is fully shown, causing the progress stop signal to get lost
                # and the progress dialog to get stuck on a spinner indefinitely
                await asyncio.sleep(0.5)
                valid = await asyncio.wait_for(self._test_url(host, port), timeout=20)
            except TimeoutError:
                _LOGGER.warning("ETA endpoint connectivity check timed out after 20s")
                self._endpoint_discovery_error = "unknown_host"
                return
            except Exception:
                _LOGGER.exception("Unexpected error while validating ETA endpoint")
                self._endpoint_discovery_error = "unknown_host"
                return

            if valid != 1:
                self._endpoint_discovery_error = (
                    "no_eta_endpoint" if valid == 0 else "unknown_host"
                )
                return

            await self._async_discover_possible_endpoints(host, port, force_legacy_mode)
        except asyncio.CancelledError:
            self._endpoint_discovery_error = None
            raise
        finally:
            if self._endpoint_discovery_error is not None:
                self._restore_logging_level()

    async def _async_discover_possible_endpoints(
        self, host: str, port: str, force_legacy_mode: bool
    ) -> None:
        """Discover endpoints while the config flow shows a native progress page."""
        try:
            (
                self.data[FLOAT_DICT],
                self.data[SWITCHES_DICT],
                self.data[TEXT_DICT],
                self.data[WRITABLE_DICT],
                self.data[PENDING_DICT],
            ) = await self._get_possible_endpoints(
                host,
                port,
                force_legacy_mode,
                progress_callback=self._on_discovery_progress,
            )
            total_entities = (
                len(self.data[FLOAT_DICT])
                + len(self.data[SWITCHES_DICT])
                + len(self.data[TEXT_DICT])
                + len(self.data[WRITABLE_DICT])
                + len(self.data[PENDING_DICT])
            )
            self._on_discovery_progress(
                f"Discovery finished: {total_entities} entities found",
                1.0,
            )
        except asyncio.CancelledError:
            self._endpoint_discovery_error = None
            self._restore_logging_level()
            raise
        except Exception:
            _LOGGER.exception("Exception while discovering ETA endpoints")
            self._endpoint_discovery_error = "endpoint_discovery_failed"
            self._on_discovery_progress("Discovery failed unexpectedly", None)
        finally:
            if self._endpoint_discovery_error is not None:
                self._restore_logging_level()

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
                selected_pending_sensors = list(self.data.get(PENDING_DICT, {}).keys())
            else:
                selected_float_sensors = user_input.get(CHOSEN_FLOAT_SENSORS, [])
                selected_switches = user_input.get(CHOSEN_SWITCHES, [])
                selected_text_sensors = user_input.get(CHOSEN_TEXT_SENSORS, [])
                selected_writable_sensors = user_input.get(CHOSEN_WRITABLE_SENSORS, [])
                selected_pending_sensors = user_input.get(CHOSEN_PENDING_SENSORS, [])

            (
                self.data[CHOSEN_FLOAT_SENSORS],
                self.data[CHOSEN_SWITCHES],
                self.data[CHOSEN_TEXT_SENSORS],
                self.data[CHOSEN_WRITABLE_SENSORS],
                self.data[CHOSEN_PENDING_SENSORS],
            ) = _sanitize_selected_entity_ids(
                # Keep selection lists category-unique before persisting the entry.
                selected_float_sensors,
                selected_switches,
                selected_text_sensors,
                selected_writable_sensors,
                selected_pending_sensors,
            )

            # Restore old logging level
            self._restore_logging_level()

            # User is done, create the config entry.
            self.data.setdefault(MAX_PARALLEL_REQUESTS, DEFAULT_MAX_PARALLEL_REQUESTS)
            self.data.setdefault(UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
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
                    vol.Required(CONF_PORT, default=user_input[CONF_PORT]): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=65535)
                    ),
                    vol.Required(FORCE_LEGACY_MODE, default=False): cv.boolean,
                    vol.Required(ENABLE_DEBUG_LOGGING, default=False): cv.boolean,
                }
            ),
            errors=self._errors,
        )

    def _restore_logging_level(self) -> None:
        """Restore the previous root logger level if it was changed."""
        if self._old_logging_level != logging.NOTSET and _LOGGER.parent is not None:
            _LOGGER.parent.setLevel(self._old_logging_level)
            self._old_logging_level = logging.NOTSET

    async def _show_config_form_endpoint(self):
        """Show the configuration form to select which endpoints should become entities."""
        pending_dict: dict[str, ETAEndpoint] = self.data.get(PENDING_DICT, {})
        count_placeholders = _build_discovered_entity_placeholders(
            len(self.data[FLOAT_DICT]),
            len(self.data[SWITCHES_DICT]),
            len(self.data[TEXT_DICT]),
            len(self.data[WRITABLE_DICT]),
            len(pending_dict),
        )
        schema = _build_endpoint_selection_schema(self.data)
        return self.async_show_form(
            step_id="select_entities",
            data_schema=vol.Schema(schema),
            errors=self._errors,
            description_placeholders=count_placeholders,
        )

    async def _get_possible_endpoints(
        self,
        host,
        port,
        force_legacy_mode,
        progress_callback=None,
    ):
        session = async_get_clientsession(self.hass)
        eta_client = EtaAPI(session, host, port)
        float_dict = {}
        switches_dict = {}
        text_dict = {}
        writable_dict = {}
        pending_dict = {}
        new_api_version = await eta_client.get_all_sensors(
            force_legacy_mode,
            float_dict,
            switches_dict,
            text_dict,
            writable_dict,
            pending_dict,
            progress_callback=progress_callback,
        )

        if not new_api_version:
            self._errors["base"] = "legacy_mode_selected"

        _LOGGER.debug(
            "Queried sensors: Number of float sensors: %i, Number of switches: %i, Number of text sensors: %i, Number of writable sensors: %i, Number of pending sensors: %i",
            len(float_dict),
            len(switches_dict),
            len(text_dict),
            len(writable_dict),
            len(pending_dict),
        )

        return float_dict, switches_dict, text_dict, writable_dict, pending_dict

    async def _test_url(self, host, port):
        """Return true if host port is valid."""
        session = async_get_clientsession(self.hass)
        eta_client = EtaAPI(session, host, port)

        try:
            does_endpoint_exist = await eta_client.does_endpoint_exists()
        except:  # noqa: E722
            return -1
        return 1 if does_endpoint_exist else 0


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
        self.update_interval = DEFAULT_UPDATE_INTERVAL
        self.unavailable_sensors: dict = {}
        self.advanced_options_writable_sensors = []
        self._options_update_task: asyncio.Task | None = None
        self._options_update_error: str | None = None
        self._pending_init_error: str | None = None

    def _get_runtime_config(self) -> dict | None:
        """Return the loaded runtime config for this entry if available."""
        domain_data = self.hass.data.get(DOMAIN, {})
        config_entry = self.config_entry
        if config_entry is None:
            return None
        return domain_data.get(config_entry.entry_id)

    async def _get_possible_endpoints_with_progress(
        self, host, port, force_legacy_mode, progress_callback=None
    ):
        session = async_get_clientsession(self.hass)
        eta_client = EtaAPI(session, host, port)
        float_dict = {}
        switches_dict = {}
        text_dict = {}
        writable_dict = {}
        pending_dict = {}
        new_api_version = await eta_client.get_all_sensors(
            force_legacy_mode,
            float_dict,
            switches_dict,
            text_dict,
            writable_dict,
            pending_dict,
            progress_callback=progress_callback,
        )

        if not new_api_version:
            self._errors["base"] = "legacy_mode_selected"

        return float_dict, switches_dict, text_dict, writable_dict, pending_dict

    def _on_options_progress(self, message: str, progress: float | None) -> None:
        """Forward options progress updates to HA's progress tracking."""
        _LOGGER.debug("Options progress: %s", message)
        if progress is not None:
            self.async_update_progress(progress)

    async def async_step_init(self, user_input=None):  # noqa: D102
        self._errors = {}
        if self._pending_init_error is not None:
            self._errors["base"] = self._pending_init_error
            self._pending_init_error = None
        current_data = self._get_runtime_config()
        if current_data is None:
            return self.async_abort(reason="integration_busy")
        self.max_parallel_requests = current_data.get(
            MAX_PARALLEL_REQUESTS, DEFAULT_MAX_PARALLEL_REQUESTS
        )
        self.update_interval = current_data.get(
            UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
        )

        if user_input is not None:
            selected_action = user_input[OPTIONS_UPDATE_ACTION]

            self.update_sensor_values = selected_action in (
                OPTIONS_ACTION_UPDATE_SELECTED,
                OPTIONS_ACTION_REDISCOVER_AND_UPDATE,
            )
            self.enumerate_new_endpoints = (
                selected_action == OPTIONS_ACTION_REDISCOVER_AND_UPDATE
            )

            if not self.update_sensor_values and not self.enumerate_new_endpoints:
                return await self.async_step_parallel_requests()

            self._options_update_error = None
            self._options_update_task = self.hass.async_create_task(
                self._async_prepare_entity_selection()
            )
            return await self.async_step_prepare_entities()

        return await self._show_initial_option_screen()

    async def async_step_prepare_entities(self, user_input=None):
        """Show progress while preparing entity data in the options flow."""
        if self._options_update_task is None:
            return await self.async_step_init()

        if not self._options_update_task.done():
            return self.async_show_progress(
                step_id="prepare_entities",
                progress_action="prepare_entities",
                progress_task=self._options_update_task,
            )

        if self._options_update_error is not None:
            self._pending_init_error = self._options_update_error
            self._options_update_task = None
            self._options_update_error = None
            return self.async_show_progress_done(next_step_id="init")

        self._options_update_task = None
        return self.async_show_progress_done(next_step_id="user")

    async def _async_prepare_entity_selection(self) -> None:
        """Prepare endpoint data in a background task for the options flow."""
        try:
            await self._prepare_data_structures()
        except asyncio.CancelledError:
            self._options_update_error = None
            raise
        except Exception:
            _LOGGER.exception("Exception while preparing options data structures")
            self._options_update_error = (
                "endpoint_discovery_failed"
                if self.enumerate_new_endpoints
                else "value_update_error"
            )
            self._on_options_progress("Background preparation failed", None)

    async def _show_initial_option_screen(self):
        """Show the initial option form."""
        current_data = self._get_runtime_config()
        if current_data is None:
            return self.async_abort(reason="integration_busy")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        OPTIONS_UPDATE_ACTION,
                        default=OPTIONS_ACTION_PARALLEL_ONLY,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                OPTIONS_ACTION_PARALLEL_ONLY,
                                OPTIONS_ACTION_UPDATE_SELECTED,
                                OPTIONS_ACTION_REDISCOVER_AND_UPDATE,
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                            multiple=False,
                            translation_key="options_update_action",
                        )
                    ),
                }
            ),
            errors=self._errors,
        )

    async def async_step_parallel_requests(self, user_input=None):
        """Update only the max number of parallel API requests."""
        current_data = self._get_runtime_config()
        if current_data is None:
            return self.async_abort(reason="integration_busy")

        parallel_request_options = ["1", "2", "3", "5", "8", "10", "15"]
        default_parallel_requests = str(
            current_data.get(MAX_PARALLEL_REQUESTS, DEFAULT_MAX_PARALLEL_REQUESTS)
        )
        if default_parallel_requests not in parallel_request_options:
            default_parallel_requests = str(DEFAULT_MAX_PARALLEL_REQUESTS)

        update_interval_options = ["20", "30", "60", "90", "120"]
        default_update_interval = str(
            current_data.get(UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        if default_update_interval not in update_interval_options:
            default_update_interval = str(DEFAULT_UPDATE_INTERVAL)

        if user_input is not None:
            self.max_parallel_requests = int(user_input[MAX_PARALLEL_REQUESTS])
            self.update_interval = int(user_input[UPDATE_INTERVAL])
            data = {
                CHOSEN_FLOAT_SENSORS: current_data[CHOSEN_FLOAT_SENSORS],
                CHOSEN_SWITCHES: current_data[CHOSEN_SWITCHES],
                CHOSEN_TEXT_SENSORS: current_data[CHOSEN_TEXT_SENSORS],
                CHOSEN_WRITABLE_SENSORS: current_data[CHOSEN_WRITABLE_SENSORS],
                CHOSEN_PENDING_SENSORS: current_data.get(CHOSEN_PENDING_SENSORS, []),
                FLOAT_DICT: current_data[FLOAT_DICT],
                SWITCHES_DICT: current_data[SWITCHES_DICT],
                TEXT_DICT: current_data[TEXT_DICT],
                WRITABLE_DICT: current_data[WRITABLE_DICT],
                PENDING_DICT: current_data.get(PENDING_DICT, {}),
                MAX_PARALLEL_REQUESTS: self.max_parallel_requests,
                UPDATE_INTERVAL: self.update_interval,
                CONF_HOST: current_data[CONF_HOST],
                CONF_PORT: current_data[CONF_PORT],
                ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION: current_data.get(
                    ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION, []
                ),
                FORCE_LEGACY_MODE: current_data[FORCE_LEGACY_MODE],
            }
            return self.async_create_entry(title="", data=data)

        return self.async_show_form(
            step_id="parallel_requests",
            data_schema=vol.Schema(
                {
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
                    vol.Required(
                        UPDATE_INTERVAL, default=default_update_interval
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=v, label=f"{v}s")
                                for v in update_interval_options
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
        for category_key in [FLOAT_DICT, SWITCHES_DICT, TEXT_DICT, WRITABLE_DICT]:
            for entity in list(self.data[category_key].keys()):
                if self.data[category_key][entity]["url"] not in all_data:
                    _LOGGER.exception(
                        "Exception while updating the value for endpoint '%s' (%s)",
                        self.data[category_key][entity]["friendly_name"],
                        self.data[category_key][entity]["url"],
                    )
                    self._errors["base"] = "value_update_error"
                else:
                    self.data[category_key][entity]["value"] = all_data[
                        self.data[category_key][entity]["url"]
                    ]

    def _verify_pending_sensors(
        self,
        new_pending_sensors: dict,
        new_float_sensors: dict,
        current_float_sensors: dict,
    ) -> int:
        # Pending sensors which are already available as regular sensors can be removed from the pending sensors list
        deleted_pending_count = 0
        for key in list(new_pending_sensors.keys()):
            # Pending sensors will only be promoted to float sensors, so we don't need to check the other sensor categories here
            if key in current_float_sensors:
                del new_pending_sensors[key]
                new_float_sensors[key] = current_float_sensors[key]
                deleted_pending_count += 1
        return deleted_pending_count

    def _handle_new_sensors(
        self,
        new_float_sensors: dict,
        new_switches: dict,
        new_text_sensors: dict,
        new_writable_sensors: dict,
        new_pending_sensors: dict,
    ):
        added_sensor_count = 0
        # Add newly detected sensors to the lists of available sensors
        category_mapping = [
            (new_float_sensors, FLOAT_DICT),
            (new_switches, SWITCHES_DICT),
            (new_text_sensors, TEXT_DICT),
            (new_writable_sensors, WRITABLE_DICT),
            (new_pending_sensors, PENDING_DICT),
        ]
        for new_dict, category_key in category_mapping:
            for key, value in new_dict.items():
                if key not in self.data[category_key]:
                    added_sensor_count += 1
                    self.data[category_key][key] = value

        return added_sensor_count

    def _handle_deleted_sensors(
        self,
        new_float_sensors: dict,
        new_switches: dict,
        new_text_sensors: dict,
        new_writable_sensors: dict,
        new_pending_sensors: dict,
    ):
        deleted_sensor_count = 0
        # Delete sensors which are no longer available; loop over a copy of the
        # keys so items can be removed in-place.
        standard_categories = [
            (FLOAT_DICT, CHOSEN_FLOAT_SENSORS, new_float_sensors),
            (SWITCHES_DICT, CHOSEN_SWITCHES, new_switches),
            (TEXT_DICT, CHOSEN_TEXT_SENSORS, new_text_sensors),
            (WRITABLE_DICT, CHOSEN_WRITABLE_SENSORS, new_writable_sensors),
        ]
        for category_key, chosen_key, new_dict in standard_categories:
            for key in list(self.data[category_key].keys()):
                if key not in new_dict:
                    deleted_sensor_count += 1
                    if key in self.data[chosen_key]:
                        # Remember deleted chosen sensors to show them to the user later
                        self.data[chosen_key].remove(key)
                        self.unavailable_sensors[key] = self.data[category_key][key]
                    del self.data[category_key][key]

        # PENDING: no unavailable_sensors tracking (pending sensors have no HA entities yet)
        for key in list(self.data[PENDING_DICT].keys()):
            if key not in new_pending_sensors:
                deleted_sensor_count += 1
                self.data[CHOSEN_PENDING_SENSORS] = [
                    k for k in self.data[CHOSEN_PENDING_SENSORS] if k != key
                ]
                del self.data[PENDING_DICT][key]

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

    async def _prepare_data_structures(self):
        current_data = self._get_runtime_config()
        if current_data is None:
            raise RuntimeError("Integration runtime config is unavailable")
        self._on_options_progress("Loading current configuration", 0.05)

        # Make a copy of the data structure to make sure we don't alter the original data
        for key in [
            CONF_HOST,
            CONF_PORT,
            FLOAT_DICT,
            SWITCHES_DICT,
            TEXT_DICT,
            WRITABLE_DICT,
            PENDING_DICT,
            CHOSEN_FLOAT_SENSORS,
            CHOSEN_SWITCHES,
            CHOSEN_TEXT_SENSORS,
            CHOSEN_WRITABLE_SENSORS,
            CHOSEN_PENDING_SENSORS,
            FORCE_LEGACY_MODE,
        ]:
            self.data[key] = copy.copy(current_data[key])
        (
            self.data[CHOSEN_FLOAT_SENSORS],
            self.data[CHOSEN_SWITCHES],
            self.data[CHOSEN_TEXT_SENSORS],
            self.data[CHOSEN_WRITABLE_SENSORS],
            self.data[CHOSEN_PENDING_SENSORS],
        ) = _sanitize_selected_entity_ids(
            # Normalize historic options data before applying updates.
            self.data[CHOSEN_FLOAT_SENSORS],
            self.data[CHOSEN_SWITCHES],
            self.data[CHOSEN_TEXT_SENSORS],
            self.data[CHOSEN_WRITABLE_SENSORS],
            self.data[CHOSEN_PENDING_SENSORS],
        )
        # ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION can be unset, so we have to handle it separately
        self.data[ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION] = (
            current_data.get(ADVANCED_OPTIONS_IGNORE_DECIMAL_PLACES_RESTRICTION, [])
        )
        self.data[MAX_PARALLEL_REQUESTS] = self.max_parallel_requests
        self.data[UPDATE_INTERVAL] = self.update_interval
        self._on_options_progress("Loaded current configuration", 0.1)

        if self.enumerate_new_endpoints:
            _LOGGER.info("Discovering new endpoints")
            self._on_options_progress("Rediscovering available entities", 0.15)
            (
                new_float_sensors,
                new_switches,
                new_text_sensors,
                new_writable_sensors,
                new_pending_sensors,
            ) = await self._get_possible_endpoints_with_progress(
                self.data[CONF_HOST],
                self.data[CONF_PORT],
                self.data[FORCE_LEGACY_MODE],
                progress_callback=self._on_options_progress,
            )

            removed_pending_count = self._verify_pending_sensors(
                new_pending_sensors, new_float_sensors, self.data[FLOAT_DICT]
            )
            _LOGGER.info(
                "Verified pending sensors, removed %i sensors which are now available as regular sensors from the pending sensors list",
                removed_pending_count,
            )

            added_sensor_count = self._handle_new_sensors(
                new_float_sensors,
                new_switches,
                new_text_sensors,
                new_writable_sensors,
                new_pending_sensors,
            )
            _LOGGER.info("Added %i new sensors", added_sensor_count)
            self._on_options_progress(
                f"Added {added_sensor_count} newly discovered entities",
                0.92,
            )

            deleted_sensor_count = self._handle_deleted_sensors(
                new_float_sensors,
                new_switches,
                new_text_sensors,
                new_writable_sensors,
                new_pending_sensors,
            )
            _LOGGER.info("Deleted %i unavailable sensors", deleted_sensor_count)
            self._on_options_progress(
                f"Removed {deleted_sensor_count} unavailable entities",
                0.95,
            )

            self._handle_sensor_value_updates_from_enumeration(
                new_float_sensors, new_switches, new_text_sensors, new_writable_sensors
            )
            _LOGGER.info("Updated sensor values")
            self._on_options_progress("Updated values for rediscovered entities", 0.98)

        elif self.update_sensor_values:
            # Update current sensor values only if requested and no re-enumeration is running.
            self._on_options_progress("Refreshing values of selected entities", 0.3)
            await self._update_sensor_values()
            self._on_options_progress(
                "Finished refreshing selected entity values", 0.98
            )

        self._on_options_progress("Preparation finished", 1.0)

    async def async_step_user(self, user_input=None):
        """Manage the options."""
        if self._get_runtime_config() is None:
            return self.async_abort(reason="integration_busy")

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
            if self.auto_select_all_entities:
                selected_float_sensors = list(self.data[FLOAT_DICT].keys())
                selected_switches = list(self.data[SWITCHES_DICT].keys())
                selected_text_sensors = list(self.data[TEXT_DICT].keys())
                selected_writable_sensors = list(self.data[WRITABLE_DICT].keys())
                selected_pending_sensors = list(self.data.get(PENDING_DICT, {}).keys())
            else:
                selected_float_sensors = user_input.get(CHOSEN_FLOAT_SENSORS, [])
                selected_switches = user_input.get(CHOSEN_SWITCHES, [])
                selected_text_sensors = user_input.get(CHOSEN_TEXT_SENSORS, [])
                selected_writable_sensors = user_input.get(CHOSEN_WRITABLE_SENSORS, [])
                selected_pending_sensors = user_input.get(CHOSEN_PENDING_SENSORS, [])

            (
                selected_float_sensors,
                selected_switches,
                selected_text_sensors,
                selected_writable_sensors,
                selected_pending_sensors,
            ) = _sanitize_selected_entity_ids(
                # Prevent cross-category duplicates from being written back via options.
                selected_float_sensors,
                selected_switches,
                selected_text_sensors,
                selected_writable_sensors,
                selected_pending_sensors,
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
                CHOSEN_PENDING_SENSORS: selected_pending_sensors,
                FLOAT_DICT: self.data[FLOAT_DICT],
                SWITCHES_DICT: self.data[SWITCHES_DICT],
                TEXT_DICT: self.data[TEXT_DICT],
                WRITABLE_DICT: self.data[WRITABLE_DICT],
                PENDING_DICT: self.data[PENDING_DICT],
                MAX_PARALLEL_REQUESTS: self.data[MAX_PARALLEL_REQUESTS],
                UPDATE_INTERVAL: self.data[UPDATE_INTERVAL],
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

        writable_dict = self.data[WRITABLE_DICT]

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
                                    label=f"{writable_dict[key]['friendly_name']} ({writable_dict[key]['value']} {writable_dict[key]['unit'] if writable_dict[key]['unit'] not in INVISIBLE_UNITS else ''})",
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

        count_placeholders = _build_discovered_entity_placeholders(
            len(self.data[FLOAT_DICT]),
            len(self.data[SWITCHES_DICT]),
            len(self.data[TEXT_DICT]),
            len(self.data[WRITABLE_DICT]),
            len(self.data.get(PENDING_DICT, {})),
        )
        # Pending sensors don't have HA entities yet, so read their selection from local data
        defaults = {
            CHOSEN_FLOAT_SENSORS: current_chosen_sensors,
            CHOSEN_SWITCHES: current_chosen_switches,
            CHOSEN_TEXT_SENSORS: current_chosen_text_sensors,
            CHOSEN_WRITABLE_SENSORS: current_chosen_writable_sensors,
        }
        schema = _build_endpoint_selection_schema(
            self.data,
            auto_select_default=self.auto_select_all_entities,
            defaults=defaults,
            unavailable_sensors=self.unavailable_sensors or None,
        )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema),
            errors=self._errors,
            description_placeholders=count_placeholders,
        )
