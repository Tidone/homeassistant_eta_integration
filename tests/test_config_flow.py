"""Tests for the ETA Webservices config flow."""

from unittest.mock import patch, MagicMock

from unittest.mock import AsyncMock

from homeassistant import config_entries, data_entry_flow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eta_webservices.const import (
    DOMAIN,
    FORCE_LEGACY_MODE,
    ENABLE_DEBUG_LOGGING,
    CHOSEN_DEVICES,
    FLOAT_DICT,
    SWITCHES_DICT,
    TEXT_DICT,
    WRITABLE_DICT,
    CHOSEN_FLOAT_SENSORS,
    CHOSEN_SWITCHES,
)


@pytest.fixture(autouse=True)
def mock_setup_entry():
    """Mock setting up a config entry."""
    with patch(
        "custom_components.eta_webservices.async_setup_entry", return_value=True
    ):
        yield


@pytest.mark.asyncio
async def test_user_form_show(hass: HomeAssistant, enable_custom_integrations):
    """Test that the user form is shown."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_user_form_invalid_host(hass: HomeAssistant, enable_custom_integrations):
    """Test that the user form shows an error for an invalid host."""
    with patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._test_url",
        return_value=0,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_HOST: "invalid_host",
                CONF_PORT: "8080",
                FORCE_LEGACY_MODE: False,
                ENABLE_DEBUG_LOGGING: False,
            },
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "no_eta_endpoint"}


@pytest.mark.asyncio
async def test_user_form_wrong_api_version(
    hass: HomeAssistant, enable_custom_integrations
):
    """Test that the user form shows an error for a wrong API version."""
    with patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._test_url",
        return_value=1,
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._is_correct_api_version",
        return_value=False,
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._get_possible_devices",
        return_value=["device1"],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_HOST: "valid_host",
                CONF_PORT: "8080",
                FORCE_LEGACY_MODE: False,
                ENABLE_DEBUG_LOGGING: False,
            },
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "wrong_api_version"}


@pytest.mark.asyncio
async def test_user_form_no_devices_found(
    hass: HomeAssistant, enable_custom_integrations
):
    """Test that the user form shows an error if no devices are found."""
    with patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._test_url",
        return_value=1,
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._is_correct_api_version",
        return_value=True,
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._get_possible_devices",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_HOST: "valid_host",
                CONF_PORT: "8080",
                FORCE_LEGACY_MODE: False,
                ENABLE_DEBUG_LOGGING: False,
            },
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": "no_devices_found"}


@pytest.mark.asyncio
async def test_user_form_success(hass: HomeAssistant, enable_custom_integrations):
    """Test that the user form successfull."""
    with patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._test_url",
        return_value=1,
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._is_correct_api_version",
        return_value=True,
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._get_possible_devices",
        return_value=["device1", "device2"],
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._scan_device",
        return_value={"some": "data"},
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_HOST: "valid_host",
                CONF_PORT: "8080",
                FORCE_LEGACY_MODE: False,
                ENABLE_DEBUG_LOGGING: False,
            },
        )

        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "confirm_scan"


@pytest.mark.asyncio
async def test_options_flow_select_device_show(
    hass: HomeAssistant, enable_custom_integrations
):
    """Test that the options flow shows the select device form."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CHOSEN_DEVICES: ["device1", "device2"],
            CONF_HOST: "valid_host",
            CONF_PORT: "8080",
        },
        entry_id="test-entry-id",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "select_device"


