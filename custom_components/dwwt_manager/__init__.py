"""DWWT Manager integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryNotReady
from homeassistant.core import HomeAssistant

from .const import (
    CONF_BLOWER_DEVICE,
    CONF_BLOWER_ENTITY,
    CONF_INLET_DEVICE,
    CONF_INLET_ENTITY,
    CONF_INLET_POWER_SENSOR,
    CONF_PUMP_DEVICE,
    CONF_PUMP_ENTITY,
    CONF_PUMP_POWER_SENSOR,
    DOMAIN,
    PLATFORMS,
)
from .device_resolver import (
    DeviceResolutionError,
    async_device_id_from_entity,
    async_resolve_config,
)
from .manager import DwwtManager

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    config = {**entry.data, **entry.options}
    try:
        resolved_entities = async_resolve_config(hass, config)
    except DeviceResolutionError as err:
        raise ConfigEntryNotReady(
            f"Unable to resolve {err.role.value} device: {err.translation_key}"
        ) from err

    manager = DwwtManager(hass, entry)
    manager.config.update(resolved_entities)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager
    await manager.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    manager: DwwtManager = hass.data[DOMAIN].pop(entry.entry_id)
    await manager.async_stop()
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate entity-based equipment assignments to stable device ids."""
    if entry.version >= 2:
        return True

    data = dict(entry.data)
    mappings = (
        (CONF_BLOWER_DEVICE, (CONF_BLOWER_ENTITY,)),
        (CONF_PUMP_DEVICE, (CONF_PUMP_POWER_SENSOR, CONF_PUMP_ENTITY)),
        (CONF_INLET_DEVICE, (CONF_INLET_POWER_SENSOR, CONF_INLET_ENTITY)),
    )
    for device_key, entity_keys in mappings:
        device_id = None
        for entity_key in entity_keys:
            device_id = async_device_id_from_entity(hass, data.get(entity_key))
            if device_id:
                break
        if device_id:
            data[device_key] = device_id
        elif device_key != CONF_INLET_DEVICE:
            _LOGGER.error("Cannot migrate %s: source entity has no registered device", device_key)
            return False

    for key in (
        CONF_BLOWER_ENTITY,
        CONF_PUMP_ENTITY,
        CONF_PUMP_POWER_SENSOR,
        CONF_INLET_ENTITY,
        CONF_INLET_POWER_SENSOR,
    ):
        data.pop(key, None)

    hass.config_entries.async_update_entry(entry, data=data, version=2)
    _LOGGER.info("Migrated DWWT Manager config entry %s to device selection", entry.entry_id)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)