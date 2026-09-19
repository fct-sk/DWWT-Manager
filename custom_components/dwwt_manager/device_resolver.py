"""Resolve user-selected Home Assistant devices to their usable entities."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_BLOWER_DEVICE,
    CONF_BLOWER_ENTITY,
    CONF_INLET_DEVICE,
    CONF_INLET_ENTITY,
    CONF_INLET_POWER_SENSOR,
    CONF_PUMP_DEVICE,
    CONF_PUMP_ENTITY,
    CONF_PUMP_POWER_SENSOR,
)


class DeviceRole(StrEnum):
    """Supported equipment roles."""

    BLOWER = "blower"
    PUMP = "pump"
    INLET = "inlet"


class DeviceResolutionError(ValueError):
    """A selected device does not expose an unambiguous required entity."""

    def __init__(self, translation_key: str, role: DeviceRole) -> None:
        super().__init__(translation_key)
        self.translation_key = translation_key
        self.role = role


@dataclass(frozen=True, slots=True)
class ResolvedDevice:
    """Entities discovered for one selected smart plug."""

    switch_entity: str | None
    power_sensor: str | None


def _entries_for_device(hass: HomeAssistant, device_id: str) -> list[er.RegistryEntry]:
    registry = er.async_get(hass)
    return list(er.async_entries_for_device(registry, device_id))


def _power_device_class(hass: HomeAssistant, entry: er.RegistryEntry) -> str | None:
    state = hass.states.get(entry.entity_id)
    state_class = state.attributes.get("device_class") if state else None
    return entry.device_class or entry.original_device_class or state_class


def _single(candidates: list[str], missing: str, ambiguous: str, role: DeviceRole) -> str:
    if not candidates:
        raise DeviceResolutionError(missing, role)
    if len(candidates) > 1:
        raise DeviceResolutionError(ambiguous, role)
    return candidates[0]


def async_resolve_device(hass: HomeAssistant, device_id: str, role: DeviceRole) -> ResolvedDevice:
    """Resolve a smart plug without relying on user-editable entity IDs."""
    entries = _entries_for_device(hass, device_id)
    if not entries:
        raise DeviceResolutionError("device_not_found", role)

    switches = sorted(entry.entity_id for entry in entries if entry.domain == Platform.SWITCH)
    power = sorted(
        entry.entity_id
        for entry in entries
        if entry.domain == Platform.SENSOR
        and _power_device_class(hass, entry) == SensorDeviceClass.POWER
    )

    if role == DeviceRole.BLOWER:
        switch = _single(switches, "blower_switch_missing", "blower_switch_ambiguous", role)
        return ResolvedDevice(switch, power[0] if len(power) == 1 else None)

    power_sensor = _single(power, "pump_power_missing", "pump_power_ambiguous", role)
    return ResolvedDevice(switches[0] if len(switches) == 1 else None, power_sensor)


def async_resolve_config(hass: HomeAssistant, config: dict) -> dict[str, str]:
    """Resolve all configured equipment devices into runtime entity IDs."""
    resolved: dict[str, str] = {}
    blower = async_resolve_device(hass, config[CONF_BLOWER_DEVICE], DeviceRole.BLOWER)
    resolved[CONF_BLOWER_ENTITY] = blower.switch_entity

    pump = async_resolve_device(hass, config[CONF_PUMP_DEVICE], DeviceRole.PUMP)
    resolved[CONF_PUMP_POWER_SENSOR] = pump.power_sensor
    if pump.switch_entity:
        resolved[CONF_PUMP_ENTITY] = pump.switch_entity

    if inlet_device := config.get(CONF_INLET_DEVICE):
        inlet = async_resolve_device(hass, inlet_device, DeviceRole.INLET)
        resolved[CONF_INLET_POWER_SENSOR] = inlet.power_sensor
        if inlet.switch_entity:
            resolved[CONF_INLET_ENTITY] = inlet.switch_entity
    return resolved


def async_device_id_from_entity(hass: HomeAssistant, entity_id: str | None) -> str | None:
    """Return the owning device id for legacy entity-based configuration."""
    if not entity_id:
        return None
    entry = er.async_get(hass).async_get(entity_id)
    return entry.device_id if entry else None