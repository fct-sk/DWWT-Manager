"""Passive future contracts; no estimator, collection or runtime control.

Fixed DWWT alarm semantics (not user-configurable):
armed_night = occupied, people present, night operation. Predicts expected
evening/night/morning activity (WC, hygiene, showers, dishes), not people count,
wastewater volume or operating mode. Low instantaneous flow does not imply absence.
armed_away = unoccupied/absent. Predicts lower activity, not immediate zero plant
load. Other states alone do not establish occupancy.

Missing data is not zero activity. Unknown state start times remain None;
never infer a start from midnight, last observation or integration startup.
Timestamps are timezone-aware UTC. Coverage is a fraction [0, 1], or None when
unknown. These types are deliberately not imported by the runtime controller.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ObservationAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class Observation[T]:
    value: T | None
    observed_at: datetime
    source_id: str
    availability: ObservationAvailability
    # e.g. measured, pump_cycle_estimate or manually_reported.
    method: str
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class WindowedObservation[T]:
    observation: Observation[T]
    window_start: datetime
    window_end: datetime
    data_coverage: float | None


@dataclass(frozen=True, slots=True)
class AlarmStateInterval:
    alarm_state: str
    started_at: datetime | None
    ended_at: datetime | None
    source_id: str
    data_coverage: float | None


@dataclass(frozen=True, slots=True)
class PumpActivityInterval:
    pump_role: str
    started_at: datetime | None
    ended_at: datetime | None


@dataclass(frozen=True, slots=True)
class HouseholdObservations:
    current_occupants: Observation[int] | None = None
    alarm_state: Observation[str] | None = None
    state_since: datetime | None = None
    inlet: tuple[WindowedObservation[float], ...] = ()
    outlet: tuple[WindowedObservation[float], ...] = ()
    pump_activity: tuple[Observation[PumpActivityInterval], ...] = ()


class ActualLoadStatus(StrEnum):
    UNAVAILABLE = "unavailable"
    INSUFFICIENT_DATA = "insufficient_data"
    AVAILABLE = "available"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class ActualLoadEstimate:
    """Reserved output shape only; no values are generated in Beta7 phase one.

    A future algorithm must define the index/reference scale explicitly.
    This is not nominal EO, current occupants or the aeration mode factor.
    """

    status: ActualLoadStatus
    estimated_load_index: float | None
    reference_id: str | None
    window_start: datetime | None
    window_end: datetime | None
    calculated_at: datetime | None
    valid_until: datetime | None
    source_ids: tuple[str, ...]
    data_coverage: float | None
    reason_codes: tuple[str, ...]
    estimator_version: str | None
    profile_revision: str | None
