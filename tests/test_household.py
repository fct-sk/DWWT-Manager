"""Household configuration must remain independent of treatment control."""
import ast
import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

import pytest

from custom_components.dwwt_manager import async_migrate_entry
from custom_components.dwwt_manager.config_flow import DwwtConfigFlow, DwwtOptionsFlow, household_schema
from custom_components.dwwt_manager.const import DEFAULTS, AerationConfiguration, OperatingMode
from custom_components.dwwt_manager.household import (
    HouseholdLoadProfile,
    HouseholdProfileError,
    OccupancyPattern,
    migrate_household_config,
)
from custom_components.dwwt_manager.manager import DwwtManager
from custom_components.dwwt_manager.models import PersistentState

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "dwwt_manager"


@pytest.mark.parametrize("value", [{}, {"typical_occupants": None}, {"typical_occupants": 0},
                                  {"typical_occupants": 20, "peak_occupants": 20},
                                  {"occupancy_pattern": "seasonal"}, {"peak_occupants": 9}])
def test_valid_partial_unknown_and_zero(value):
    profile = HouseholdLoadProfile.from_config(value)
    assert HouseholdLoadProfile.from_config(profile.as_config()) == profile
    assert profile.typical_occupants == value.get("typical_occupants")


@pytest.mark.parametrize("key", ["typical_occupants", "peak_occupants"])
@pytest.mark.parametrize("value", [-1, 1.2, True, False, "2", float("nan"), float("inf")])
def test_reject_invalid_counts(key, value):
    with pytest.raises(HouseholdProfileError):
        HouseholdLoadProfile.from_config({key: value})


@pytest.mark.parametrize("value", [
    {"typical_occupants": 3, "peak_occupants": 2},
    {"occupancy_pattern": "invalid"}, {"schema_version": 2},
    {"schema_version": True}, {"unexpected": 1}, [],
])
def test_invalid_profile(value):
    with pytest.raises(HouseholdProfileError):
        HouseholdLoadProfile.from_config(value)


def test_complete_not_required_and_no_nominal_capacity_limit():
    assert not HouseholdLoadProfile().is_complete
    assert not HouseholdLoadProfile(typical_occupants=2).is_complete
    assert HouseholdLoadProfile(typical_occupants=0, occupancy_pattern=OccupancyPattern.PERMANENT).is_complete
    assert HouseholdLoadProfile.from_config({"typical_occupants": 1000}).typical_occupants == 1000
    assert HouseholdLoadProfile.from_config({"typical_occupants": 2.0}).typical_occupants == 2


@pytest.mark.parametrize("data,options,expected", [
    ({}, {}, None), ({"occupants": 0}, {}, None),
    ({"occupants": 3}, {}, 3), ({"occupants": 3}, {"occupants": 0}, None),
    ({"occupants": 3}, {"occupants": 4}, 4),
    ({"household_profile": {"typical_occupants": 2}}, {"occupants": 8}, 2),
    ({"occupants": 8}, {"household_profile": {"typical_occupants": 0}}, 0),
    ({"household_profile": {"typical_occupants": 2, "peak_occupants": 7}},
     {"household_profile": {"typical_occupants": 4}}, 4),
])
def test_migration_precedence_and_idempotence(data, options, expected):
    before = copy.deepcopy((data, options))
    migrated = migrate_household_config(data, options)
    effective = {**migrated[0], **migrated[1]}["household_profile"]
    assert effective["typical_occupants"] == expected
    assert effective["occupancy_pattern"] == "unknown"
    assert effective["peak_occupants"] is None
    assert all("occupants" not in x for x in migrated)
    assert migrated == migrate_household_config(*migrated)
    assert (data, options) == before


