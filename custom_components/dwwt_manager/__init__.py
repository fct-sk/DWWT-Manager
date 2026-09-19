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
    CONF_SCHEDULES,
    DOMAIN,
    LEGACY_MODE_MAP,
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
    """Migrate device assignments and beta5 operating-mode schedules."""
    data = dict(entry.data)
    options = dict(entry.options)
    version = entry.version

    if version < 2:
        mappings = (
            (CONF_BLOWER_DEVICE, (CONF_BLOWER_ENTITY,)),
            (CONF_PUMP_DEVICE, (CONF_PUMP_POWER_SENSOR, CONF_PUMP_ENTITY)),
            (CONF_INLET_DEVICE, (CONF_INLET_POWER_SENSOR, CONF_INLET_ENTITY)),
        )
        for device_key, entity_keys in mappings:
            device_id = next(
                (value for key in entity_keys if (value := async_device_id_from_entity(hass, data.get(key)))),
                None,
            )
            if device_id:
                data[device_key] = device_id
            elif device_key != CONF_INLET_DEVICE:
                _LOGGER.error("Cannot migrate %s: source entity has no registered device", device_key)
                return False
        for key in (CONF_BLOWER_ENTITY, CONF_PUMP_ENTITY, CONF_PUMP_POWER_SENSOR, CONF_INLET_ENTITY, CONF_INLET_POWER_SENSOR):
            data.pop(key, None)
        version = 2

    if version < 3:
        for container in (data, options):
            schedules = container.get(CONF_SCHEDULES)
            if not isinstance(schedules, dict):
                continue
            migrated = dict(schedules)
            for old_id, new_mode in LEGACY_MODE_MAP.items():
                if old_id in schedules and new_mode.value not in migrated:
                    # Copy the exact user values; never replace them with new defaults.
                    migrated[new_mode.value] = dict(schedules[old_id])
                migrated.pop(old_id, None)
            container[CONF_SCHEDULES] = migrated
        version = 3

    hass.config_entries.async_update_entry(entry, data=data, options=options, version=version)
    _LOGGER.info("Migrated DWWT Manager config entry %s to version %s", entry.entry_id, version)
    return True

async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
