"""Tests for resolving user-selected smart-plug devices."""
from types import SimpleNamespace

import pytest

from custom_components.dwwt_manager.device_resolver import (
    DeviceResolutionError,
    DeviceRole,
    async_resolve_device,
)


def entry(entity_id: str, device_class: str | None = None):
    """Create the registry fields used by the resolver."""
    return SimpleNamespace(
        entity_id=entity_id,
        domain=entity_id.split(".", 1)[0],
        device_class=device_class,
        original_device_class=None,
    )


@pytest.fixture
def hass():
    return SimpleNamespace(states=SimpleNamespace(get=lambda entity_id: None))


def test_blower_device_resolves_single_switch(monkeypatch, hass):
    monkeypatch.setattr(
        "custom_components.dwwt_manager.device_resolver._entries_for_device",
        lambda hass, device_id: [entry("switch.blower"), entry("sensor.blower_power", "power")],
    )
    resolved = async_resolve_device(hass, "blower-device", DeviceRole.BLOWER)
    assert resolved.switch_entity == "switch.blower"
    assert resolved.power_sensor == "sensor.blower_power"


def test_pump_device_resolves_power_but_never_requires_switch(monkeypatch, hass):
    monkeypatch.setattr(
        "custom_components.dwwt_manager.device_resolver._entries_for_device",
        lambda hass, device_id: [entry("sensor.outlet_power", "power")],
    )
    resolved = async_resolve_device(hass, "pump-device", DeviceRole.PUMP)
    assert resolved.switch_entity is None
    assert resolved.power_sensor == "sensor.outlet_power"


def test_pump_device_requires_power_sensor(monkeypatch, hass):
    monkeypatch.setattr(
        "custom_components.dwwt_manager.device_resolver._entries_for_device",
        lambda hass, device_id: [entry("switch.pump_supply")],
    )
    with pytest.raises(DeviceResolutionError, match="pump_power_missing"):
        async_resolve_device(hass, "pump-device", DeviceRole.PUMP)


def test_multiple_power_sensors_are_rejected(monkeypatch, hass):
    monkeypatch.setattr(
        "custom_components.dwwt_manager.device_resolver._entries_for_device",
        lambda hass, device_id: [entry("sensor.power_a", "power"), entry("sensor.power_b", "power")],
    )
    with pytest.raises(DeviceResolutionError, match="pump_power_ambiguous"):
        async_resolve_device(hass, "pump-device", DeviceRole.PUMP)