"""Pure models and decision logic for DWWT Manager."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .const import OperatingMode


@dataclass(slots=True)
class PumpCycle:
    """A detected pump cycle."""

    started_at: datetime
    stopped_at: datetime | None = None

    @property
    def runtime_seconds(self) -> float | None:
        return None if self.stopped_at is None else max(0, (self.stopped_at - self.started_at).total_seconds())

    def as_storage(self) -> dict[str, str | None]:
        return {"started_at": self.started_at.isoformat(), "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None}

    @classmethod
    def from_storage(cls, value: dict[str, Any]) -> "PumpCycle":
        return cls(datetime.fromisoformat(value["started_at"]), datetime.fromisoformat(value["stopped_at"]) if value.get("stopped_at") else None)


@dataclass(slots=True)
class PersistentState:
    """State which must survive a Home Assistant restart."""

    pump_starts_total: int = 0
    pump_running: bool = False
    pump_started_at: datetime | None = None
    last_pump_stop: datetime | None = None
    cycles: list[PumpCycle] = field(default_factory=list)
    requested_mode: OperatingMode = OperatingMode.AUTO
    active_mode: OperatingMode = OperatingMode.RESIDENCE
    auto_reason: str = "Initial safe fallback"
    last_mode_change: datetime | None = None
    last_alarm_state: str | None = None
    away_since: datetime | None = None
    blower_phase_on: bool = True
    blower_phase_started: datetime | None = None
    blower_phase_deadline: datetime | None = None

    def as_storage(self) -> dict[str, Any]:
        value = asdict(self)
        value["requested_mode"] = self.requested_mode.value
        value["active_mode"] = self.active_mode.value
        for key in ("pump_started_at", "last_pump_stop", "last_mode_change", "away_since", "blower_phase_started", "blower_phase_deadline"):
            value[key] = getattr(self, key).isoformat() if getattr(self, key) else None
        value["cycles"] = [cycle.as_storage() for cycle in self.cycles]
        return value

    @classmethod
    def from_storage(cls, value: dict[str, Any] | None) -> "PersistentState":
        if not value:
            return cls()
        dates = {key: datetime.fromisoformat(value[key]) if value.get(key) else None for key in ("pump_started_at", "last_pump_stop", "last_mode_change", "away_since", "blower_phase_started", "blower_phase_deadline")}
        return cls(
            pump_starts_total=int(value.get("pump_starts_total", 0)),
            pump_running=bool(value.get("pump_running", False)),
            cycles=[PumpCycle.from_storage(item) for item in value.get("cycles", [])],
            requested_mode=OperatingMode(value.get("requested_mode", OperatingMode.AUTO)),
            active_mode=OperatingMode(value.get("active_mode", OperatingMode.RESIDENCE)),
            auto_reason=value.get("auto_reason", "Initial safe fallback"),
            last_alarm_state=value.get("last_alarm_state"),
            blower_phase_on=bool(value.get("blower_phase_on", True)),
            **dates,
        )


def cycle_count(cycles: list[PumpCycle], now: datetime, hours: float) -> int:
    cutoff = now - timedelta(hours=hours)
    return sum(cycle.started_at >= cutoff for cycle in cycles)


def volume_in_window(cycles: list[PumpCycle], now: datetime, hours: float, liters_per_cycle: float) -> float:
    return cycle_count(cycles, now, hours) * liters_per_cycle


def volume_for_period(cycles: list[PumpCycle], now: datetime, period: str, liters_per_cycle: float) -> float:
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"Unsupported period: {period}")
    return sum(cycle.started_at >= start for cycle in cycles) * liters_per_cycle


def decide_auto_mode(*, now: datetime, alarm_state: str | None, previous_alarm_state: str | None, away_since: datetime | None, starts_hour: int, starts_6h: int, volume_day: float, use_alarm: bool, use_activity: bool, use_volume: bool, away_timeout_h: float, high_starts_hour: int, medium_volume_day: float, high_volume_day: float, inactivity_timeout_h: float, last_activity: datetime | None) -> tuple[OperatingMode, str]:
    """Apply transparent, ordered heuristics. Thresholds are configuration, not engineering claims."""
    if use_alarm and alarm_state == "armed_night":
        return OperatingMode.RESIDENCE, "Alarm armed night"
    if use_alarm and alarm_state == "armed_away":
        elapsed = (now - (away_since or now)).total_seconds() / 3600
        if elapsed >= away_timeout_h:
            return OperatingMode.HOLIDAY, f"Holiday after {elapsed:.1f} hours away"
        return OperatingMode.VISIT, f"Alarm armed away for {elapsed:.1f} hours"
    if use_alarm and alarm_state == "disarmed" and previous_alarm_state == "armed_night":
        return OperatingMode.RESIDENCE, "Disarmed after armed night"
    if use_alarm and alarm_state == "disarmed" and previous_alarm_state == "armed_away":
        return OperatingMode.VISIT, "Disarmed after armed away"
    if use_activity and starts_hour >= high_starts_hour:
        return OperatingMode.FULLHOUSE, f"High pump activity: {starts_hour} starts/hour"
    if use_volume and volume_day >= high_volume_day:
        return OperatingMode.FULLHOUSE, f"High estimated volume: {volume_day:.0f} L/24 h"
    if use_volume and volume_day >= medium_volume_day:
        return OperatingMode.RESIDENCE, f"Normal estimated volume: {volume_day:.0f} L/24 h"
    if last_activity and (now - last_activity).total_seconds() / 3600 >= inactivity_timeout_h:
        return OperatingMode.HOLIDAY, f"No pump activity for at least {inactivity_timeout_h:g} hours"
    if use_activity and starts_6h > 0:
        return OperatingMode.RESIDENCE, f"Recent pump activity: {starts_6h} starts/6 h"
    return OperatingMode.VISIT, "Low recent measured activity"
