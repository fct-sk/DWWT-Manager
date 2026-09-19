"""Constants for DWWT Manager."""
from __future__ import annotations

from enum import StrEnum

DOMAIN = "dwwt_manager"
PLATFORMS = ["binary_sensor", "select", "sensor", "switch"]


class OperatingMode(StrEnum):
    """Stable operating mode identifiers."""

    VISIT = "visit"
    RESIDENCE = "residence"
    FULLHOUSE = "fullhouse"
    HOLIDAY = "holiday"
    AUTO = "auto"


MANUAL_MODES = tuple(mode for mode in OperatingMode if mode != OperatingMode.AUTO)

DEFAULT_SCHEDULES = {
    OperatingMode.VISIT: (80, 400),
    OperatingMode.RESIDENCE: (120, 360),
    OperatingMode.FULLHOUSE: (240, 240),
    OperatingMode.HOLIDAY: (10, 470),
}

CONF_NAME = "name"
CONF_MANUFACTURER = "manufacturer"
CONF_MODEL = "model"
CONF_PLANT_TYPE = "plant_type"
CONF_NOMINAL_EO = "nominal_eo"
CONF_TANK_VOLUME = "tank_volume_l"
CONF_OCCUPANTS = "occupants"
CONF_ESTIMATED_EO = "estimated_eo"
CONF_LOAD_FACTOR = "load_factor"
CONF_BLOWER_DEVICE = "blower_device_id"
CONF_BLOWER_ENTITY = "blower_entity"
CONF_BLOWER_POWER = "blower_power_w"
CONF_BLOWER_AIRFLOW = "blower_airflow_l_min"
CONF_BLOWER_PRESSURE = "blower_pressure_mbar"
CONF_PUMP_DEVICE = "pump_device_id"
CONF_PUMP_ENTITY = "pump_entity"
CONF_PUMP_POWER_SENSOR = "pump_power_sensor"
CONF_PUMP_POWER_THRESHOLD = "pump_power_threshold_w"
CONF_VOLUME_PER_CYCLE = "volume_per_cycle_l"
CONF_PUMP_MIN_RUNTIME = "pump_min_runtime_s"
CONF_INLET_DEVICE = "inlet_device_id"
CONF_INLET_ENTITY = "inlet_entity"
CONF_INLET_POWER_SENSOR = "inlet_power_sensor"
CONF_ALARM_ENTITY = "alarm_entity"
CONF_AWAY_TIMEOUT = "away_timeout_h"
CONF_HIGH_STARTS_HOUR = "high_starts_hour"
CONF_MEDIUM_VOLUME_DAY = "medium_volume_day_l"
CONF_HIGH_VOLUME_DAY = "high_volume_day_l"
CONF_INACTIVITY_TIMEOUT = "inactivity_timeout_h"
CONF_USE_ALARM = "use_alarm"
CONF_USE_PUMP_ACTIVITY = "use_pump_activity"
CONF_USE_VOLUME = "use_volume"
CONF_SCHEDULES = "schedules"

DEFAULTS = {
    CONF_MANUFACTURER: "",
    CONF_MODEL: "",
    CONF_PLANT_TYPE: "aerated",
    CONF_NOMINAL_EO: 6.0,
    CONF_TANK_VOLUME: 3000.0,
    CONF_OCCUPANTS: 0,
    CONF_ESTIMATED_EO: 0.0,
    CONF_LOAD_FACTOR: 1.0,
    CONF_BLOWER_POWER: 0.0,
    CONF_BLOWER_AIRFLOW: 0.0,
    CONF_BLOWER_PRESSURE: 0.0,
    CONF_PUMP_POWER_THRESHOLD: 100.0,
    CONF_VOLUME_PER_CYCLE: 50.0,
    CONF_PUMP_MIN_RUNTIME: 1,
    CONF_AWAY_TIMEOUT: 72.0,
    CONF_HIGH_STARTS_HOUR: 3,
    CONF_MEDIUM_VOLUME_DAY: 100.0,
    CONF_HIGH_VOLUME_DAY: 250.0,
    CONF_INACTIVITY_TIMEOUT: 24.0,
    CONF_USE_ALARM: True,
    CONF_USE_PUMP_ACTIVITY: True,
    CONF_USE_VOLUME: True,
}

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.{{entry_id}}"
SIGNAL_UPDATE = f"{DOMAIN}_update_{{entry_id}}"