@pytest.mark.asyncio
async def test_options_flow_select_device_submit(
    hass: HomeAssistant, enable_custom_integrations
):
    """Test that the options flow moves to select_entities after device selection."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CHOSEN_DEVICES: ["device1", "device2"],
            CONF_HOST: "valid_host",
            CONF_PORT: "8080",
        },
        entry_id="test-entry-id",
    )
    entry.add_to_hass(hass)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "device1": MagicMock(
            data={
                FLOAT_DICT: {"sensor1": {"friendly_name": "Sensor 1"}},
                SWITCHES_DICT: {},
                TEXT_DICT: {},
                WRITABLE_DICT: {},
            }
        )
    }

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"device": "device1"},
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "select_entities"


@pytest.mark.asyncio
async def test_options_flow_select_entities_submit(
    hass: HomeAssistant, enable_custom_integrations
):
    """Test that options are updated on select_entities submit."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CHOSEN_DEVICES: ["device1"],
            CONF_HOST: "valid_host",
            CONF_PORT: "8080",
        },
        options={
            CHOSEN_FLOAT_SENSORS: [],
            CHOSEN_SWITCHES: ["switch1"],
        },
        entry_id="test-entry-id",
    )
    entry.add_to_hass(hass)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "device1": MagicMock(
            data={
                FLOAT_DICT: {"sensor1": {"friendly_name": "Sensor 1", "uri": "uri1"}},
                SWITCHES_DICT: {
                    "switch1": {"friendly_name": "Switch 1", "uri": "uri2"}
                },
                TEXT_DICT: {},
                WRITABLE_DICT: {},
            }
        )
    }

    def classify_entity_mock(entity):
        if "sensor" in entity["friendly_name"].lower():
            return "sensor"
        if "switch" in entity["friendly_name"].lower():
            return "switch"
        return None

    with patch(
        "custom_components.eta_webservices.api.EtaAPI.classify_entity",
        side_effect=classify_entity_mock,
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={"device": "device1"},
        )

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={"chosen_entities": ["sensor1"]},
        )

        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["data"] == {
            CHOSEN_FLOAT_SENSORS: ["sensor1"],
            CHOSEN_SWITCHES: [],
        }


@pytest.mark.asyncio
async def test_scan_device_step(hass: HomeAssistant, enable_custom_integrations):
    """Test the scan_device step."""
    with patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._test_url",
        return_value=1,
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._is_correct_api_version",
        return_value=True,
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._get_possible_devices",
        return_value=["device1", "device2"],
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._scan_device",
        return_value={"some": "data"},
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_HOST: "valid_host",
                CONF_PORT: "8080",
                FORCE_LEGACY_MODE: False,
                ENABLE_DEBUG_LOGGING: False,
            },
        )

        # Confirm scan
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "scan_device"

        # Scan first device
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "show_found_entities"

        # Continue from intermediate step
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "scan_device"
        assert result["description_placeholders"]["device"] == "device2"

        # Scan second device
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "show_found_entities"

        # Continue from intermediate step
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={},
        )
        assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result["title"] == "ETA at valid_host"
        assert result["data"][CHOSEN_DEVICES] == ["device1", "device2"]


@pytest.mark.asyncio
async def test_scan_device_shows_entities_step(
    hass: HomeAssistant, enable_custom_integrations
):
    """Test that the intermediate show_found_entities step is shown."""
    mock_entities = {
        FLOAT_DICT: {"uri1": {"friendly_name": "Sensor 1"}},
        SWITCHES_DICT: {"uri2": {"friendly_name": "Switch 1"}},
        TEXT_DICT: {},
        WRITABLE_DICT: {},
    }

    with patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._test_url",
        return_value=1,
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._is_correct_api_version",
        return_value=True,
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._get_possible_devices",
        return_value=["device1", "device2"],
    ), patch(
        "custom_components.eta_webservices.config_flow.EtaFlowHandler._scan_device",
        return_value=mock_entities,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={
                CONF_HOST: "valid_host",
                CONF_PORT: "8080",
                FORCE_LEGACY_MODE: False,
                ENABLE_DEBUG_LOGGING: False,
            },
        )

        # Confirm scan
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )

        # Scan first device
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )

        # Assert that we are at the new intermediate step
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "show_found_entities"
        assert "Sensor 1" in result["description_placeholders"]["entities"]
        assert "Switch 1" in result["description_placeholders"]["entities"]

        # Continue from the intermediate step
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )

        # Assert that we are now scanning the second device
        assert result["type"] == data_entry_flow.FlowResultType.FORM
        assert result["step_id"] == "scan_device"
        assert result["description_placeholders"]["device"] == "device2"
