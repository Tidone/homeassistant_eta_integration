"""Unit tests for utility functions."""

# pyright: reportTypedDictNotRequiredAccess=false

from custom_components.eta_webservices.const import DOMAIN
from custom_components.eta_webservices.utils import create_device_info


def test_create_device_info_with_device_name():
    """Device name is prefixed with 'ETA > ' and appended to the identifier."""
    info = create_device_info("192.168.1.10", "8080", "Kessel")
    assert info["name"] == "ETA > Kessel"
    assert (DOMAIN, "eta_192_168_1_10_8080_Kessel") in info["identifiers"]
    assert info["manufacturer"] == "ETA"
    assert info["configuration_url"] == "https://www.meineta.at"


def test_create_device_info_without_device_name():
    """Omitting device_name produces a plain 'ETA' name and shorter identifier."""
    info = create_device_info("192.168.1.10", "8080", None)
    assert info["name"] == "ETA"
    assert (DOMAIN, "eta_192_168_1_10_8080") in info["identifiers"]
    assert info["manufacturer"] == "ETA"
    assert info["configuration_url"] == "https://www.meineta.at"
