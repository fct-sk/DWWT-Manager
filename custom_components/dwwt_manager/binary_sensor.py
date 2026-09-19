"""Observed state binary sensors."""
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_BLOWER_ENTITY, CONF_INLET_ENTITY, CONF_INLET_POWER_SENSOR, DOMAIN
from .entity import DwwtEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    entities = [DwwtPumpRunning(manager), DwwtBlowerPhase(manager)]
    if manager.config.get(CONF_INLET_ENTITY) or manager.config.get(CONF_INLET_POWER_SENSOR):
        entities.append(DwwtInletRunning(manager))
    async_add_entities(entities)


class DwwtPumpRunning(DwwtEntity, BinarySensorEntity):
    _attr_translation_key = "pump_running"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    def __init__(self, manager): super().__init__(manager, "pump_running")
    @property
    def is_on(self): return self.manager.state.pump_running


class DwwtBlowerPhase(DwwtEntity, BinarySensorEntity):
    _attr_translation_key = "blower_phase"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    def __init__(self, manager): super().__init__(manager, "blower_phase")
    @property
    def is_on(self): return self.manager.state.blower_phase_on
    @property
    def extra_state_attributes(self): return {"source_entity": self.manager.config[CONF_BLOWER_ENTITY]}


class DwwtInletRunning(DwwtEntity, BinarySensorEntity):
    _attr_translation_key = "inlet_running"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_entity_registry_enabled_default = False
    def __init__(self, manager): super().__init__(manager, "inlet_running")
    @property
    def is_on(self): return self.manager.inlet_running
