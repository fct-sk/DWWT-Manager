"""DWWT Manager sensors."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import DwwtEntity


@dataclass(frozen=True, kw_only=True)
class DwwtSensorDescription(SensorEntityDescription):
    value_fn: Callable = lambda manager: None


SENSORS = (
    DwwtSensorDescription(key="active_mode", translation_key="active_mode", device_class=SensorDeviceClass.ENUM, options=["normal", "low_load", "heavy_load", "eco"] , value_fn=lambda m: m.state.active_mode.value),
    DwwtSensorDescription(key="auto_reason", translation_key="auto_reason", value_fn=lambda m: m.state.auto_reason),
    DwwtSensorDescription(key="manufacturer_configuration", translation_key="manufacturer_configuration", icon="mdi:factory", device_class=SensorDeviceClass.ENUM, options=["coming_soon"], value_fn=lambda m: "coming_soon"),
    DwwtSensorDescription(key="pump_starts_total", translation_key="pump_starts_total", icon="mdi:pump", state_class=SensorStateClass.TOTAL, value_fn=lambda m: m.state.pump_starts_total),
    DwwtSensorDescription(key="pumped_volume_total", translation_key="pumped_volume_total", native_unit_of_measurement=UnitOfVolume.LITERS, device_class=SensorDeviceClass.VOLUME, state_class=SensorStateClass.TOTAL, suggested_display_precision=1, value_fn=lambda m: m.lifetime_volume),
    *tuple(DwwtSensorDescription(key=f"volume_{period}", translation_key=f"volume_{period}", native_unit_of_measurement=UnitOfVolume.LITERS, device_class=SensorDeviceClass.VOLUME, state_class=SensorStateClass.TOTAL, suggested_display_precision=1, value_fn=lambda m, p=period: m.volume_period(p)) for period in ("day", "week", "month", "year")),
    *tuple(DwwtSensorDescription(key=f"starts_{hours}h", translation_key=f"starts_{hours}h", icon="mdi:pump", state_class=SensorStateClass.MEASUREMENT, entity_registry_enabled_default=hours != 6, value_fn=lambda m, h=hours: m.starts(h)) for hours in (1, 6, 24)),
    DwwtSensorDescription(key="volume_24h", translation_key="volume_24h", native_unit_of_measurement=UnitOfVolume.LITERS, device_class=SensorDeviceClass.VOLUME, state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, value_fn=lambda m: m.volume_window(24)),
    DwwtSensorDescription(key="phase_remaining", translation_key="phase_remaining", native_unit_of_measurement=UnitOfTime.SECONDS, device_class=SensorDeviceClass.DURATION, state_class=SensorStateClass.MEASUREMENT, value_fn=lambda m: m.phase_remaining_seconds),
    DwwtSensorDescription(key="last_pump_start", translation_key="last_pump_start", device_class=SensorDeviceClass.TIMESTAMP, entity_registry_enabled_default=False, value_fn=lambda m: m.last_activity),
    DwwtSensorDescription(key="last_pump_stop", translation_key="last_pump_stop", device_class=SensorDeviceClass.TIMESTAMP, entity_registry_enabled_default=False, value_fn=lambda m: m.state.last_pump_stop),
    DwwtSensorDescription(key="last_mode_change", translation_key="last_mode_change", device_class=SensorDeviceClass.TIMESTAMP, entity_registry_enabled_default=False, value_fn=lambda m: m.state.last_mode_change),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DwwtSensor(manager, description) for description in SENSORS])


class DwwtSensor(DwwtEntity, SensorEntity):
    entity_description: DwwtSensorDescription
    def __init__(self, manager, description):
        super().__init__(manager, description.key)
        self.entity_description = description
    @property
    def native_value(self):
        return self.entity_description.value_fn(self.manager)
