"""Snapshot of a config entry that survives uninstalling this integration."""

from typing import Any

from homeassistant import config_entries, core
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_KEY = f"{DOMAIN}.migration"
STORAGE_VERSION = 1


def _device_snapshot(device: dr.DeviceEntry) -> dict[str, Any]:
    return {
        "identifiers": sorted(list(item) for item in device.identifiers),
        "name": device.name,
        "name_by_user": device.name_by_user,
        "area_id": device.area_id,
        "disabled_by": device.disabled_by,
        "labels": sorted(device.labels),
    }


def _entity_snapshot(
    entity: er.RegistryEntry, identifiers: dict[str, list[list[str]]]
) -> dict[str, Any]:
    return {
        "entity_id": entity.entity_id,
        "unique_id": entity.unique_id,
        "device_identifiers": identifiers.get(entity.device_id or ""),
        "name": entity.name,
        "icon": entity.icon,
        "area_id": entity.area_id,
        "disabled_by": entity.disabled_by,
        "hidden_by": entity.hidden_by,
        "labels": sorted(entity.labels),
        "options": {key: dict(value) for key, value in entity.options.items()},
        "original_name": entity.original_name,
        "original_device_class": entity.original_device_class,
        "unit_of_measurement": entity.unit_of_measurement,
        "entity_category": entity.entity_category,
    }


async def async_save_snapshot(
    hass: core.HomeAssistant, entry: config_entries.ConfigEntry
) -> None:
    """Store everything needed to restore this entry after a repository switch."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
    identifiers = {
        device.id: sorted(list(item) for item in device.identifiers)
        for device in devices
    }

    store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    snapshots = await store.async_load() or {}
    snapshots[entry.entry_id] = {
        "version": entry.version,
        "minor_version": entry.minor_version,
        "title": entry.title,
        "data": {**entry.data, **entry.options},
        "devices": [_device_snapshot(device) for device in devices],
        "entities": [
            _entity_snapshot(entity, identifiers)
            for entity in er.async_entries_for_config_entry(
                entity_registry, entry.entry_id
            )
        ],
    }
    await store.async_save(snapshots)
