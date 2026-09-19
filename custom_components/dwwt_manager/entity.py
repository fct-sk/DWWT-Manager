"""Shared DWWT entity base."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import CONF_MANUFACTURER, CONF_MODEL, CONF_NAME, DOMAIN, SIGNAL_UPDATE
from .manager import DwwtManager


class DwwtEntity(Entity):
    _attr_has_entity_name = True

    def __init__(self, manager: DwwtManager, key: str) -> None:
        self.manager = manager
        self._attr_unique_id = f"{manager.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.entry.entry_id)},
            name=manager.config[CONF_NAME],
            manufacturer=manager.config.get(CONF_MANUFACTURER) or "DWWT Manager",
            model=manager.config.get(CONF_MODEL) or "Wastewater treatment plant",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATE.format(entry_id=self.manager.entry.entry_id), self.async_write_ha_state))
