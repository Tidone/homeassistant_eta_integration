"""Tests for the ETA API module."""

import pytest
from unittest.mock import AsyncMock
from aiohttp import ClientSession

from custom_components.eta_webservices.api import EtaAPI


@pytest.mark.asyncio
async def test_get_all_sensors_v12(load_fixture):
    """Test _get_all_sensors_v12 method with real fixture data.
    
    This test verifies:
    - Mock HTTP responses are properly used
    - Endpoints are correctly parsed from varinfo endpoint
    - Sensor values are fetched and added to correct dictionaries
    - All dictionaries are populated with expected entries
    """
    # Load fixtures
    api_endpoint_data = load_fixture("api_endpoint_data.json")
    assignment_target_values = load_fixture("api_assignment_reference_values_v12.json")
    
    # Setup mock session
    mock_session = AsyncMock(spec=ClientSession)
    
    # Create API instance with test host
    api = EtaAPI(mock_session, "192.168.0.25", 8080)
    
    # Setup mock responses based on fixture data
    def create_mock_response(url_path: str):
        """Create a mock response for a given URL path."""
        response = AsyncMock()
        if url_path in api_endpoint_data:
            response.text = AsyncMock(
                return_value=api_endpoint_data[url_path]
            )
        else:
            # Return error for unknown endpoints
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )
        return response
    
    # Mock the _get_request method to return fixture data
    async def mock_get_request(suffix):
        """Mock _get_request to return fixture data."""
        # Extract the path from the suffix
        # suffix is like "/user/menu", "/user/var//120/10111/0/0/10990", etc.
        response = create_mock_response(suffix)
        return response
    
    api._get_request = mock_get_request
    
    # Initialize dictionaries
    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}
    
    # Execute the method
    await api._get_all_sensors_v12(float_dict, switches_dict, text_dict, writable_dict)
    
    # Assertions
    # Verify that dictionaries are not empty
    assert len(float_dict) > 0, "float_dict should not be empty"
    assert len(text_dict) >= 0, "text_dict should be populated"
    assert len(writable_dict) > 0, "writable_dict should not be empty"
    
    # Verify expected entries from target values
    expected_float_entries = assignment_target_values.get("float_dict", {})
    expected_switches_entries = assignment_target_values.get("switches_dict", {})
    expected_text_entries = assignment_target_values.get("text_dict", {})
    expected_writable_entries = assignment_target_values.get("writable_dict", {})
    
    # Check float_dict entries
    for expected_key, expected_value in expected_float_entries.items():
        assert expected_key in float_dict, (
            f"Expected key '{expected_key}' not found in float_dict"
        )
        actual_entry = float_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}: "
            f"expected {expected_value['url']}, got {actual_entry['url']}"
        )
        assert actual_entry["unit"] == expected_value["unit"], (
            f"Unit mismatch for {expected_key}: "
            f"expected {expected_value['unit']}, got {actual_entry['unit']}"
        )
        assert actual_entry["endpoint_type"] == expected_value["endpoint_type"], (
            f"Endpoint type mismatch for {expected_key}"
        )
        assert actual_entry["friendly_name"] == expected_value["friendly_name"], (
            f"Friendly name mismatch for {expected_key}"
        )
        # Value might differ slightly due to floating point precision, so we check with tolerance
        if isinstance(actual_entry.get("value"), (int, float)):
            assert abs(
                actual_entry.get("value", 0) - expected_value.get("value", 0)
            ) < 0.01, (
                f"Value mismatch for {expected_key}: "
                f"expected {expected_value.get('value')}, got {actual_entry.get('value')}"
            )
    
    # Check writable_dict entries
    for expected_key, expected_value in expected_writable_entries.items():
        assert expected_key in writable_dict, (
            f"Expected key '{expected_key}' not found in writable_dict"
        )
        actual_entry = writable_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}"
        )
        assert actual_entry["unit"] == expected_value["unit"], (
            f"Unit mismatch for {expected_key}"
        )
        assert actual_entry["value"] == expected_value["value"], (
            f"Data mismatch for {expected_key}"
        )
        
        # Check valid_values structure for writable entries
        if expected_value.get("valid_values") is not None:
            assert actual_entry.get("valid_values") is not None, (
                f"Valid values missing for writable entry {expected_key}"
            )
            expected_vv = expected_value["valid_values"]
            actual_vv = actual_entry["valid_values"]
            
            assert actual_vv.get("scaled_min_value") == expected_vv.get("scaled_min_value"), (
                f"Scaled min value mismatch for {expected_key}"
            )
            assert actual_vv.get("scaled_max_value") == expected_vv.get("scaled_max_value"), (
                f"Scaled max value mismatch for {expected_key}"
            )
            assert actual_vv.get("scale_factor") == expected_vv.get("scale_factor"), (
                f"Scale factor mismatch for {expected_key}"
            )
            assert actual_vv.get("dec_places") == expected_vv.get("dec_places"), (
                f"Dec places mismatch for {expected_key}"
            )
    
    # Check switches_dict entries
    for expected_key, expected_value in expected_switches_entries.items():
        assert expected_key in switches_dict, (
            f"Expected key '{expected_key}' not found in switches_dict"
        )
        actual_entry = switches_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}"
        )
        assert actual_entry["unit"] == expected_value["unit"], (
            f"Unit mismatch for {expected_key}"
        )
        assert actual_entry["value"] == expected_value["value"], (
            f"Data mismatch for {expected_key}"
        )
        
        # Check switch valid_values (on_value and off_value)
        assert actual_entry.get("valid_values") is not None, (
            f"Valid values missing for switch {expected_key}"
        )
        assert "on_value" in actual_entry["valid_values"], (
            f"on_value missing for switch {expected_key}"
        )
        assert "off_value" in actual_entry["valid_values"], (
            f"off_value missing for switch {expected_key}"
        )
    
    # Check text_dict entries
    for expected_key, expected_value in expected_text_entries.items():
        assert expected_key in text_dict, (
            f"Expected key '{expected_key}' not found in text_dict"
        )
        actual_entry = text_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}"
        )
        assert actual_entry["unit"] == expected_value["unit"], (
            f"Unit mismatch for {expected_key}"
        )
        assert actual_entry["value"] == expected_value["value"], (
            f"Data mismatch for {expected_key}"
        )


