"""Tests for the new ETA Webservices config flow."""
from unittest.mock import patch, AsyncMock
import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from custom_components.eta_webservices.const import (
    DOMAIN,
    FORCE_LEGACY_MODE,
    ENABLE_DEBUG_LOGGING,
    CHOSEN_DEVICES,
    CHOSEN_FLOAT_SENSORS,
    CHOSEN_SWITCHES,
    FLOAT_DICT,
    SWITCHES_DICT,
    TEXT_DICT,
    WRITABLE_DICT,
)

MOCK_HOST = "valid_host"
MOCK_PORT = "8080"
MOCK_DEVICES = ["device1", "device2"]
MOCK_DEVICE_1_ENTITIES = {
    FLOAT_DICT: {
        "uri1": {
            "friendly_name": "Device 1 Sensor",
            "unit": "V",
            "value": 12.5,
            "valid_values": None,
            "endpoint_type": "FLOAT",
        }
    },
    SWITCHES_DICT: {
        "uri2": {
            "friendly_name": "Device 1 Switch",
            "valid_values": {"On": 1, "Off": 0},
            "value": "1",
            "unit": "",
            "endpoint_type": "TEXT",
        }
    },
    TEXT_DICT: {},
    WRITABLE_DICT: {},
}
MOCK_DEVICE_2_ENTITIES = {
    FLOAT_DICT: {
        "uri3": {
            "friendly_name": "Device 2 Sensor",
            "unit": "kW",
            "value": 12.3,
            "valid_values": None,
            "endpoint_type": "FLOAT",
        }
    },
    SWITCHES_DICT: {},
    TEXT_DICT: {},
    WRITABLE_DICT: {},
}


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Mock setting up a config entry."""
    with patch("custom_components.eta_webservices.async_setup_entry", return_value=True):
        yield


@pytest.mark.asyncio
async def test_full_new_config_flow(hass: HomeAssistant, enable_custom_integrations):
    """Test the full new config flow from user step to finish."""

    async def mock_scan_device(device_name: str):
        if device_name == "device1":
            return MOCK_DEVICE_1_ENTITIES
        if device_name == "device2":
            return MOCK_DEVICE_2_ENTITIES
        return {}

    with patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._test_url",
        return_value=1,
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._is_correct_api_version",
        return_value=True,
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._get_possible_devices",
        return_value=MOCK_DEVICES,
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._scan_device",
        side_effect=mock_scan_device,
    ):
        # 1. Start the flow
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "user"

        # 2. Provide host/port
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_HOST: MOCK_HOST,
                CONF_PORT: MOCK_PORT,
                FORCE_LEGACY_MODE: False,
                ENABLE_DEBUG_LOGGING: False,
            },
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "confirm_scan"

        # 3. Confirm scan
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "scan_device"
        assert result["description_placeholders"]["device"] == "device1"

        # 4. Scan device 1
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "scan_device"
        assert result["description_placeholders"]["device"] == "device2"

        # 5. Scan device 2 -> transition to select_device
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "select_device"

        # 6. Select device 1 to configure
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"device": "device1"}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "select_entities"

        # 7. Select entities for device 1
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"chosen_entities": ["uri1"]}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "select_device"

        # 8. Select device 2 to configure
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"device": "device2"}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "select_entities"

        # 9. Select entities for device 2
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"chosen_entities": ["uri3"]}
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "select_device"

        # 10. Finish setup
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"device": "finish_setup"}
        )

        # 11. Verify entry created with correct data and options
        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["title"] == f"ETA at {MOCK_HOST}"

        # Verify data part
        assert result["data"][CONF_HOST] == MOCK_HOST
        assert result["data"][CHOSEN_DEVICES] == MOCK_DEVICES
        assert result["data"]["scanned_devices_data"]["device1"] == MOCK_DEVICE_1_ENTITIES
        assert result["data"]["scanned_devices_data"]["device2"] == MOCK_DEVICE_2_ENTITIES

        # Verify options part
        assert result["options"][CHOSEN_FLOAT_SENSORS] == ["uri1", "uri3"]
        assert result["options"][CHOSEN_SWITCHES] == []
