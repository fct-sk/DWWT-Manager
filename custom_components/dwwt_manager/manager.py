"""Runtime control engine for DWWT Manager."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ALARM_ENTITY, CONF_AWAY_TIMEOUT, CONF_BLOWER_ENTITY, CONF_HIGH_STARTS_HOUR,
    CONF_HIGH_VOLUME_DAY, CONF_INACTIVITY_TIMEOUT, CONF_INLET_ENTITY, CONF_INLET_POWER_SENSOR, CONF_MEDIUM_VOLUME_DAY,
    CONF_PUMP_ENTITY, CONF_PUMP_MIN_RUNTIME, CONF_PUMP_POWER_SENSOR,
    CONF_PUMP_POWER_THRESHOLD, CONF_SCHEDULES, CONF_USE_ALARM, CONF_USE_PUMP_ACTIVITY,
    CONF_USE_VOLUME, CONF_VOLUME_PER_CYCLE, DEFAULTS, DEFAULT_SCHEDULES, MANUAL_MODES,
    OperatingMode, SIGNAL_UPDATE,
)
from .models import PersistentState, PumpCycle, cycle_count, decide_auto_mode, volume_for_period, volume_in_window
from .store import DwwtStore

_LOGGER = logging.getLogger(__name__)


class DwwtManager:
    """Own all runtime state and one blower control task for a config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.config: dict[str, Any] = {**DEFAULTS, **entry.data, **entry.options}
        self.store = DwwtStore(hass, entry.entry_id)
        self.state = PersistentState()
        self.control_enabled = True
        self.inlet_running = False
        self._scheduler_task: asyncio.Task | None = None
        self._pump_validation_task: asyncio.Task | None = None
        self._unsub: list[Any] = []
        self._save_lock = asyncio.Lock()

    async def async_start(self) -> None:
        self.state = await self.store.load()
        monitored = [x for x in (
            self.config.get(CONF_PUMP_POWER_SENSOR), self.config.get(CONF_PUMP_ENTITY),
            self.config.get(CONF_INLET_POWER_SENSOR), self.config.get(CONF_INLET_ENTITY),
            self.config.get(CONF_ALARM_ENTITY),
        ) if x]
        if monitored:
            self._unsub.append(async_track_state_change_event(self.hass, monitored, self._state_changed))
        self._unsub.append(async_track_time_interval(self.hass, self._periodic_update, timedelta(minutes=1)))
        await self._evaluate_current_inputs()
        if self.state.pump_running and self.state.pump_started_at and not self._has_cycle(self.state.pump_started_at):
            elapsed = (dt_util.utcnow() - self.state.pump_started_at).total_seconds()
            delay = max(0.0, float(self.config[CONF_PUMP_MIN_RUNTIME]) - elapsed)
            self._pump_validation_task = self.hass.async_create_task(
                self._validate_pump_start(self.state.pump_started_at, delay),
                f"{self.entry.entry_id}_pump_debounce",
            )
        self._restart_scheduler()

    async def async_stop(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        await self._cancel_scheduler()
        if self._pump_validation_task:
            self._pump_validation_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._pump_validation_task
            self._pump_validation_task = None
        await self._save()

    @callback
    def _state_changed(self, event: Event[EventStateChangedData]) -> None:
        self.hass.async_create_task(self._async_handle_state(event.data["entity_id"], event.data.get("old_state"), event.data.get("new_state")))

    async def _async_handle_state(self, entity_id: str, old: State | None, new: State | None) -> None:
        if entity_id == self.config.get(CONF_ALARM_ENTITY):
            await self._handle_alarm(old.state if old else None, new.state if new else None)
        if entity_id in (self.config.get(CONF_PUMP_POWER_SENSOR), self.config.get(CONF_PUMP_ENTITY)):
            running = self._pump_running_from_state(new)
            if running is not None:
                await self.async_set_pump_running(running)
        if entity_id in (self.config.get(CONF_INLET_POWER_SENSOR), self.config.get(CONF_INLET_ENTITY)):
            running = self._inlet_running_from_state(new)
            if running is not None:
                self.inlet_running = running
        await self.async_recalculate_auto()
        self._notify()

    def _pump_running_from_state(self, state: State | None) -> bool | None:
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        if state.entity_id == self.config.get(CONF_PUMP_POWER_SENSOR):
            try:
                return float(state.state) >= float(self.config[CONF_PUMP_POWER_THRESHOLD])
            except (TypeError, ValueError):
                return None
        return state.state == STATE_ON

    def _inlet_running_from_state(self, state: State | None) -> bool | None:
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        if state.entity_id == self.config.get(CONF_INLET_POWER_SENSOR):
            try:
                return float(state.state) >= float(self.config[CONF_PUMP_POWER_THRESHOLD])
            except (TypeError, ValueError):
                return None
        return state.state == STATE_ON

    async def async_set_pump_running(self, running: bool, now: datetime | None = None) -> None:
        now = now or dt_util.utcnow()
        if running == self.state.pump_running:
            return
        self.state.pump_running = running
        if running:
            self.state.pump_started_at = now
            minimum = float(self.config[CONF_PUMP_MIN_RUNTIME])
            if minimum <= 0:
                await self._confirm_pump_start(now)
            else:
                self._pump_validation_task = self.hass.async_create_task(
                    self._validate_pump_start(now, minimum),
                    f"{self.entry.entry_id}_pump_debounce",
                )
        else:
            self.state.last_pump_stop = now
            if self._pump_validation_task:
                self._pump_validation_task.cancel()
                self._pump_validation_task = None
            # A delayed event loop must not lose a genuinely long cycle.
            if self.state.pump_started_at and not self._has_cycle(self.state.pump_started_at):
                if (now - self.state.pump_started_at).total_seconds() >= float(self.config[CONF_PUMP_MIN_RUNTIME]):
                    await self._confirm_pump_start(self.state.pump_started_at)
            if self.state.cycles and self.state.cycles[-1].stopped_at is None:
                self.state.cycles[-1].stopped_at = now
            self.state.pump_started_at = None
        self._prune_history(now)
        await self._save()

    async def _validate_pump_start(self, started_at: datetime, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            if self.state.pump_running and self.state.pump_started_at == started_at:
                await self._confirm_pump_start(started_at)
                await self._save()
                self._notify()
        finally:
            self._pump_validation_task = None

    def _has_cycle(self, started_at: datetime) -> bool:
        return bool(self.state.cycles and self.state.cycles[-1].started_at == started_at)

    async def _confirm_pump_start(self, started_at: datetime) -> None:
        if self._has_cycle(started_at):
            return
        self.state.pump_starts_total += 1
        self.state.cycles.append(PumpCycle(started_at=started_at))

    async def _handle_alarm(self, old: str | None, new: str | None) -> None:
        now = dt_util.utcnow()
        previous = self.state.last_alarm_state or old
        if new == "armed_away" and previous != "armed_away":
            self.state.away_since = now
        elif new != "armed_away":
            # Keep previous state through the decision so night->disarmed is distinguishable.
            pass
        self.state.last_alarm_state = previous
        await self.async_recalculate_auto(alarm_state=new)
        self.state.last_alarm_state = new
        if new != "armed_away":
            self.state.away_since = None
        await self._save()

    async def _evaluate_current_inputs(self) -> None:
        pump_id = self.config.get(CONF_PUMP_POWER_SENSOR) or self.config.get(CONF_PUMP_ENTITY)
        if pump_id and (running := self._pump_running_from_state(self.hass.states.get(pump_id))) is not None:
            # Startup observation must not invent a pump start; an already-running cycle is restored.
            if not running:
                self.state.pump_running = False
        inlet_id = self.config.get(CONF_INLET_POWER_SENSOR) or self.config.get(CONF_INLET_ENTITY)
        if inlet_id and (running := self._inlet_running_from_state(self.hass.states.get(inlet_id))) is not None:
            self.inlet_running = running
        await self.async_recalculate_auto()

    async def async_recalculate_auto(self, alarm_state: str | None = None, now: datetime | None = None) -> None:
        if self.state.requested_mode != OperatingMode.AUTO:
            return
        now = now or dt_util.utcnow()
        if alarm_state is None and self.config.get(CONF_ALARM_ENTITY):
            alarm = self.hass.states.get(self.config[CONF_ALARM_ENTITY])
            alarm_state = alarm.state if alarm else None
        mode, reason = decide_auto_mode(
            now=now, alarm_state=alarm_state, previous_alarm_state=self.state.last_alarm_state,
            away_since=self.state.away_since, starts_hour=self.starts(1, now), starts_6h=self.starts(6, now),
            volume_day=self.volume_window(24, now), use_alarm=bool(self.config[CONF_USE_ALARM]),
            use_activity=bool(self.config[CONF_USE_PUMP_ACTIVITY]), use_volume=bool(self.config[CONF_USE_VOLUME]),
            away_timeout_h=float(self.config[CONF_AWAY_TIMEOUT]), high_starts_hour=int(self.config[CONF_HIGH_STARTS_HOUR]),
            medium_volume_day=float(self.config[CONF_MEDIUM_VOLUME_DAY]), high_volume_day=float(self.config[CONF_HIGH_VOLUME_DAY]),
            inactivity_timeout_h=float(self.config[CONF_INACTIVITY_TIMEOUT]), last_activity=self.last_activity,
        )
        self._set_active_mode(mode, reason, now)

    async def async_select_mode(self, mode: OperatingMode) -> None:
        self.state.requested_mode = mode
        if mode == OperatingMode.AUTO:
            await self.async_recalculate_auto()
        else:
            self._set_active_mode(mode, f"Manual mode: {mode.value}", dt_util.utcnow())
        await self._save()
        self._notify()

    def _set_active_mode(self, mode: OperatingMode, reason: str, now: datetime) -> None:
        changed = mode != self.state.active_mode
        self.state.auto_reason = reason
        if changed:
            self.state.active_mode = mode
            self.state.last_mode_change = now
            self.state.blower_phase_started = now
            self.state.blower_phase_deadline = None
            self._restart_scheduler()

    def schedule(self, mode: OperatingMode | None = None) -> tuple[int, int]:
        mode = mode or self.state.active_mode
        custom = self.config.get(CONF_SCHEDULES, {}).get(mode.value, {})
        default_on, default_off = DEFAULT_SCHEDULES[mode]
        return int(custom.get("on", default_on)), int(custom.get("off", default_off))

    def _restart_scheduler(self) -> None:
        if self._scheduler_task:
            self._scheduler_task.cancel()
        if self.control_enabled:
            self._scheduler_task = self.hass.async_create_task(self._scheduler(), f"{self.entry.entry_id}_blower_scheduler")

    async def _cancel_scheduler(self) -> None:
        if not self._scheduler_task:
            return
        self._scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._scheduler_task
        self._scheduler_task = None

    async def _scheduler(self) -> None:
        """Run one restart-safe phase loop. Unavailable blower never advances the phase."""
        while self.control_enabled:
            now = dt_util.utcnow()
            on_minutes, off_minutes = self.schedule()
            duration = timedelta(minutes=on_minutes if self.state.blower_phase_on else off_minutes)
            if self.state.blower_phase_started is None:
                self.state.blower_phase_started = now
            deadline = self.state.blower_phase_deadline or (self.state.blower_phase_started + duration)
            self.state.blower_phase_deadline = deadline
            blower_id = self.config[CONF_BLOWER_ENTITY]
            blower = self.hass.states.get(blower_id)
            if blower is None or blower.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                _LOGGER.warning("Blower %s unavailable; retaining phase and retrying", blower_id)
                await asyncio.sleep(60)
                continue
            domain = blower_id.split(".", 1)[0]
            service = "turn_on" if self.state.blower_phase_on else "turn_off"
            await self.hass.services.async_call(domain, service, {"entity_id": blower_id}, blocking=True)
            await self._save()
            self._notify()
            delay = max(0.0, (deadline - dt_util.utcnow()).total_seconds())
            if delay:
                await asyncio.sleep(delay)
            now = dt_util.utcnow()
            self.state.blower_phase_on = not self.state.blower_phase_on
            self.state.blower_phase_started = now
            self.state.blower_phase_deadline = None

    async def async_set_control_enabled(self, enabled: bool) -> None:
        self.control_enabled = enabled
        if enabled:
            self._restart_scheduler()
        else:
            await self._cancel_scheduler()
        self._notify()

    @callback
    def _periodic_update(self, now: datetime) -> None:
        self._prune_history(now)
        self.hass.async_create_task(self.async_recalculate_auto(now=now))
        self._notify()

    def _prune_history(self, now: datetime) -> None:
        # Calendar sensors need the current year; keep one extra year for timezone changes.
        cutoff = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=366)
        self.state.cycles[:] = [cycle for cycle in self.state.cycles if cycle.started_at >= cutoff]

    @property
    def last_activity(self) -> datetime | None:
        return self.state.cycles[-1].started_at if self.state.cycles else None

    def starts(self, hours: float, now: datetime | None = None) -> int:
        return cycle_count(self.state.cycles, now or dt_util.utcnow(), hours)

    def volume_window(self, hours: float, now: datetime | None = None) -> float:
        return volume_in_window(self.state.cycles, now or dt_util.utcnow(), hours, float(self.config[CONF_VOLUME_PER_CYCLE]))

    def volume_period(self, period: str, now: datetime | None = None) -> float:
        return volume_for_period(self.state.cycles, now or dt_util.utcnow(), period, float(self.config[CONF_VOLUME_PER_CYCLE]))

    @property
    def lifetime_volume(self) -> float:
        return self.state.pump_starts_total * float(self.config[CONF_VOLUME_PER_CYCLE])

    @property
    def phase_remaining_seconds(self) -> int:
        if not self.state.blower_phase_deadline:
            return 0
        return max(0, int((self.state.blower_phase_deadline - dt_util.utcnow()).total_seconds()))

    async def _save(self) -> None:
        async with self._save_lock:
            await self.store.save(self.state)

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(entry_id=self.entry.entry_id))
