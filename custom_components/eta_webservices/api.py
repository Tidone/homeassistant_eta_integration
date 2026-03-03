"""Handle all low-level API calls for ETA Sensors.

This module provides a unified API for the ETA integration, with automatic
version detection and routing to the appropriate sensor discovery implementation.
"""

import asyncio
import logging

from packaging import version
import xmltodict

from ._api.api_client import APIClient
from ._api.sensor_discovery_v11 import SensorDiscoveryV11
from ._api.sensor_discovery_v12 import SensorDiscoveryV12

# Re-export types for backward compatibility
from ._api.types import (  # noqa: F401
    DEFAULT_VALID_WRITABLE_VALUES,
    FLOAT_SENSOR_UNITS,
    WRITABLE_SENSOR_UNITS,
    ETAEndpoint,
    ETAError,
    ETAValidSwitchValues,
    ETAValidWritableValues,
)

_LOGGER = logging.getLogger(__name__)


class EtaAPI:
    """Unified API for ETA communication.

    This class provides the main interface for communicating with ETA heating systems.
    It automatically detects the API version and delegates sensor discovery to the
    appropriate version-specific implementation.
    """

    def __init__(
        self,
        session,
        host,
        port,
        max_concurrent_requests=5,
        request_semaphore=None,
    ) -> None:
        """Initialize the ETA API.

        :param session: aiohttp ClientSession for HTTP requests
        :param host: Hostname or IP address of the ETA device
        :param port: Port number of the ETA API
        """
        self._http = APIClient(
            session,
            host,
            port,
            max_concurrent_requests=max_concurrent_requests,
            request_semaphore=request_semaphore,
        )

    async def get_all_sensors(
        self, force_legacy_mode, float_dict, switches_dict, text_dict, writable_dict
    ):
        """Enumerate all possible sensors on the ETA API.

        Automatically routes to the appropriate version implementation based on
        the detected API version.

        :param force_legacy_mode: Set to true to force the use of the old API mode
        :param float_dict: Dictionary which will be filled with all float sensors
        :param switches_dict: Dictionary which will be filled with all switch sensors
        :param text_dict: Dictionary which will be filled with all text sensors
        :param writable_dict: Dictionary which will be filled with all writable sensors
        """
        if not force_legacy_mode and await self.is_correct_api_version():
            # New version with varinfo endpoint detected
            sensor_discovery = SensorDiscoveryV12(self._http)
            await sensor_discovery.get_all_sensors(
                float_dict, switches_dict, text_dict, writable_dict
            )
        else:
            # varinfo not available -> fall back to compatibility mode
            sensor_discovery = SensorDiscoveryV11(self._http)
            await sensor_discovery.get_all_sensors(
                float_dict, switches_dict, text_dict, writable_dict
            )

    async def does_endpoint_exists(self):
        """Returns true if the ETA API is accessible."""
        try:
            await self._http.get_menu()
        except Exception:  # noqa: BLE001
            return False
        return True

    async def get_api_version(self):
        """Get the version of the ETA API as a raw string.

        :return: Version of the ETA API
        :rtype: Version
        """
        data = await self._http.get_request("/user/api")
        text = await data.text()
        return version.parse(xmltodict.parse(text)["eta"]["api"]["@version"])

    async def is_correct_api_version(self):
        """Returns true if the ETA API version is v1.2 or higher."""
        eta_version = await self.get_api_version()
        required_version = version.parse("1.2")

        return eta_version >= required_version

    async def get_data(
        self, uri, force_number_handling=False, force_string_handling=False
    ):
        """Request the data from a API URL.

        :param uri: ETA API url suffix, like /120/1/123
        :param force_number_handling: Set to true if the data should be treated as a number even if its unit is not in the list of valid float sensors
        :param force_string_handling: Set to true if the data should be treated as a string regardless of its unit
        :return: Parsed data as a Tuple[Value, Unit]
        :rtype: Tuple[Any,str]
        """
        return await self._http.get_data(
            uri,
            force_number_handling=force_number_handling,
            force_string_handling=force_string_handling,
        )

    async def get_all_data(self, sensor_list: dict[str, dict[str, bool]]):
        """Get all data from all endpoints.

        :param sensor_list: Dict[url, Dict[str, bool]] of sensors to query the data for
        :return: List of all data
        :rtype: Dict[str, Any]
        """
        return await self._http.get_all_data(sensor_list)

    async def get_menu(self):
        """Request the menu from the ETA API, which includes links to all possible sensors."""
        return await self._http.get_menu()

    async def get_errors(self):
        """Request a list of active errors from the ETA system.

        :return: List of active errors
        :rtype: List[ETAError]
        """
        data = await self._http.get_request("/user/errors")
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["errors"]["fub"]

        return self._http.parse_errors(data)

    async def get_switch_state(self, uri):
        """Get the raw state of a switch sensor.

        :param uri: URL suffix of the switch sensor
        :return: Raw switch value, like 1802
        :rtype: int
        """
        data = await self._http.get_request("/user/var/" + str(uri))
        text = await data.text()
        data = xmltodict.parse(text)["eta"]["value"]
        return int(data["#text"])

    async def get_all_switch_states(self, switch_uris: list[str]):
        """Get switch states from all endpoints.

        :param switch_uris: List of switch endpoint URIs
        :return: Mapping from URI to raw switch state (or exception)
        :rtype: Dict[str, Any]
        """
        semaphore = asyncio.Semaphore(self._http.max_concurrent_requests)

        async def fetch_state_limited(uri: str):
            async with semaphore:
                return await self.get_switch_state(uri)

        tasks = [fetch_state_limited(uri) for uri in switch_uris]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return dict(zip(switch_uris, results, strict=False))

    async def set_switch_state(self, uri, state):
        """Set the state of a switch sensor.

        :param uri: URL suffix of the switch sensor
        :param state: Raw switch state value, like 1802
        :return: True on success, False on failure
        :rtype: boolean
        """
        data = {"value": state}
        response = await self._http.post_request("/user/var/" + str(uri), data)
        text = await response.text()
        parsed = xmltodict.parse(text)

        # Check if response contains success element
        if "success" in parsed.get("eta", {}):
            return True

        _LOGGER.error(
            "ETA Integration - could not set state of switch. Got invalid result: %s",
            text,
        )

        return False

    async def write_endpoint(self, uri, value=None, begin=None, end=None):
        """Writa a raw value to a writable sensor.

        :param uri: URL suffix of the writable sensor
        :param value: Raw value of the sensor
        :param begin: Optional begin time, used for some sensors
        :param end: Optional end time, used for some sensors
        :return: True on success, False on failure or error
        :rtype: boolean
        """
        data = {}
        if value is not None:
            data["value"] = value
        if begin is not None:
            data["begin"] = begin
        if end is not None:
            data["end"] = end
        response = await self._http.post_request("/user/var/" + str(uri), data)
        text = await response.text()
        parsed = xmltodict.parse(text)

        # Check if response contains success element (not error or invalid)
        if "success" in parsed.get("eta", {}):
            return True

        if "error" in parsed.get("eta", {}):
            _LOGGER.error(
                "ETA Integration - could not set write value to endpoint. Terminal returned: %s",
                parsed["eta"]["error"],
            )
            return False

        _LOGGER.error(
            "ETA Integration - could not set write value to endpoint. Got invalid result: %s",
            text,
        )
        return False