def existing_entry(version=5):
    return SimpleNamespace(
        entry_id="test", version=version,
        data={"blower_entity": "switch.blower", "blower_entity_registry_id": "stable-uuid",
              "pump_device_id": "pump", "pump_min_runtime_s": 3,
              "nominal_eo": 6, "estimated_eo": 2, "load_factor": 1.5,
              "schedules": {"normal": {"on": 240, "off": 240}}, "occupants": 2},
        options={"estimated_eo": 3, "load_factor": 0.7, "occupants": 4},
    )


async def test_v5_to_v6_preserves_every_unrelated_value():
    entry = existing_entry()
    before = copy.deepcopy((entry.data, entry.options))
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))
    with patch("custom_components.dwwt_manager.async_migrate_blower_config") as blower:
        assert await async_migrate_entry(hass, entry)
        blower.assert_not_called()
    result = hass.config_entries.async_update_entry.call_args.kwargs
    assert result["version"] == 6
    for name, original in zip(("data", "options"), before, strict=True):
        for key, value in original.items():
            if key != "occupants":
                assert result[name][key] == value
    assert result["options"]["household_profile"]["typical_occupants"] == 4
    assert (entry.data, entry.options) == before
    second = SimpleNamespace(entry_id="test", **result)
    assert await async_migrate_entry(hass, second)
    assert hass.config_entries.async_update_entry.call_args.kwargs == result


@pytest.mark.parametrize("container", ["data", "options"])
async def test_invalid_stored_profile_never_partially_saved(container):
    entry = existing_entry()
    getattr(entry, container)["household_profile"] = {"typical_occupants": -2}
    before = copy.deepcopy((entry.data, entry.options))
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))
    assert not await async_migrate_entry(hass, entry)
    hass.config_entries.async_update_entry.assert_not_called()
    assert entry.version == 5
    assert (entry.data, entry.options) == before


async def test_setup_unknown_and_valid_profile():
    flow = DwwtConfigFlow()
    assert flow.VERSION == 6
    result = await flow.async_step_household({"typical_occupants": -1})
    assert result["errors"]["base"] == "household_invalid_count"
    assert flow._data == {}
    assert (await flow.async_step_household({}))["step_id"] == "blower"
    assert flow._data["household_profile"]["typical_occupants"] is None
    await flow.async_step_household({"typical_occupants": 10, "occupancy_pattern": "intermittent"})
    assert flow._data["household_profile"]["peak_occupants"] is None


async def test_options_preserve_other_settings_and_clear_counts():
    entry = existing_entry()
    entry.options["household_profile"] = HouseholdLoadProfile(typical_occupants=4, peak_occupants=8).as_config()
    flow = DwwtOptionsFlow()
    with patch.object(DwwtOptionsFlow, "config_entry", new_callable=PropertyMock, return_value=entry):
        form = await flow.async_step_household()
        assert "peak_occupants" not in form["data_schema"]({})
        invalid = await flow.async_step_household({"typical_occupants": 4, "peak_occupants": 1})
        assert invalid["errors"]["base"] == "household_peak_below_typical"
        result = await flow.async_step_household({"occupancy_pattern": "unknown"})
    assert result["data"] == {**entry.options, "household_profile": HouseholdLoadProfile().as_config()}


async def test_options_invalid_stored_profile_can_be_repaired():
    entry = existing_entry()
    entry.options["household_profile"] = {"schema_version": 999}
    flow = DwwtOptionsFlow()
    with patch.object(DwwtOptionsFlow, "config_entry", new_callable=PropertyMock, return_value=entry):
        assert (await flow.async_step_household())["errors"]["base"] == "household_schema_version"
        result = await flow.async_step_household({"typical_occupants": 0})
    assert result["data"]["household_profile"]["typical_occupants"] == 0


def test_schema_optional_counts_no_hidden_defaults():
    result = household_schema({"typical_occupants": 5, "peak_occupants": 8})({})
    assert result == {"occupancy_pattern": "unknown"}


