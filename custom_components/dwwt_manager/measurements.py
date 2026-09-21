"""Passive measurement references; registry ownership is not measurement scope."""
from dataclasses import dataclass
from enum import StrEnum


class MeasurementScope(StrEnum):
    DEVICE_TOTAL = "device_total"
    BLOWER_ONLY = "blower_only"
    SHARED_CIRCUIT = "shared_circuit"
    UNKNOWN = "unknown"


class MeasurementQuantity(StrEnum):
    POWER = "power"
    CURRENT = "current"
    VOLTAGE = "voltage"
    ENERGY = "energy"


class ScopeSource(StrEnum):
    INTEGRATION_METADATA = "integration_metadata"
    USER_CONFIRMED = "user_confirmed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class MeasurementBinding:
    """An independent sensor reference; never inferred from a control output.

    sensor_entity_ref is an opaque source reference interpreted by the platform
    adapter (for example an HA sensor entity or a controller measurement channel).
    This contract neither parses HA entity IDs nor accesses a device registry.
    Owner-device context, if needed, is resolved separately by the adapter.
    A shared owner alone must never establish BLOWER_ONLY scope. This contract
    adds no sensor discovery, monitoring, UI or control dependencies.
    """

    sensor_entity_ref: str
    quantity: MeasurementQuantity
    measurement_scope: MeasurementScope = MeasurementScope.UNKNOWN
    scope_source: ScopeSource = ScopeSource.UNKNOWN
