"""Tests for pure DWWT domain logic."""
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.dwwt_manager.const import OperatingMode
from custom_components.dwwt_manager.models import (
    PersistentState, PumpCycle, cycle_count, decide_auto_mode, volume_for_period,
    volume_in_window,
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


def test_pump_cycle_runtime_and_storage_roundtrip():
    cycle = PumpCycle(NOW, NOW + timedelta(seconds=30))
    assert cycle.runtime_seconds == 30
    assert PumpCycle.from_storage(cycle.as_storage()) == cycle


def test_persistent_counter_and_restart_state_roundtrip():
    state = PersistentState(pump_starts_total=7, cycles=[PumpCycle(NOW)], away_since=NOW, blower_phase_deadline=NOW + timedelta(minutes=5))
    restored = PersistentState.from_storage(state.as_storage())
    assert restored.pump_starts_total == 7
    assert restored.away_since == NOW
    assert restored.blower_phase_deadline == NOW + timedelta(minutes=5)


def test_rolling_counts_and_volume():
    cycles = [PumpCycle(NOW - timedelta(minutes=20)), PumpCycle(NOW - timedelta(hours=2)), PumpCycle(NOW - timedelta(hours=25))]
    assert cycle_count(cycles, NOW, 1) == 1
    assert cycle_count(cycles, NOW, 6) == 2
    assert volume_in_window(cycles, NOW, 24, 50) == 100


@pytest.mark.parametrize("period", ["day", "week", "month", "year"])
def test_calendar_volume_periods(period):
    assert volume_for_period([PumpCycle(NOW - timedelta(minutes=1))], NOW, period, 50) == 50


def test_alarm_night_and_critical_night_to_disarmed_transition():
    assert decision(alarm_state="armed_night")[0] == OperatingMode.RESIDENCE
    mode, reason = decision(alarm_state="disarmed", previous_alarm_state="armed_night")
    assert mode == OperatingMode.RESIDENCE
    assert "night" in reason


def test_away_before_and_after_timeout_survives_via_timestamp():
    assert decision(alarm_state="armed_away", away_since=NOW - timedelta(hours=71))[0] == OperatingMode.VISIT
    mode, reason = decision(alarm_state="armed_away", away_since=NOW - timedelta(hours=72))
    assert mode == OperatingMode.HOLIDAY
    assert "72.0" in reason


def test_auto_activity_and_volume_thresholds():
    assert decision(starts_hour=3)[0] == OperatingMode.FULLHOUSE
    assert decision(volume_day=150)[0] == OperatingMode.RESIDENCE
    assert decision(volume_day=300)[0] == OperatingMode.FULLHOUSE


def test_auto_inactivity_and_recent_activity():
    assert decision(last_activity=NOW - timedelta(hours=25))[0] == OperatingMode.HOLIDAY
    assert decision(starts_6h=1, last_activity=NOW - timedelta(hours=1))[0] == OperatingMode.RESIDENCE


def test_disabled_optional_signals_are_ignored():
    assert decision(use_alarm=False, use_activity=False, use_volume=False, alarm_state="armed_away", starts_hour=99, volume_day=999)[0] == OperatingMode.VISIT
