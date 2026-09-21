"""Explicit blower control, migration, identity and independent measurements."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryError

from custom_components.dwwt_manager import async_migrate_entry, async_setup_entry
from custom_components.dwwt_manager.config_flow import (
    BLOWER_SCHEMA,
    DwwtConfigFlow,
    DwwtOptionsFlow,
)
from custom_components.dwwt_manager.const import (
    CONF_BLOWER_DEVICE,
    CONF_BLOWER_ENTITY,
    CONF_BLOWER_REGISTRY_ID,
)
from custom_components.dwwt_manager.device_resolver import (
    DeviceResolutionError,
    DeviceRole,
    async_migrate_blower_config,
    async_resolve_blower,
    async_resolve_config,
    async_resolve_device,
)
from custom_components.dwwt_manager.manager import DwwtManager
from custom_components.dwwt_manager.measurements import (
    MeasurementBinding,
    MeasurementQuantity,
    MeasurementScope,
    ScopeSource,
)
from custom_components.dwwt_manager.models import PersistentState


class Registry:
    """Small registry boundary double, indexed by name and registry identity."""

    def __init__(self):
        self.items = []
        self.entities = self

    def add(self, entity_id, device_id="multi", *, disabled=None, quantity=None, identity=None):
        entry = SimpleNamespace(
            entity_id=entity_id, device_id=device_id, id=identity or f"uuid-{entity_id}",
            domain=entity_id.split(".", 1)[0], disabled_by=disabled,
            device_class=quantity, original_device_class=None,
        )
        self.items.append(entry)
        return entry

    def async_get(self, reference):
        return next((x for x in self.items if reference in (x.entity_id, x.id)), None)

    def get_entries_for_device_id(self, device_id, include_disabled_entities=False):
        return [
            x for x in self.items if x.device_id == device_id
            and (include_disabled_entities or x.disabled_by is None)
        ]


@pytest.fixture
def equipment(monkeypatch):
    registry = Registry()
    hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda entity_id: None),
        config_entries=SimpleNamespace(async_update_entry=Mock(), async_reload=AsyncMock()),
        data={}, services=SimpleNamespace(async_call=AsyncMock()),
    )
    monkeypatch.setattr("custom_components.dwwt_manager.device_resolver.er.async_get", lambda h: registry)
    return hass, registry


@pytest.mark.parametrize("other_switches", [0, 1, 3])
def test_explicit_last_switch_on_single_or_multi_output_device(equipment, other_switches):
    hass, registry = equipment
    for index in range(other_switches):
        registry.add(f"switch.a_{index}")
    selected = registry.add("switch.z_blower")
    registry.add("sensor.total_power", quantity="power")
    result = async_resolve_blower(hass, selected.entity_id)
    assert result.switch_entity_id == "switch.z_blower"
    assert result.owner_device_id == "multi"
    assert result.registry_entry_id == selected.id


def test_device_only_resolver_cannot_choose_blower(equipment):
    hass, registry = equipment
    registry.add("switch.only")
    with pytest.raises(DeviceResolutionError, match="blower_selection_required"):
        async_resolve_device(hass, "multi", DeviceRole.BLOWER)


@pytest.mark.parametrize("entity_id,error", [
    (None, "blower_selection_required"),
    ("switch.missing", "blower_entity_missing"),
    ("sensor.power", "blower_entity_not_switch"),
])
def test_invalid_explicit_selection(equipment, entity_id, error):
    hass, registry = equipment
    registry.add("sensor.power", quantity="power")  # Device with zero switches.
    with pytest.raises(DeviceResolutionError, match=error):
        async_resolve_blower(hass, entity_id)


def test_disabled_switch_is_rejected(equipment):
    hass, registry = equipment
    registry.add("switch.disabled", disabled="user")
    with pytest.raises(DeviceResolutionError, match="blower_entity_disabled"):
        async_resolve_blower(hass, "switch.disabled")


def test_registered_switch_without_owner_or_measurements_is_valid(equipment):
    hass, registry = equipment
    registry.add("switch.standalone", device_id=None)
    selected = async_resolve_blower(hass, "switch.standalone")
    assert selected.owner_device_id is None
    assert selected.switch_entity_id == "switch.standalone"


def test_live_unregistered_switch_has_no_invented_owner_or_identity(equipment):
    hass, _ = equipment
    hass.states.get = lambda entity_id: SimpleNamespace(state="off") if entity_id == "switch.virtual" else None
    result = async_resolve_blower(hass, "switch.virtual")
    assert result.as_config() == {CONF_BLOWER_ENTITY: "switch.virtual", CONF_BLOWER_REGISTRY_ID: None}
    assert result.owner_device_id is None


def test_registry_identity_survives_rename_and_rejects_name_reuse(equipment):
    hass, registry = equipment
    selected = registry.add("switch.original")
    identity = selected.id
    selected.entity_id = "switch.renamed"
    registry.add("switch.original", identity="replacement-uuid")
    assert async_resolve_blower(hass, "switch.original", identity).switch_entity_id == "switch.renamed"
    registry.items.remove(selected)
    with pytest.raises(DeviceResolutionError, match="blower_entity_removed"):
        async_resolve_blower(hass, "switch.original", identity)


@pytest.mark.parametrize("count", [0, 1, 2, 4])
def test_device_migration_requires_unique_valid_switch(equipment, count):
    hass, registry = equipment
    for index in range(count):
        registry.add(f"switch.output_{index}")
    registry.add("switch.disabled", disabled="user")
    original = {
        CONF_BLOWER_DEVICE: "multi", "blower_power_w": 40, "blower_airflow_l_min": 60,
        "blower_pressure_mbar": 150, "estimated_eo": 2, "load_factor": 1.1,
        "household_profile": {"typical_occupants": 2},
    }
    data, options = async_migrate_blower_config(hass, original, {"volume_per_cycle_l": 77})
    assert CONF_BLOWER_DEVICE not in data and CONF_BLOWER_DEVICE not in options
    assert original[CONF_BLOWER_DEVICE] == "multi"  # Input not mutated.
    for key in original.keys() - {CONF_BLOWER_DEVICE}:
        assert data[key] == original[key]
    assert options == {"volume_per_cycle_l": 77}
    if count == 1:
        assert data[CONF_BLOWER_ENTITY] == "switch.output_0"
        assert data[CONF_BLOWER_REGISTRY_ID] == "uuid-switch.output_0"
    else:
        assert data[CONF_BLOWER_ENTITY] is None
        with pytest.raises(DeviceResolutionError, match="blower_selection_required"):
            async_resolve_config(hass, data)


def test_migration_preserves_explicit_historical_selection(equipment):
    hass, registry = equipment
    registry.add("switch.a")
    selected = registry.add("switch.z")
    data, _ = async_migrate_blower_config(
        hass, {CONF_BLOWER_DEVICE: "multi", CONF_BLOWER_ENTITY: "switch.z"}, {},
    )
    assert data[CONF_BLOWER_ENTITY] == selected.entity_id
    assert data[CONF_BLOWER_REGISTRY_ID] == selected.id


def test_options_device_overrides_old_data_entity(equipment):
    hass, registry = equipment
    registry.add("switch.old", device_id="old")
    registry.add("switch.new", device_id="new")
    data, options = async_migrate_blower_config(
        hass, {CONF_BLOWER_ENTITY: "switch.old"}, {CONF_BLOWER_DEVICE: "new"},
    )
    assert data[CONF_BLOWER_ENTITY] == "switch.new"
    assert not options


def test_removed_explicit_selection_never_falls_back_to_device(equipment):
    hass, registry = equipment
    registry.add("switch.other")
    data, _ = async_migrate_blower_config(
        hass, {CONF_BLOWER_DEVICE: "multi", CONF_BLOWER_ENTITY: "switch.removed"}, {},
    )
    assert data[CONF_BLOWER_ENTITY] == "switch.removed"
    with pytest.raises(DeviceResolutionError, match="blower_entity_missing"):
        async_resolve_config(hass, data)


def test_full_resolution_preserves_pump_power_and_ignores_blower_measurements(equipment):
    hass, registry = equipment
    registry.add("switch.a")
    selected = registry.add("switch.z")
    registry.add("sensor.total_power", quantity="power")
    registry.add("sensor.outlet_power", device_id="pump", quantity="power")
    resolved = async_resolve_config(hass, {**selected_config(selected), "pump_device_id": "pump"})
    assert resolved == {"blower_entity": "switch.z", "pump_power_sensor": "sensor.outlet_power"}


def selected_config(entry):
    return {CONF_BLOWER_ENTITY: entry.entity_id, CONF_BLOWER_REGISTRY_ID: entry.id}


@pytest.mark.parametrize("scope", list(MeasurementScope))
def test_measurement_scopes_are_explicit_and_independent(scope):
    binding = MeasurementBinding("sensor.total_power", MeasurementQuantity.POWER, scope, ScopeSource.USER_CONFIRMED)
    assert binding.measurement_scope == scope


def test_device_power_is_not_implicitly_blower_power():
    binding = MeasurementBinding("sensor.total_power", MeasurementQuantity.POWER)
    assert binding.measurement_scope == MeasurementScope.UNKNOWN
    assert binding.scope_source == ScopeSource.UNKNOWN


@pytest.mark.parametrize("phase", [True, False])
async def test_scheduler_targets_exact_selected_output(equipment, phase):
    hass, registry = equipment
    registry.add("switch.a")
    selected = registry.add("switch.z")
    hass.states.get = lambda entity_id: SimpleNamespace(state="off")
    manager = DwwtManager.__new__(DwwtManager)
    manager.hass = hass
    manager.config = selected_config(selected)
    manager.state = PersistentState(
        blower_phase_on=phase, blower_phase_started=datetime.now(UTC),
        blower_phase_deadline=datetime.now(UTC) - timedelta(seconds=1),
    )
    manager.control_enabled = True
    manager.schedule = lambda: (240, 240)
    manager._save = AsyncMock()
    manager._notify = Mock()

    async def call(domain, service, data, **kwargs):
        manager.control_enabled = False

    hass.services.async_call.side_effect = call
    await manager._scheduler()
    hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_on" if phase else "turn_off", {"entity_id": "switch.z"}, blocking=True,
    )


async def test_scheduler_never_controls_replacement_after_registry_removal(equipment):
    hass, registry = equipment
    registry.add("switch.old_name", identity="new-output")
    manager = DwwtManager.__new__(DwwtManager)
    manager.hass = hass
    manager.config = {CONF_BLOWER_ENTITY: "switch.old_name", CONF_BLOWER_REGISTRY_ID: "removed-uuid"}
    manager.state = PersistentState()
    manager.control_enabled = True
    manager.schedule = lambda: (240, 240)
    manager._notify = Mock()
    await manager._scheduler()
    assert not manager.control_enabled
    hass.services.async_call.assert_not_called()


async def test_config_flow_stores_switch_identity_not_device(equipment):
    hass, registry = equipment
    registry.add("switch.a")
    selected = registry.add("switch.z")
    flow = DwwtConfigFlow()
    flow.hass = hass
    result = await flow.async_step_blower(BLOWER_SCHEMA({CONF_BLOWER_ENTITY: "switch.z"}))
    assert result["step_id"] == "method"
    assert flow._data[CONF_BLOWER_ENTITY] == "switch.z"
    assert flow._data[CONF_BLOWER_REGISTRY_ID] == selected.id
    assert CONF_BLOWER_DEVICE not in flow._data


async def test_options_switch_change_replaces_identity(equipment):
    hass, registry = equipment
    registry.add("switch.a")
    selected = registry.add("switch.z")
    registry.add("sensor.pump", device_id="pump", quantity="power")
    entry = SimpleNamespace(
        data={"blower_entity": "switch.a", "pump_device_id": "pump"},
        options={"blower_entity_registry_id": "old", "other_setting": 10},
    )
    flow = DwwtOptionsFlow()
    flow.hass = hass
    with patch.object(DwwtOptionsFlow, "config_entry", new_callable=PropertyMock, return_value=entry):
        result = await flow.async_step_devices({"blower_entity": "switch.z", "pump_device_id": "pump"})
    assert result["data"][CONF_BLOWER_REGISTRY_ID] == selected.id
    assert result["data"][CONF_BLOWER_ENTITY] == "switch.z"
    assert result["data"]["other_setting"] == 10
    assert CONF_BLOWER_DEVICE not in result["data"]


async def test_reconfigure_repairs_unresolved_selection_without_losing_other_data(equipment):
    hass, registry = equipment
    selected = registry.add("switch.z")
    entry = SimpleNamespace(data={"blower_entity": None, "nominal_eo": 6}, options={"load_factor": 1.2})
    flow = DwwtConfigFlow()
    flow.hass = hass
    flow._get_reconfigure_entry = Mock(return_value=entry)
    flow.async_update_reload_and_abort = Mock(return_value={"type": "abort"})
    await flow.async_step_reconfigure({CONF_BLOWER_ENTITY: "switch.z"})
    assert flow.async_update_reload_and_abort.call_args.kwargs == {
        "data": {"nominal_eo": 6, **selected_config(selected)},
        "options": {"load_factor": 1.2},
    }


@pytest.mark.parametrize("count", [0, 1, 2])
@pytest.mark.parametrize("source_version", [3, 4])
async def test_entry_migration_to_v5(equipment, count, source_version):
    hass, registry = equipment
    for i in range(count):
        registry.add(f"switch.output_{i}")
    entry = SimpleNamespace(
        data={"blower_device_id": "multi", "nominal_eo": 6, "occupants": 2, "estimated_eo": 1.5},
        options={"load_factor": 1.2, "occupants": 4}, version=source_version, entry_id="test",
    )
    assert await async_migrate_entry(hass, entry)
    update = hass.config_entries.async_update_entry.call_args.kwargs
    assert update["version"] == 5
    assert update["options"] == entry.options
    assert update["data"]["nominal_eo"] == 6
    assert update["data"]["occupants"] == 2
    assert update["data"]["estimated_eo"] == 1.5
    assert "household_profile" not in update["data"]
    assert update["data"]["blower_entity"] == ("switch.output_0" if count == 1 else None)


async def test_missing_selection_reports_reconfiguration_before_control_starts(equipment):
    hass, _ = equipment
    entry = SimpleNamespace(data={"blower_entity": None}, options={}, entry_id="test")
    with pytest.raises(ConfigEntryError, match="Reconfigure"):
        await async_setup_entry(hass, entry)
    hass.services.async_call.assert_not_called()


async def test_actual_ha_registry_identity_survives_rename(tmp_path):
    """Exercise HA's real UUID lookup, not only the boundary double."""
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    hass = HomeAssistant(str(tmp_path))
    dr.async_setup(hass)
    await dr.async_load(hass)
    await er.async_load(hass)
    registry = er.async_get(hass)
    selected = registry.async_get_or_create(
        "switch", "test", "physical-output", suggested_object_id="original",
    )
    original = selected.entity_id
    registry.async_update_entity(original, new_entity_id="switch.renamed")
    resolved = async_resolve_blower(hass, original, selected.id)
    assert resolved.switch_entity_id == "switch.renamed"
    assert resolved.owner_device_id is None
    registry.async_remove("switch.renamed")
    with pytest.raises(DeviceResolutionError, match="blower_entity_removed"):
        async_resolve_blower(hass, original, selected.id)
    await hass.async_stop(force=True)


