"""Config and options flows for DWWT Manager."""
from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_NAME
from homeassistant.helpers.selector import (
    BooleanSelector, EntitySelector, EntitySelectorConfig, NumberSelector,
    NumberSelectorConfig, NumberSelectorMode, SelectSelector, SelectSelectorConfig,
    SelectSelectorMode, TextSelector,
)

from .const import *  # noqa: F403 - config schemas intentionally mirror constants


def _num(minimum: float = 0, maximum: float = 100000, step: float = 1) -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(min=minimum, max=maximum, step=step, mode=NumberSelectorMode.BOX))


def _entity(domains: list[str]) -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain=domains))


def _suggest(schema: vol.Schema, values: dict[str, Any]) -> vol.Schema:
    result: dict[Any, Any] = {}
    for marker, validator in schema.schema.items():
        key = marker.schema
        default = values.get(key, getattr(marker, "default", vol.UNDEFINED))
        new_marker = vol.Required(key, default=default) if isinstance(marker, vol.Required) else vol.Optional(key, default=default)
        result[new_marker] = validator
    return vol.Schema(result)


GENERAL_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME, default="DWWT"): TextSelector(),
    vol.Optional(CONF_MANUFACTURER, default=""): TextSelector(),
    vol.Optional(CONF_MODEL, default=""): TextSelector(),
    vol.Required(CONF_PLANT_TYPE, default="aerated"): SelectSelector(SelectSelectorConfig(options=["aerated", "other"], mode=SelectSelectorMode.DROPDOWN, translation_key="plant_type")),
    vol.Required(CONF_NOMINAL_EO, default=6): _num(0.1, 100, 0.1),
    vol.Required(CONF_TANK_VOLUME, default=3000): _num(1, 100000, 1),
})
HOUSEHOLD_SCHEMA = vol.Schema({
    vol.Optional(CONF_OCCUPANTS, default=0): _num(0, 100, 1),
    vol.Optional(CONF_ESTIMATED_EO, default=0): _num(0, 100, 0.1),
    vol.Optional(CONF_LOAD_FACTOR, default=1): _num(0, 10, 0.1),
})
BLOWER_SCHEMA = vol.Schema({
    vol.Required(CONF_BLOWER_ENTITY): _entity(["switch", "fan"]),
    vol.Optional(CONF_BLOWER_POWER, default=0): _num(),
    vol.Optional(CONF_BLOWER_AIRFLOW, default=0): _num(),
    vol.Optional(CONF_BLOWER_PRESSURE, default=0): _num(),
})
PUMP_SCHEMA = vol.Schema({
    vol.Optional(CONF_PUMP_ENTITY): _entity(["switch", "binary_sensor"]),
    vol.Optional(CONF_PUMP_POWER_SENSOR): _entity(["sensor"]),
    vol.Required(CONF_PUMP_POWER_THRESHOLD, default=100): _num(0, 100000, 1),
    vol.Required(CONF_VOLUME_PER_CYCLE, default=50): _num(0, 100000, 0.1),
    vol.Optional(CONF_PUMP_MIN_RUNTIME, default=1): _num(0, 3600, 1),
})
OPTIONAL_SCHEMA = vol.Schema({
    vol.Optional(CONF_INLET_ENTITY): _entity(["switch", "binary_sensor"]),
    vol.Optional(CONF_INLET_POWER_SENSOR): _entity(["sensor"]),
    vol.Optional(CONF_ALARM_ENTITY): _entity(["alarm_control_panel"]),
    vol.Required(CONF_AWAY_TIMEOUT, default=72): _num(1, 8760, 1),
})
AUTO_SCHEMA = vol.Schema({
    vol.Required(CONF_USE_ALARM, default=True): BooleanSelector(),
    vol.Required(CONF_USE_PUMP_ACTIVITY, default=True): BooleanSelector(),
    vol.Required(CONF_USE_VOLUME, default=True): BooleanSelector(),
    vol.Required(CONF_HIGH_STARTS_HOUR, default=3): _num(1, 100, 1),
    vol.Required(CONF_MEDIUM_VOLUME_DAY, default=100): _num(0, 100000, 1),
    vol.Required(CONF_HIGH_VOLUME_DAY, default=250): _num(0, 100000, 1),
    vol.Required(CONF_INACTIVITY_TIMEOUT, default=24): _num(1, 8760, 1),
})


