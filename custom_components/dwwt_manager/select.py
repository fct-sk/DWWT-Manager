"""Mode selection platform."""
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, OperatingMode
from .entity import DwwtEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([DwwtModeSelect(hass.data[DOMAIN][entry.entry_id])])


class DwwtModeSelect(DwwtEntity, SelectEntity):
    _attr_translation_key = "operating_mode"
    _attr_icon = "mdi:tune-variant"
    _attr_options = [mode.value for mode in OperatingMode]

    def __init__(self, manager) -> None:
        super().__init__(manager, "operating_mode")

    @property
    def current_option(self) -> str:
        return self.manager.state.requested_mode.value

    async def async_select_option(self, option: str) -> None:
        await self.manager.async_select_mode(OperatingMode(option))
