"""Aeration schedule strategies for DWWT Manager."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Protocol
from .const import DEFAULT_SCHEDULES, OperatingMode

@dataclass(frozen=True, slots=True)
class AerationContext:
    tank_volume_l: float
    blower_airflow_l_min: float
    nominal_eo: float  # Rated plant design capacity, not occupants or current load.

@dataclass(frozen=True, slots=True)
class AerationSchedule:
    on_minutes: int
    off_minutes: int
    source: str
    explanation: str

class AerationStrategy(Protocol):
    def calculate(self, mode: OperatingMode, context: AerationContext) -> AerationSchedule: ...

class ManufacturerConfigurationProvider(Protocol):
    """Extension point for a future manufacturer data source."""
    def schedule_for(self, mode: OperatingMode, context: AerationContext) -> AerationSchedule: ...

class HouseholdAdaptationStrategy(Protocol):
    """Extension point for future household-specific learning."""
    def adapt(self, schedule: AerationSchedule, mode: OperatingMode) -> AerationSchedule: ...

class NoHouseholdAdaptation:
    """V1 deliberately performs no active household adaptation."""
    def adapt(self, schedule: AerationSchedule, mode: OperatingMode) -> AerationSchedule:
        return schedule

class ManualAerationStrategy:
    def __init__(self, schedules: Mapping[str, Mapping[str, int]]) -> None:
        self._schedules = schedules

    def calculate(self, mode: OperatingMode, context: AerationContext) -> AerationSchedule:
        default_on, default_off = DEFAULT_SCHEDULES[mode]
        configured = self._schedules.get(mode.value, {})
        return AerationSchedule(
            int(configured.get("on", default_on)),
            int(configured.get("off", default_off)),
            "manual",
            "User-defined ON/OFF schedule",
        )

class HeuristicAerationStrategyV1:
    """Transparent V1 estimate; this is not treatment-engineering guidance."""
    CYCLE_MINUTES = 480
    REFERENCE_VOLUME_L = 3000.0
    REFERENCE_AIRFLOW_L_MIN = 60.0
    REFERENCE_EO = 6.0
    REFERENCE_ON_MIN = 240.0

    def calculate(self, mode: OperatingMode, context: AerationContext) -> AerationSchedule:
        if mode == OperatingMode.ECO:
            return AerationSchedule(10, 470, "heuristic_v1", "Separate fixed ECO baseline: 10 minutes ON / 470 minutes OFF")
        if context.tank_volume_l <= 0 or context.blower_airflow_l_min <= 0 or context.nominal_eo <= 0:
            raise ValueError("Tank volume, blower airflow and nominal EO must be positive")
        # Mode represents current relative load independently of nominal capacity.
        # V1 heuristic factors: NORMAL=1, LOW_LOAD=1/3, HEAVY_LOAD=1.25.
        mode_factor = {
            OperatingMode.LOW_LOAD: 1 / 3,
            OperatingMode.NORMAL: 1.0,
            OperatingMode.HEAVY_LOAD: 1.25,
        }[mode]
        raw_on = (
            self.REFERENCE_ON_MIN
            * (context.nominal_eo / self.REFERENCE_EO)
            * (context.tank_volume_l / self.REFERENCE_VOLUME_L)
            * (self.REFERENCE_AIRFLOW_L_MIN / context.blower_airflow_l_min)
            * mode_factor
        )
        # Five-minute buckets communicate that V1 is a heuristic, not false precision.
        on_minutes = int(round(raw_on / 5.0) * 5)
        # Technical/heuristic bounds; 420 minutes is not a technologically validated limit.
        on_minutes = min(420, max(10, on_minutes))
        return AerationSchedule(
            on_minutes, self.CYCLE_MINUTES - on_minutes, "heuristic_v1",
            "Estimated from tank volume, blower airflow, nominal plant capacity (EO) and independent operating-mode load factor",
        )

def calculate_final_schedule(
    baseline: AerationStrategy,
    adaptation: HouseholdAdaptationStrategy,
    mode: OperatingMode,
    context: AerationContext,
) -> AerationSchedule:
    """Pipeline: baseline/heuristic -> household adaptation -> final schedule."""
    return adaptation.adapt(baseline.calculate(mode, context), mode)