def schedule_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    schema: dict[Any, Any] = {}
    for mode in MANUAL_MODES:
        on, off = DEFAULT_SCHEDULES[mode]
        configured = defaults.get(mode.value, {})
        schema[vol.Required(f"{mode.value}_on", default=configured.get("on", on))] = _num(1, 1440, 1)
        schema[vol.Required(f"{mode.value}_off", default=configured.get("off", off))] = _num(1, 1440, 1)
    return vol.Schema(schema)


def pack_schedules(values: dict[str, Any]) -> dict[str, dict[str, int]]:
    return {mode.value: {"on": int(values[f"{mode.value}_on"]), "off": int(values[f"{mode.value}_off"])} for mode in MANUAL_MODES}


class DwwtConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        return await self._step("user", GENERAL_SCHEMA, user_input, "household")

    async def async_step_household(self, user_input=None) -> ConfigFlowResult:
        return await self._step("household", HOUSEHOLD_SCHEMA, user_input, "blower")

    async def async_step_blower(self, user_input=None) -> ConfigFlowResult:
        return await self._step("blower", BLOWER_SCHEMA, user_input, "pump")

    async def async_step_pump(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None and not (user_input.get(CONF_PUMP_ENTITY) or user_input.get(CONF_PUMP_POWER_SENSOR)):
            return self.async_show_form(step_id="pump", data_schema=PUMP_SCHEMA, errors={"base": "pump_source_required"})
        return await self._step("pump", PUMP_SCHEMA, user_input, "optional")

    async def async_step_optional(self, user_input=None) -> ConfigFlowResult:
        return await self._step("optional", OPTIONAL_SCHEMA, user_input, "auto")

    async def async_step_auto(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None and float(user_input[CONF_HIGH_VOLUME_DAY]) < float(user_input[CONF_MEDIUM_VOLUME_DAY]):
            return self.async_show_form(step_id="auto", data_schema=AUTO_SCHEMA, errors={"base": "threshold_order"})
        return await self._step("auto", AUTO_SCHEMA, user_input, "schedules")

    async def async_step_schedules(self, user_input=None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="schedules", data_schema=schedule_schema())
        self._data[CONF_SCHEDULES] = pack_schedules(user_input)
        await self.async_set_unique_id(uuid.uuid4().hex)
        return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

    async def _step(self, step_id, schema, user_input, next_step) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id=step_id, data_schema=schema)
        self._data.update(user_input)
        return await getattr(self, f"async_step_{next_step}")()

    @staticmethod
    def async_get_options_flow(config_entry):
        return DwwtOptionsFlow()


class DwwtOptionsFlow(OptionsFlowWithReload):
    """Edit runtime settings and schedules; setup identity remains entry data."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["settings", "schedules"])

    async def async_step_settings(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, **user_input})
        values = {**DEFAULTS, **self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema({
            vol.Required(CONF_AWAY_TIMEOUT): _num(1, 8760, 1),
            vol.Required(CONF_HIGH_STARTS_HOUR): _num(1, 100, 1),
            vol.Required(CONF_MEDIUM_VOLUME_DAY): _num(),
            vol.Required(CONF_HIGH_VOLUME_DAY): _num(),
            vol.Required(CONF_INACTIVITY_TIMEOUT): _num(1, 8760, 1),
            vol.Required(CONF_VOLUME_PER_CYCLE): _num(0, 100000, 0.1),
            vol.Required(CONF_PUMP_POWER_THRESHOLD): _num(),
            vol.Required(CONF_USE_ALARM): BooleanSelector(),
            vol.Required(CONF_USE_PUMP_ACTIVITY): BooleanSelector(),
            vol.Required(CONF_USE_VOLUME): BooleanSelector(),
        })
        return self.async_show_form(step_id="settings", data_schema=_suggest(schema, values))

    async def async_step_schedules(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, CONF_SCHEDULES: pack_schedules(user_input)})
        values = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="schedules", data_schema=schedule_schema(values.get(CONF_SCHEDULES)))
