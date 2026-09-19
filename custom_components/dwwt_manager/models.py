"""Pure models and AUTO decision logic for DWWT Manager."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any
from .const import (
    AerationConfiguration, LEGACY_MODE_MAP, ModeSelection, OperatingMode,
)

def _mode(value: Any, default: OperatingMode) -> OperatingMode:
    raw = value.value if isinstance(value, OperatingMode) else str(value)
    return LEGACY_MODE_MAP.get(raw, OperatingMode(raw) if raw in OperatingMode._value2member_map_ else default)

@dataclass(slots=True)
class PumpCycle:
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

@dataclass(frozen=True, slots=True)
class AutoModeDecision:
    mode: OperatingMode
    reason: str
    immediate: bool = False

    def __iter__(self):
        yield self.mode
        yield self.reason

@dataclass(slots=True)
class PersistentState:
    pump_starts_total: int = 0
    pump_running: bool = False
    pump_started_at: datetime | None = None
    last_pump_stop: datetime | None = None
    cycles: list[PumpCycle] = field(default_factory=list)
    aeration_configuration: AerationConfiguration = AerationConfiguration.MANUAL
    mode_selection: ModeSelection = ModeSelection.AUTO
    manual_mode: OperatingMode = OperatingMode.NORMAL
    active_mode: OperatingMode = OperatingMode.NORMAL
    auto_reason: str = "Initial safe fallback"
    pending_auto_mode: OperatingMode | None = None
    pending_auto_since: datetime | None = None
    last_mode_change: datetime | None = None
    last_alarm_state: str | None = None
    away_since: datetime | None = None
    blower_phase_on: bool = True
    blower_phase_started: datetime | None = None
    blower_phase_deadline: datetime | None = None
    model_version: int = 2

    def as_storage(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("aeration_configuration", "mode_selection", "manual_mode", "active_mode", "pending_auto_mode"):
            item = getattr(self, key)
            value[key] = item.value if item is not None else None
        for key in ("pump_started_at", "last_pump_stop", "pending_auto_since", "last_mode_change", "away_since", "blower_phase_started", "blower_phase_deadline"):
            item = getattr(self, key)
            value[key] = item.isoformat() if item else None
        value["cycles"] = [cycle.as_storage() for cycle in self.cycles]
        return value

    @classmethod
    def from_storage(cls, value: dict[str, Any] | None) -> "PersistentState":
        if not value:
            return cls(model_version=0)
        old_requested = value.get("requested_mode")
        if old_requested == "auto":
            selection, manual = ModeSelection.AUTO, OperatingMode.NORMAL
        elif old_requested:
            selection, manual = ModeSelection.MANUAL, _mode(old_requested, OperatingMode.NORMAL)
        else:
            selection = ModeSelection(value.get("mode_selection", ModeSelection.AUTO.value))
            manual = _mode(value.get("manual_mode", OperatingMode.NORMAL.value), OperatingMode.NORMAL)
        date_keys = ("pump_started_at", "last_pump_stop", "pending_auto_since", "last_mode_change", "away_since", "blower_phase_started", "blower_phase_deadline")
        dates = {key: datetime.fromisoformat(value[key]) if value.get(key) else None for key in date_keys}
        pending = value.get("pending_auto_mode")
        return cls(
            pump_starts_total=int(value.get("pump_starts_total", 0)),
            pump_running=bool(value.get("pump_running", False)),
            cycles=[PumpCycle.from_storage(item) for item in value.get("cycles", [])],
            aeration_configuration=AerationConfiguration(value.get("aeration_configuration", AerationConfiguration.MANUAL.value)),
            mode_selection=selection,
            manual_mode=manual,
            active_mode=_mode(value.get("active_mode", OperatingMode.NORMAL.value), OperatingMode.NORMAL),
            auto_reason=value.get("auto_reason", "Initial safe fallback"),
            pending_auto_mode=_mode(pending, OperatingMode.NORMAL) if pending else None,
            last_alarm_state=value.get("last_alarm_state"),
            blower_phase_on=bool(value.get("blower_phase_on", True)),
            model_version=int(value.get("model_version", 1)),
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

def decide_auto_mode(*, now: datetime, alarm_state: str | None, previous_alarm_state: str | None, away_since: datetime | None, starts_hour: int, starts_6h: int, volume_day: float, use_alarm: bool, use_activity: bool, use_volume: bool, away_timeout_h: float, high_starts_hour: int, medium_volume_day: float, high_volume_day: float, inactivity_timeout_h: float, last_activity: datetime | None) -> AutoModeDecision:
    """Ordered V1 heuristics. ECO requires prolonged absence or inactivity."""
    if use_alarm and alarm_state == "armed_night":
        return AutoModeDecision(OperatingMode.NORMAL, "Alarm armed night", True)
    if use_alarm and alarm_state == "armed_away":
        elapsed = (now - (away_since or now)).total_seconds() / 3600
        if elapsed >= away_timeout_h:
            return AutoModeDecision(OperatingMode.ECO, f"ECO after {elapsed:.1f} hours away", True)
        return AutoModeDecision(OperatingMode.LOW_LOAD, f"Alarm armed away for {elapsed:.1f} hours", True)
    if use_alarm and alarm_state == "disarmed" and previous_alarm_state == "armed_night":
        return AutoModeDecision(OperatingMode.NORMAL, "Disarmed after armed night", True)
    if use_alarm and alarm_state == "disarmed" and previous_alarm_state == "armed_away":
        return AutoModeDecision(OperatingMode.LOW_LOAD, "Disarmed after armed away", True)
    if use_activity and starts_hour >= high_starts_hour:
        return AutoModeDecision(OperatingMode.HEAVY_LOAD, f"High pump activity: {starts_hour} starts/hour")
    if use_volume and volume_day >= high_volume_day:
        return AutoModeDecision(OperatingMode.HEAVY_LOAD, f"High estimated volume: {volume_day:.0f} L/24 h")
    if use_volume and volume_day >= medium_volume_day:
        return AutoModeDecision(OperatingMode.NORMAL, f"Normal estimated volume: {volume_day:.0f} L/24 h")
    if last_activity and (now - last_activity).total_seconds() / 3600 >= inactivity_timeout_h:
        return AutoModeDecision(OperatingMode.ECO, f"No pump activity for at least {inactivity_timeout_h:g} hours", True)
    if use_activity and starts_6h > 0:
        return AutoModeDecision(OperatingMode.NORMAL, f"Recent pump activity: {starts_6h} starts/6 h")
    return AutoModeDecision(OperatingMode.LOW_LOAD, "Low recent measured activity")

def stabilize_auto_decision(*, decision: AutoModeDecision, current: OperatingMode, pending_mode: OperatingMode | None, pending_since: datetime | None, now: datetime, delay_minutes: float) -> tuple[OperatingMode, OperatingMode | None, datetime | None, str]:
    """Debounce load-driven transitions while allowing explicit/long-window signals."""
    if decision.mode == current:
        return current, None, None, decision.reason
    if decision.immediate or delay_minutes <= 0:
        return decision.mode, None, None, decision.reason
    if pending_mode != decision.mode or pending_since is None:
        return current, decision.mode, now, f"Waiting for stable signal: {decision.reason}"
    elapsed = (now - pending_since).total_seconds() / 60
    if elapsed >= delay_minutes:
        return decision.mode, None, None, decision.reason
    return current, pending_mode, pending_since, f"Waiting {delay_minutes - elapsed:.1f} more minutes: {decision.reason}"
