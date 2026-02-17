"""Abstract base class for sensor discovery implementations."""

from abc import ABC, abstractmethod

from ..const import CUSTOM_UNITS  # noqa: TID252
from .api_client import APIClient
from .types import FLOAT_SENSOR_UNITS, ETAEndpoint


class SensorDiscoveryBase(ABC):
    """Abstract base class for version-specific sensor discovery."""

    def __init__(self, http_client: APIClient) -> None:
        """Initialize sensor discovery.

        :param http_client: HTTPClient instance for API calls
        :param api_instance: Reference to parent EtaAPI instance
        """
        self._http = http_client

    # Concrete methods (shared by all versions)

    def _is_float_sensor(self, endpoint_info: ETAEndpoint) -> bool:
        """Check if endpoint is a float sensor."""
        return endpoint_info["unit"] in FLOAT_SENSOR_UNITS

    def _is_text_sensor(self, endpoint_info: ETAEndpoint) -> bool:
        """Check if endpoint is a text sensor."""
        # all custom units are text sensors right now
        return endpoint_info["unit"] in CUSTOM_UNITS or (
            endpoint_info["unit"] == "" and endpoint_info["endpoint_type"] == "TEXT"
        )

    def _get_friendly_name(self, key: str) -> str:
        """Generate friendly name from key."""
        components = key.split("_")[1:]  # The first part is always empty
        return " > ".join(components)

    # Abstract methods (must be implemented by subclasses)

    @abstractmethod
    def _is_switch(
        self, endpoint_info: ETAEndpoint, raw_value: str | None = None
    ) -> bool:
        """Check if endpoint is a switch.

        :param endpoint_info: Endpoint metadata
        :param raw_value: Optional raw value (used by v1.1)
        :return: True if switch
        """

    @abstractmethod
    def _is_writable(self, endpoint_info: ETAEndpoint) -> bool:
        """Check if endpoint is writable.

        :param endpoint_info: Endpoint metadata
        :return: True if writable
        """

    @abstractmethod
    def _parse_switch_values(self, endpoint_info: ETAEndpoint):
        """Parse and populate switch valid values.

        :param endpoint_info: Endpoint metadata (modified in place)
        """

    @abstractmethod
    async def get_all_sensors(
        self,
        float_dict: dict,
        switches_dict: dict,
        text_dict: dict,
        writable_dict: dict,
    ):
        """Discover and enumerate all sensors.

        :param float_dict: Dictionary to fill with float sensors
        :param switches_dict: Dictionary to fill with switch sensors
        :param text_dict: Dictionary to fill with text sensors
        :param writable_dict: Dictionary to fill with writable sensors
        """
