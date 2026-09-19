"""Tests for pure DWWT domain logic."""
from datetime import UTC, datetime, timedelta
import pytest
from custom_components.dwwt_manager.const import ModeSelection, OperatingMode
from custom_components.dwwt_manager.models import (
    AutoModeDecision, PersistentState, PumpCycle, cycle_count, decide_auto_mode,
    stabilize_auto_decision, volume_for_period, volume_in_window,
)
NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)

def decision(**overrides):
    values = dict(
        now=NOW, alarm_state=None, previous_alarm_state=None, away_since=None,
        starts_hour=0, starts_6h=0, volume_day=0, use_alarm=True,
        use_activity=True, use_volume=True, away_timeout_h=72,
        high_starts_hour=3, medium_volume_day=100, high_volume_day=250,
        inactivity_timeout_h=24, last_activity=None,
    )
    values.update(overrides)
    return decide_auto_mode(**values)

def test_exactly_four_fixed_modes():
    assert [mode.value for mode in OperatingMode] == ["normal", "low_load", "heavy_load", "eco"]
    assert [mode.value for mode in ModeSelection] == ["manual", "auto"]

def test_pump_cycle_runtime_and_storage_roundtrip():
    cycle = PumpCycle(NOW, NOW + timedelta(seconds=30))
    assert cycle.runtime_seconds == 30
    assert PumpCycle.from_storage(cycle.as_storage()) == cycle

def test_persistent_state_roundtrip_and_legacy_mapping():
    state = PersistentState(pump_starts_total=7, cycles=[PumpCycle(NOW)], away_since=NOW)
    restored = PersistentState.from_storage(state.as_storage())
    assert restored.pump_starts_total == 7
    assert restored.away_since == NOW
    legacy = PersistentState.from_storage({"requested_mode": "fullhouse", "active_mode": "holiday"})
    assert legacy.mode_selection == ModeSelection.MANUAL
    assert legacy.manual_mode == OperatingMode.HEAVY_LOAD
    assert legacy.active_mode == OperatingMode.ECO

def test_rolling_counts_and_volume():
    cycles = [PumpCycle(NOW - timedelta(minutes=20)), PumpCycle(NOW - timedelta(hours=2)), PumpCycle(NOW - timedelta(hours=25))]
    assert cycle_count(cycles, NOW, 1) == 1
    assert cycle_count(cycles, NOW, 6) == 2
    assert volume_in_window(cycles, NOW, 24, 50) == 100

@pytest.mark.parametrize("period", ["day", "week", "month", "year"])
def test_calendar_volume_periods(period):
    assert volume_for_period([PumpCycle(NOW - timedelta(minutes=1))], NOW, period, 50) == 50

def test_auto_selection_and_eco_guards():
    assert decision(alarm_state="armed_night").mode == OperatingMode.NORMAL
    assert decision(alarm_state="armed_away", away_since=NOW - timedelta(hours=71)).mode == OperatingMode.LOW_LOAD
    assert decision(alarm_state="armed_away", away_since=NOW - timedelta(hours=72)).mode == OperatingMode.ECO
    assert decision(starts_hour=3).mode == OperatingMode.HEAVY_LOAD
    assert decision(volume_day=150).mode == OperatingMode.NORMAL
    assert decision(volume_day=300).mode == OperatingMode.HEAVY_LOAD
    assert decision(last_activity=NOW - timedelta(hours=25)).mode == OperatingMode.ECO
    assert decision(starts_6h=1, last_activity=NOW - timedelta(hours=1)).mode == OperatingMode.NORMAL
    # A short period with no measured flow is low load, never ECO.
    assert decision(last_activity=NOW - timedelta(hours=1)).mode == OperatingMode.LOW_LOAD

def test_hysteresis_requires_stable_candidate():
    high = AutoModeDecision(OperatingMode.HEAVY_LOAD, "high load")
    mode, pending, since, _ = stabilize_auto_decision(
        decision=high, current=OperatingMode.NORMAL, pending_mode=None,
        pending_since=None, now=NOW, delay_minutes=10,
    )
    assert mode == OperatingMode.NORMAL and pending == OperatingMode.HEAVY_LOAD and since == NOW
    mode, pending, _, _ = stabilize_auto_decision(
        decision=high, current=OperatingMode.NORMAL, pending_mode=pending,
        pending_since=since, now=NOW + timedelta(minutes=10), delay_minutes=10,
    )
    assert mode == OperatingMode.HEAVY_LOAD and pending is None

def test_time_qualified_eco_bypasses_extra_debounce():
    eco = AutoModeDecision(OperatingMode.ECO, "long inactivity", immediate=True)
    assert stabilize_auto_decision(
        decision=eco, current=OperatingMode.NORMAL, pending_mode=None,
        pending_since=None, now=NOW, delay_minutes=10,
    )[0] == OperatingMode.ECO
