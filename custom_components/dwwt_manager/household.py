"""Validated household configuration, independent of treatment control."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

CONF_HOUSEHOLD_PROFILE = "household_profile"
PROFILE_SCHEMA_VERSION = 1


class OccupancyPattern(StrEnum):
    """Typical use; implies neither a calendar nor a current operating mode."""

    PERMANENT = "permanent"
    INTERMITTENT = "intermittent"
    SEASONAL = "seasonal"
    UNKNOWN = "unknown"


class HouseholdProfileError(ValueError):
    """Validation error with an HA translation key."""

    def __init__(self, key: str) -> None:
        self.translation_key = key
        super().__init__(key)


def _count(value: Any) -> int | None:
    """Accept integral HA selector numbers; never truncate or accept booleans."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if type(value) is not int or value < 0:
        raise HouseholdProfileError("household_invalid_count")
    return value


@dataclass(frozen=True, slots=True)
class HouseholdLoadProfile:
    """Expected use, not nominal capacity, current occupancy or a load estimate.

    Partial profiles are valid. None means unknown; zero means a known zero.
    Counts describe people while the property is in use, not time averages.
    Peak means the total typical visiting occupancy, not extra guests or a cap.
    """

    schema_version: int = PROFILE_SCHEMA_VERSION
    typical_occupants: int | None = None
    occupancy_pattern: OccupancyPattern = OccupancyPattern.UNKNOWN
    peak_occupants: int | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != PROFILE_SCHEMA_VERSION:
            raise HouseholdProfileError("household_schema_version")
        for key in ("typical_occupants", "peak_occupants"):
            value = getattr(self, key)
            if value is not None and (type(value) is not int or value < 0):
                raise HouseholdProfileError("household_invalid_count")
        if not isinstance(self.occupancy_pattern, OccupancyPattern):
            raise HouseholdProfileError("household_invalid_pattern")
        if (self.typical_occupants is not None and self.peak_occupants is not None
                and self.peak_occupants < self.typical_occupants):
            raise HouseholdProfileError("household_peak_below_typical")

    @property
    def is_complete(self) -> bool:
        """Informational only; completeness never enables automatic control."""
        return self.typical_occupants is not None and self.occupancy_pattern != OccupancyPattern.UNKNOWN

    def as_config(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "typical_occupants": self.typical_occupants,
            "occupancy_pattern": self.occupancy_pattern.value,
            "peak_occupants": self.peak_occupants,
        }

    @classmethod
    def from_config(cls, value: Mapping[str, Any] | None) -> HouseholdLoadProfile:
        """Parse a stored object or form; normalize only integral numbers."""
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise HouseholdProfileError("household_invalid_profile")
        if set(value) - {"schema_version", "typical_occupants", "occupancy_pattern", "peak_occupants"}:
            raise HouseholdProfileError("household_invalid_profile")
        try:
            pattern = OccupancyPattern(value.get("occupancy_pattern", OccupancyPattern.UNKNOWN))
        except (ValueError, TypeError) as err:
            raise HouseholdProfileError("household_invalid_pattern") from err
        return cls(
            schema_version=value.get("schema_version", PROFILE_SCHEMA_VERSION),
            typical_occupants=_count(value.get("typical_occupants")),
            occupancy_pattern=pattern,
            peak_occupants=_count(value.get("peak_occupants")),
        )


def migrate_household_config(
    data: Mapping[str, Any], options: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Replace legacy occupants, preserving options precedence and other fields.

    Legacy zero meant unknown. New profiles retain actual zero. Each stored
    profile is validated as a whole, never merged across configuration layers.
    """
    migrated_data, migrated_options = dict(data), dict(options)
    for container in (migrated_data, migrated_options):
        if CONF_HOUSEHOLD_PROFILE in container:
            profile = HouseholdLoadProfile.from_config(container[CONF_HOUSEHOLD_PROFILE])
            container[CONF_HOUSEHOLD_PROFILE] = profile.as_config()
    if CONF_HOUSEHOLD_PROFILE not in migrated_data and CONF_HOUSEHOLD_PROFILE not in migrated_options:
        target = migrated_options if "occupants" in migrated_options else migrated_data
        occupants = _count(target.get("occupants"))
        target[CONF_HOUSEHOLD_PROFILE] = HouseholdLoadProfile(
            typical_occupants=occupants if occupants else None,
        ).as_config()
    for container in (migrated_data, migrated_options):
        container.pop("occupants", None)
    return migrated_data, migrated_options
