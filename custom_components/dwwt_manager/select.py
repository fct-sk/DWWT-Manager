"""Configuration and operating-mode selection entities."""
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import AerationConfiguration, DOMAIN, ModeSelection, OperatingMode
from .entity import DwwtEntity

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        DwwtAerationConfigurationSelect(manager),
        DwwtModeSelectionSelect(manager),
        DwwtManualOperatingModeSelect(manager),
    ])

class DwwtAerationConfigurationSelect(DwwtEntity, SelectEntity):
    _attr_translation_key = "aeration_configuration"
    _attr_icon = "mdi:air-filter"
    _attr_options = [AerationConfiguration.MANUAL.value, AerationConfiguration.AUTOMATIC.value]
    def __init__(self, manager) -> None:
        super().__init__(manager, "aeration_configuration")
    @property
    def current_option(self) -> str:
        return self.manager.state.aeration_configuration.value
    async def async_select_option(self, option: str) -> None:
        await self.manager.async_select_aeration_configuration(AerationConfiguration(option))

class DwwtModeSelectionSelect(DwwtEntity, SelectEntity):
    _attr_translation_key = "mode_selection"
    _attr_icon = "mdi:tune-variant"
    _attr_options = [mode.value for mode in ModeSelection]
    def __init__(self, manager) -> None:
        super().__init__(manager, "mode_selection")
    @property
    def current_option(self) -> str:
        return self.manager.state.mode_selection.value
    async def async_select_option(self, option: str) -> None:
        await self.manager.async_select_mode_selection(ModeSelection(option))

class DwwtManualOperatingModeSelect(DwwtEntity, SelectEntity):
    _attr_translation_key = "manual_operating_mode"
    _attr_icon = "mdi:waves"
    _attr_options = [mode.value for mode in OperatingMode]
    def __init__(self, manager) -> None:
        super().__init__(manager, "manual_operating_mode")
    @property
    def current_option(self) -> str:
        return self.manager.state.manual_mode.value
    async def async_select_option(self, option: str) -> None:
        await self.manager.async_select_manual_mode(OperatingMode(option))
