"""Unit tests for config_flow helper logic."""

from custom_components.eta_webservices.config_flow import (
    _is_invalid_host_input,
    _is_unspecified_host,
    _sanitize_selected_entity_ids,
)


def test_sanitize_selected_entity_ids_removes_cross_category_duplicates():
    """IDs selected in multiple regular sensor groups must be deduplicated."""
    selected_float_sensors = ["a", "b", "a"]
    selected_switches = ["b", "c", "c"]
    selected_text_sensors = ["a", "c", "d", "d"]
    selected_writable_sensors = ["w1", "w1"]

    (
        sanitized_float_sensors,
        sanitized_switches,
        sanitized_text_sensors,
        sanitized_writable_sensors,
    ) = _sanitize_selected_entity_ids(
        selected_float_sensors,
        selected_switches,
        selected_text_sensors,
        selected_writable_sensors,
    )

    assert sanitized_float_sensors == ["a", "b"]
    assert sanitized_switches == ["c"]
    assert sanitized_text_sensors == ["d"]
    assert sanitized_writable_sensors == ["w1"]


def test_sanitize_selected_entity_ids_keeps_non_overlapping_selections():
    """Selections without overlaps should remain unchanged."""
    selected_float_sensors = ["float_1"]
    selected_switches = ["switch_1"]
    selected_text_sensors = ["text_1"]
    selected_writable_sensors = ["writable_1", "writable_2"]

    (
        sanitized_float_sensors,
        sanitized_switches,
        sanitized_text_sensors,
        sanitized_writable_sensors,
    ) = _sanitize_selected_entity_ids(
        selected_float_sensors,
        selected_switches,
        selected_text_sensors,
        selected_writable_sensors,
    )

    assert sanitized_float_sensors == selected_float_sensors
    assert sanitized_switches == selected_switches
    assert sanitized_text_sensors == selected_text_sensors
    assert sanitized_writable_sensors == selected_writable_sensors


def test_is_unspecified_host_rejects_placeholder_ip_addresses():
    """Unspecified IP placeholders must not be accepted as ETA hosts."""
    assert _is_unspecified_host("0.0.0.0")
    assert _is_unspecified_host("::")
    assert _is_unspecified_host(" [::] ")


def test_is_unspecified_host_accepts_real_hosts():
    """Valid concrete hosts should pass the unspecified-host check."""
    assert not _is_unspecified_host("172.24.120.210")
    assert not _is_unspecified_host("eta.local")


def test_is_invalid_host_input_rejects_malformed_hosts():
    """Malformed host inputs must be rejected before discovery starts."""
    assert _is_invalid_host_input(":")
    assert _is_invalid_host_input("%")
    assert _is_invalid_host_input("host name")
    assert _is_invalid_host_input("foo_bar.local")
    assert _is_invalid_host_input("-eta.local")
    assert _is_invalid_host_input("eta-.local")
    assert _is_invalid_host_input("http://172.24.120.210")
    assert _is_invalid_host_input("172.24.120.210/path")
    assert _is_invalid_host_input("[172.24.120.210]")
    assert _is_invalid_host_input("[::")


def test_is_invalid_host_input_accepts_valid_hosts():
    """Normal hostname/IP inputs should be accepted."""
    assert not _is_invalid_host_input("172.24.120.210")
    assert not _is_invalid_host_input("eta.local")
    assert not _is_invalid_host_input("[2001:db8::1]")
