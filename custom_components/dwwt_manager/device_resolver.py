"""Resolve explicit blower outputs and device-based pump inputs."""
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
    CONF_BLOWER_REGISTRY_ID,
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
    """Equipment has no valid explicit output or unambiguous required input."""

    def __init__(self, translation_key: str, role: DeviceRole) -> None:
        super().__init__(translation_key)
        self.translation_key = translation_key
        self.role = role


@dataclass(frozen=True, slots=True)
class ResolvedDevice:
    """Existing pump-device representation; no claim about measurement scope."""

    switch_entity: str | None
    power_sensor: str | None


@dataclass(frozen=True, slots=True)
class ResolvedBlower:
    """One chosen output; owner is context, not a second control reference."""

    switch_entity_id: str
    owner_device_id: str | None
    registry_entry_id: str | None

    def as_config(self) -> dict[str, str | None]:
        # Store None too: a new unregistered switch must clear an old registry id.
        return {
            CONF_BLOWER_ENTITY: self.switch_entity_id,
            CONF_BLOWER_REGISTRY_ID: self.registry_entry_id,
        }


def _entries_for_device(hass: HomeAssistant, device_id: str) -> list[er.RegistryEntry]:
    return list(er.async_entries_for_device(er.async_get(hass), device_id))


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


def async_resolve_blower(
    hass: HomeAssistant, entity_id: str | None, registry_entry_id: str | None = None,
) -> ResolvedBlower:
    """Validate an explicit switch; never substitute another device output.

    Registry identity survives entity-id changes. If it disappears, do not fall
    back to the old entity_id, which could now belong to a different output.
    Live unregistered switches are supported, but have no durable rename identity.
    """
    registry = er.async_get(hass)
    if registry_entry_id:
        entry = registry.async_get(registry_entry_id)
        if entry is None:
            raise DeviceResolutionError("blower_entity_removed", DeviceRole.BLOWER)
        entity_id = entry.entity_id
    else:
        if not entity_id:
            raise DeviceResolutionError("blower_selection_required", DeviceRole.BLOWER)
        entry = registry.async_get(entity_id)

    if not isinstance(entity_id, str) or not entity_id.startswith("switch."):
        raise DeviceResolutionError("blower_entity_not_switch", DeviceRole.BLOWER)
    if entry is not None:
        if entry.disabled_by is not None:
            raise DeviceResolutionError("blower_entity_disabled", DeviceRole.BLOWER)
        # Registered but temporarily unavailable is still a valid selection.
        return ResolvedBlower(entity_id, entry.device_id, entry.id)
    if hass.states.get(entity_id) is None:
        raise DeviceResolutionError("blower_entity_missing", DeviceRole.BLOWER)
    return ResolvedBlower(entity_id, None, None)


def async_migrate_blower_config(
    hass: HomeAssistant, data: dict, options: dict,
) -> tuple[dict, dict]:
    """Migrate the effective old reference without guessing or losing other data.

    Missing/ambiguous old devices become an explicit unresolved selection. Setup
    then asks for reconfiguration. Historical explicit selections take precedence
    within their layer; an options device overrides a historical data selection.
    """
    data, options = dict(data), dict(options)
    reference_keys = (CONF_BLOWER_ENTITY, CONF_BLOWER_REGISTRY_ID, CONF_BLOWER_DEVICE)
    selected = options if any(key in options for key in reference_keys) else data
    entity_id = selected.get(CONF_BLOWER_ENTITY)
    registry_id = selected.get(CONF_BLOWER_REGISTRY_ID)
    if entity_id or registry_id:
        try:
            resolved = async_resolve_blower(hass, entity_id, registry_id)
        except DeviceResolutionError:
            # Preserve explicit identity, including a removed/disabled selection.
            selection = {CONF_BLOWER_ENTITY: entity_id, CONF_BLOWER_REGISTRY_ID: registry_id}
        else:
            selection = resolved.as_config()
    else:
        selection = {CONF_BLOWER_ENTITY: None, CONF_BLOWER_REGISTRY_ID: None}
        if device_id := selected.get(CONF_BLOWER_DEVICE):
            candidates = []
            for entry in _entries_for_device(hass, device_id):
                if entry.domain == Platform.SWITCH and entry.disabled_by is None:
                    candidates.append(entry)
            if len(candidates) == 1:
                selection = async_resolve_blower(hass, candidates[0].entity_id).as_config()

    for container in (data, options):
        for key in reference_keys:
            container.pop(key, None)
    data.update(selection)
    return data, options


def async_resolve_device(hass: HomeAssistant, device_id: str, role: DeviceRole) -> ResolvedDevice:
    """Resolve existing pump telemetry. Blowers require an explicit entity."""
    if role == DeviceRole.BLOWER:
        raise DeviceResolutionError("blower_selection_required", role)
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
    power_sensor = _single(power, "pump_power_missing", "pump_power_ambiguous", role)
    return ResolvedDevice(switches[0] if len(switches) == 1 else None, power_sensor)


def async_resolve_config(hass: HomeAssistant, config: dict) -> dict[str, str]:
    """Resolve the chosen blower output and existing pump telemetry."""
    resolved: dict[str, str] = {}
    blower = async_resolve_blower(
        hass, config.get(CONF_BLOWER_ENTITY), config.get(CONF_BLOWER_REGISTRY_ID),
    )
    resolved[CONF_BLOWER_ENTITY] = blower.switch_entity_id

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
    """Return the owning device id for legacy pump configuration."""
    if not entity_id:
        return None
    entry = er.async_get(hass).async_get(entity_id)
    return entry.device_id if entry else None