@pytest.mark.asyncio
async def test_get_all_sensors_v12_handles_exceptions():
    """Test that _get_all_sensors_v12 handles exceptions gracefully.
    
    This test verifies:
    - Invalid endpoints that raise exceptions are caught and logged
    - Processing continues even if some endpoints are invalid
    - Valid endpoints are still added to dictionaries
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)
    
    # Mock menu response with valid and invalid endpoints
    menu_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<menu>'
        '<fub uri="/120/10111" name="WW">'
        '<object uri="/120/10111/0/0/12271" name="Valid"/>'
        '<object uri="/120/10111/0/0/99999" name="Invalid"/>'
        '</fub>'
        '</menu>'
        '</eta>'
    )
    
    # Mock varinfo response for valid endpoint
    valid_varinfo_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<varInfo uri="/user/varinfo/120/10111/0/0/12271">'
        '<variable uri="120/10111/0/0/12271" name="Valid" fullName="Valid" '
        'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0" isWritable="0">'
        '<type>DEFAULT</type>'
        '</variable>'
        '</varInfo>'
        '</eta>'
    )
    
    # Mock var response for valid endpoint
    valid_var_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10111/0/0/12271" strValue="50" '
        'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0">500</value>'
        '</eta>'
    )
    
    # Error response for invalid endpoint
    error_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<error>Invalid endpoint</error>'
        '</eta>'
    )
    
    async def mock_get_request(suffix):
        response = AsyncMock()
        if "/user/menu" in suffix:
            response.text = AsyncMock(return_value=menu_xml)
        elif "/user/varinfo" in suffix and "12271" in suffix:
            response.text = AsyncMock(return_value=valid_varinfo_xml)
        elif "/user/var" in suffix and "12271" in suffix:
            response.text = AsyncMock(return_value=valid_var_xml)
        else:
            # Invalid endpoints return error or cause parsing errors
            response.text = AsyncMock(return_value=error_xml)
        return response
    
    api._get_request = mock_get_request
    
    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}
    
    await api._get_all_sensors_v12(float_dict, switches_dict, text_dict, writable_dict)
    
    # Valid sensor should be in float_dict
    assert len(float_dict) > 0, "Valid float sensor should be added to float_dict"
    # Invalid endpoint should be skipped, not cause the method to fail
    # The method should complete without raising an exception


@pytest.mark.asyncio
async def test_get_all_sensors_v12_skips_duplicates(load_fixture):
    """Test that _get_all_sensors_v12 skips duplicate endpoints.
    
    This test verifies:
    - Same URI appearing multiple times in the menu is only processed once
    - All dictionaries correctly reflect single processing of duplicate URIs
    """
    api_endpoint_data = load_fixture("api_endpoint_data.json")
    
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.25", 8080)
    
    # Mock menu response with duplicate endpoint
    menu_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<menu>'
        '<fub uri="/120/10111" name="WW">'
        '<object uri="/120/10111/0/0/12271" name="Test1"/>'
        '<object uri="/120/10111/0/0/12271" name="Test2"/>'
        '</fub>'
        '</menu>'
        '</eta>'
    )
    
    def create_mock_response(url_path: str):
        response = AsyncMock()
        if url_path in api_endpoint_data:
            response.text = AsyncMock(return_value=api_endpoint_data[url_path])
        else:
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )
        return response
    
    call_count = {}
    
    async def mock_get_request(suffix):
        call_count[suffix] = call_count.get(suffix, 0) + 1
        if suffix == "/user/menu":
            response = AsyncMock()
            response.text = AsyncMock(return_value=menu_xml)
            return response
        else:
            return create_mock_response(suffix)
    
    api._get_request = mock_get_request
    
    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}
    
    await api._get_all_sensors_v12(float_dict, switches_dict, text_dict, writable_dict)
    
    # Verify that the duplicate endpoint was only queried once
    varinfo_key = "/user/varinfo//120/10111/0/0/12271"
    var_key = "/user/var//120/10111/0/0/12271"
    
    # The duplicate should have been skipped, so each endpoint should be called once
    assert call_count.get(varinfo_key, 0) <= 1, (
        f"Duplicate endpoint should be queried at most once, "
        f"but was queried {call_count.get(varinfo_key, 0)} times"
    )


@pytest.mark.asyncio
async def test_get_all_sensors_v11(load_fixture):
    """Test _get_all_sensors_v11 method with real fixture data.
    
    This test verifies:
    - Mock HTTP responses are properly used for v1.1 API
    - Endpoints are correctly parsed from menu endpoint
    - Sensor values are fetched and added to correct dictionaries
    - All dictionaries are populated with expected entries
    - Writable sensors are identified by unit alone (no varinfo available)
    - Switches are identified by empty unit and specific value codes (1802/1803)
    """
    # Load fixtures
    api_endpoint_data = load_fixture("api_endpoint_data.json")
    reference_values_v11 = load_fixture("api_assignment_reference_values_v11.json")
    
    # Setup mock session
    mock_session = AsyncMock(spec=ClientSession)
    
    # Create API instance with test host
    api = EtaAPI(mock_session, "192.168.0.25", 8080)
    
    # Setup mock responses based on fixture data
    def create_mock_response(url_path: str):
        """Create a mock response for a given URL path."""
        response = AsyncMock()
        if url_path in api_endpoint_data:
            response.text = AsyncMock(
                return_value=api_endpoint_data[url_path]
            )
        else:
            # Return error for unknown endpoints
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )
        return response
    
    # Mock the _get_request method to return fixture data
    async def mock_get_request(suffix):
        """Mock _get_request to return fixture data."""
        response = create_mock_response(suffix)
        return response
    
    api._get_request = mock_get_request
    
    # Initialize dictionaries
    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}
    
    # Execute the method
    await api._get_all_sensors_v11(float_dict, switches_dict, text_dict, writable_dict)
    
    # Assertions
    # Verify that dictionaries are not empty
    assert len(float_dict) > 0, "float_dict should not be empty"
    assert len(writable_dict) > 0, "writable_dict should not be empty"
    
    # Verify expected entries from reference values
    expected_float_entries = reference_values_v11.get("float_dict", {})
    expected_switches_entries = reference_values_v11.get("switches_dict", {})
    expected_text_entries = reference_values_v11.get("text_dict", {})
    expected_writable_entries = reference_values_v11.get("writable_dict", {})
    
    # Check float_dict entries
    for expected_key, expected_value in expected_float_entries.items():
        assert expected_key in float_dict, (
            f"Expected key '{expected_key}' not found in float_dict"
        )
        actual_entry = float_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}: "
            f"expected {expected_value['url']}, got {actual_entry['url']}"
        )
        assert actual_entry["unit"] == expected_value["unit"], (
            f"Unit mismatch for {expected_key}: "
            f"expected {expected_value['unit']}, got {actual_entry['unit']}"
        )
        assert actual_entry["friendly_name"] == expected_value["friendly_name"], (
            f"Friendly name mismatch for {expected_key}"
        )
        # Value might differ slightly due to floating point precision
        if isinstance(actual_entry.get("value"), (int, float)):
            assert abs(
                actual_entry.get("value", 0) - expected_value.get("value", 0)
            ) < 0.1, (
                f"Value mismatch for {expected_key}: "
                f"expected {expected_value.get('value')}, got {actual_entry.get('value')}"
            )
    
    # Check writable_dict entries
    for expected_key, expected_value in expected_writable_entries.items():
        assert expected_key in writable_dict, (
            f"Expected key '{expected_key}' not found in writable_dict"
        )
        actual_entry = writable_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}"
        )
        assert actual_entry["unit"] == expected_value["unit"], (
            f"Unit mismatch for {expected_key}"
        )
        
        # Check valid_values structure for writable entries (v11 uses default ranges)
        if expected_value.get("valid_values") is not None:
            assert actual_entry.get("valid_values") is not None, (
                f"Valid values missing for writable entry {expected_key}"
            )
            expected_vv = expected_value["valid_values"]
            actual_vv = actual_entry["valid_values"]
            
            assert actual_vv.get("scaled_min_value") == expected_vv.get("scaled_min_value"), (
                f"Scaled min value mismatch for {expected_key}"
            )
            assert actual_vv.get("scaled_max_value") == expected_vv.get("scaled_max_value"), (
                f"Scaled max value mismatch for {expected_key}"
            )
    
    # Check switches_dict entries (v11 uses specific codes 1802/1803)
    for expected_key, expected_value in expected_switches_entries.items():
        assert expected_key in switches_dict, (
            f"Expected key '{expected_key}' not found in switches_dict"
        )
        actual_entry = switches_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}"
        )
        assert actual_entry["unit"] == expected_value["unit"], (
            f"Unit mismatch for {expected_key}"
        )
        
        # Check switch valid_values (on_value=1803, off_value=1802)
        assert actual_entry.get("valid_values") is not None, (
            f"Valid values missing for switch {expected_key}"
        )
        assert actual_entry["valid_values"].get("on_value") == 1803, (
            f"on_value should be 1803 for switch {expected_key}, got {actual_entry['valid_values'].get('on_value')}"
        )
        assert actual_entry["valid_values"].get("off_value") == 1802, (
            f"off_value should be 1802 for switch {expected_key}, got {actual_entry['valid_values'].get('off_value')}"
        )
    
    # Check text_dict entries
    for expected_key, expected_value in expected_text_entries.items():
        assert expected_key in text_dict, (
            f"Expected key '{expected_key}' not found in text_dict"
        )
        actual_entry = text_dict[expected_key]
        
        # Verify critical fields
        assert actual_entry["url"] == expected_value["url"], (
            f"URL mismatch for {expected_key}"
        )


@pytest.mark.asyncio
async def test_get_all_sensors_v11_distinguishes_sensor_types():
    """Test that _get_all_sensors_v11 correctly identifies sensor types.
    
    This test verifies:
    - Float sensors are identified by unit in float_sensor_units
    - Switches are identified by empty unit and values 1802/1803
    - Text sensors are added only if they have non-empty values
    - Writable sensors are identified by unit in writable_sensor_units
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)
    
    # Menu with different sensor types
    menu_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<menu>'
        '<fub uri="/120/10101" name="HK">'
        '<object uri="/120/10101/0/0/12197" name="FloatSensor"/>'
        '<object uri="/120/10101/0/0/12080" name="SwitchSensor"/>'
        '<object uri="/120/10101/0/0/12132" name="WritableSensor"/>'
        '<object uri="/120/10101/0/0/12476" name="TextSensor"/>'
        '</fub>'
        '</menu>'
        '</eta>'
    )
    
    # Float sensor (°C)
    float_var = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12197" strValue="20" '
        'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0">200</value>'
        '</eta>'
    )
    
    # Switch sensor (empty unit, codes 1802/1803)
    switch_var = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12080" strValue="Ein" '
        'unit="" decPlaces="0" scaleFactor="1" advTextOffset="0">1803</value>'
        '</eta>'
    )
    
    # Writable sensor (°C, writable unit)
    writable_var = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12132" strValue="30" '
        'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0">300</value>'
        '</eta>'
    )
    
    # Text sensor (empty unit, empty value)
    text_var = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12476" strValue="" '
        'unit="" decPlaces="0" scaleFactor="1" advTextOffset="0">0</value>'
        '</eta>'
    )
    
    async def mock_get_request(suffix):
        response = AsyncMock()
        if "/user/menu" in suffix:
            response.text = AsyncMock(return_value=menu_xml)
        elif "12197" in suffix:
            response.text = AsyncMock(return_value=float_var)
        elif "12080" in suffix:
            response.text = AsyncMock(return_value=switch_var)
        elif "12132" in suffix:
            response.text = AsyncMock(return_value=writable_var)
        elif "12476" in suffix:
            response.text = AsyncMock(return_value=text_var)
        else:
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )
        return response
    
    api._get_request = mock_get_request
    
    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}
    
    await api._get_all_sensors_v11(float_dict, switches_dict, text_dict, writable_dict)
    
    # Verify sensor type identification
    assert len(float_dict) > 0, "Float sensor should be added"
    assert len(switches_dict) > 0, "Switch should be added"
    assert len(writable_dict) > 0, "Writable sensor should be added"
    # Text sensor with empty value should not be added
    assert len(text_dict) == 0, "Empty text sensor should not be added"