@pytest.mark.parametrize("action", ["rename", "remove", "disable"])
async def test_registry_change_stops_control_then_reloads(equipment, monkeypatch, action):
    import asyncio

    hass, registry = equipment
    selected = registry.add("switch.z")
    registry.add("sensor.outlet", device_id="pump", quantity="power")
    entry = SimpleNamespace(
        entry_id="test", data={**selected_config(selected), "pump_device_id": "pump"},
        options={}, async_on_unload=Mock(),
    )
    manager = SimpleNamespace(
        config={}, async_start=AsyncMock(), async_set_control_enabled=AsyncMock(),
    )
    monkeypatch.setattr("custom_components.dwwt_manager.DwwtManager", lambda h, e: manager)
    callbacks = []
    hass.bus = SimpleNamespace(async_listen=lambda name, cb: callbacks.append(cb) or Mock())
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    tasks = []
    hass.async_create_task = lambda coro: tasks.append(asyncio.create_task(coro))
    assert await async_setup_entry(hass, entry)
    event_data = {
        "rename": {"action": "update", "entity_id": "switch.renamed", "old_entity_id": "switch.z", "changes": {}},
        "remove": {"action": "remove", "entity_id": "switch.z"},
        "disable": {"action": "update", "entity_id": "switch.z", "changes": {"disabled_by": None}},
    }[action]
    callbacks[0](SimpleNamespace(data=event_data))
    await asyncio.gather(*tasks)
    manager.async_set_control_enabled.assert_awaited_once_with(False)
    hass.config_entries.async_reload.assert_awaited_once_with("test")


async def test_oldest_migration_retains_explicit_blower(equipment):
    hass, registry = equipment
    registry.add("switch.a")
    registry.add("switch.z")
    registry.add("sensor.pump", device_id="pump", quantity="power")
    entry = SimpleNamespace(
        entry_id="legacy", version=1,
        data={"blower_entity": "switch.z", "pump_power_sensor": "sensor.pump", "estimated_eo": 2},
        options={},
    )
    assert await async_migrate_entry(hass, entry)
    update = hass.config_entries.async_update_entry.call_args.kwargs
    assert update["version"] == 5
    assert update["data"]["blower_entity"] == "switch.z"
    assert update["data"]["pump_device_id"] == "pump"
    assert update["data"]["estimated_eo"] == 2


@pytest.mark.parametrize("selection,expected_error", [
    ("switch.missing", "blower_entity_missing"),
    ("sensor.power", "blower_entity_not_switch"),
])
async def test_config_flow_rejects_invalid_blower(equipment, selection, expected_error):
    hass, _ = equipment
    flow = DwwtConfigFlow()
    flow.hass = hass
    result = await flow.async_step_blower({"blower_entity": selection})
    assert result["step_id"] == "blower"
    assert result["errors"] == {"base": expected_error}
    assert not flow._data