def test_translations_complete():
    source = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    assert source == json.loads((COMPONENT / "translations/en.json").read_text(encoding="utf-8"))
    error_keys = {"household_invalid_count", "household_invalid_pattern", "household_peak_below_typical",
                  "household_schema_version", "household_invalid_profile"}
    for language in ("en", "sk"):
        text = json.loads((COMPONENT / f"translations/{language}.json").read_text(encoding="utf-8"))
        for section in ("config", "options"):
            step = text[section]["step"]["household"]
            for field in ("typical_occupants", "peak_occupants", "occupancy_pattern"):
                assert step["data"][field] and step["data_description"][field]
            assert error_keys <= text[section]["error"].keys()
        assert text["options"]["step"]["init"]["menu_options"]["household"]
        assert set(text["selector"]["occupancy_pattern"]["options"]) == {x.value for x in OccupancyPattern}


@pytest.mark.parametrize("configuration", [AerationConfiguration.MANUAL, AerationConfiguration.AUTOMATIC])
def test_profile_does_not_change_schedule_or_mode(configuration):
    manager = DwwtManager.__new__(DwwtManager)
    manager.config = dict(DEFAULTS)
    manager.state = PersistentState()
    manager.state.aeration_configuration = configuration
    before = manager.state.as_storage()
    schedules = {mode: manager.schedule(mode) for mode in OperatingMode}
    for count in (0, 2, 6, 20):
        manager.config["household_profile"] = HouseholdLoadProfile(
            typical_occupants=count, occupancy_pattern=OccupancyPattern.INTERMITTENT,
        ).as_config()
        assert {mode: manager.schedule(mode) for mode in OperatingMode} == schedules
        assert manager.state.as_storage() == before


def test_passive_contracts_and_no_mqtt_or_runtime_profile_dependency():
    from custom_components.dwwt_manager.load_contracts import HouseholdObservations, Observation

    observation = Observation(None, datetime.now(UTC), "source", "unknown", "measured")
    assert observation.value is None
    assert HouseholdObservations().current_occupants is None
    for name in ("household.py", "load_contracts.py"):
        tree = ast.parse((COMPONENT / name).read_text(encoding="utf-8"))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert all("homeassistant" not in module and "mqtt" not in module for module in imports)
        if name == "load_contracts.py":
            assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                           for node in ast.walk(tree))
    for name in ("manager.py", "aeration.py", "models.py"):
        tree = ast.parse((COMPONENT / name).read_text(encoding="utf-8"))
        assert not any(isinstance(node, ast.ImportFrom) and node.module in ("household", "load_contracts")
                       for node in ast.walk(tree))
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert "mqtt" not in manifest.get("dependencies", []) + manifest.get("after_dependencies", [])


async def test_profile_does_not_change_auto_decision():
    from unittest.mock import AsyncMock

    now = datetime.now(UTC)
    results = []
    for count in (0, 2, 6, 20):
        manager = DwwtManager.__new__(DwwtManager)
        manager.config = {**DEFAULTS, "household_profile": {"typical_occupants": count}}
        manager.state = PersistentState()
        manager._restart_scheduler = Mock()
        manager._save = AsyncMock()
        await manager.async_recalculate_auto(alarm_state="armed_night", now=now)
        results.append(manager.state.as_storage())
    assert all(value == results[0] for value in results)


@pytest.mark.parametrize("version", [3, 4])
async def test_old_migration_failure_never_saves_partial_blower_migration(version):
    entry = existing_entry(version)
    entry.data["household_profile"] = {"peak_occupants": -1}
    before = copy.deepcopy((entry.data, entry.options))
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=Mock()))
    with patch("custom_components.dwwt_manager.async_migrate_blower_config",
               side_effect=lambda h, d, o: ({**d, "blower_entity": "switch.resolved"}, dict(o))) as blower:
        assert not await async_migrate_entry(hass, entry)
        blower.assert_called_once()
    hass.config_entries.async_update_entry.assert_not_called()
    assert (entry.data, entry.options) == before
    assert entry.version == version