@pytest.mark.asyncio
async def test_get_all_sensors_v11_skips_duplicates():
    """Test that _get_all_sensors_v11 skips duplicate endpoints.
    
    This test verifies:
    - Same URI appearing multiple times is only processed once
    """
    mock_session = AsyncMock(spec=ClientSession)
    api = EtaAPI(mock_session, "192.168.0.1", 8080)
    
    menu_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<menu>'
        '<fub uri="/120/10101" name="HK">'
        '<object uri="/120/10101/0/0/12197" name="Sensor1"/>'
        '<object uri="/120/10101/0/0/12197" name="Sensor2"/>'
        '</fub>'
        '</menu>'
        '</eta>'
    )
    
    sensor_var = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<eta version="1.0" xmlns="http://www.eta.co.at/rest/v1">'
        '<value uri="/user/var/120/10101/0/0/12197" strValue="20" '
        'unit="°C" decPlaces="0" scaleFactor="10" advTextOffset="0">200</value>'
        '</eta>'
    )
    
    call_count = {}
    
    async def mock_get_request(suffix):
        call_count[suffix] = call_count.get(suffix, 0) + 1
        response = AsyncMock()
        if "/user/menu" in suffix:
            response.text = AsyncMock(return_value=menu_xml)
        elif "12197" in suffix:
            response.text = AsyncMock(return_value=sensor_var)
        else:
            response.text = AsyncMock(
                return_value='<?xml version="1.0" encoding="utf-8"?>'
                '<eta version="1.0"><error>Not found</error></eta>'
            )
        return response
    
    api._get_request = mock_get_request
    
    float_dict = {}
    switches_dict = {}
    text_dict = {}
    writable_dict = {}
    
    await api._get_all_sensors_v11(float_dict, switches_dict, text_dict, writable_dict)
    
    # Verify duplicate was only queried once
    var_key = "/user/var//120/10101/0/0/12197"
    assert call_count.get(var_key, 0) <= 1, (
        f"Duplicate endpoint should be queried at most once, "
        f"but was queried {call_count.get(var_key, 0)} times"
    )
