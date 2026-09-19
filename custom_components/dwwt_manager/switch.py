"""Blower automation enable switch."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import DwwtEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([DwwtControlSwitch(hass.data[DOMAIN][entry.entry_id])])


class DwwtControlSwitch(DwwtEntity, SwitchEntity):
    _attr_translation_key = "control"
    _attr_icon = "mdi:autorenew"

    def __init__(self, manager) -> None:
        super().__init__(manager, "control")

    @property
    def is_on(self) -> bool:
        return self.manager.control_enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self.manager.async_set_control_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.manager.async_set_control_enabled(False)
