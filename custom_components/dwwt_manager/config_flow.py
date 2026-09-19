"""Config and options flows for DWWT Manager."""
from __future__ import annotations

from typing import Any
import uuid

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_NAME
from homeassistant.helpers.selector import (
    BooleanSelector, DeviceSelector, DeviceSelectorConfig, EntitySelector, EntitySelectorConfig, NumberSelector,
    NumberSelectorConfig, NumberSelectorMode, SelectSelector, SelectSelectorConfig,
    SelectSelectorMode, TextSelector,
)

from .const import *  # noqa: F403 - config schemas intentionally mirror constants
from .device_resolver import DeviceResolutionError, DeviceRole, async_resolve_device


def _num(minimum: float = 0, maximum: float = 100000, step: float = 1) -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(min=minimum, max=maximum, step=step, mode=NumberSelectorMode.BOX))


def _entity(domains: list[str]) -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain=domains))


def _device() -> DeviceSelector:
    return DeviceSelector(DeviceSelectorConfig())


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
    vol.Required(CONF_BLOWER_DEVICE): _device(),
    vol.Optional(CONF_BLOWER_POWER, default=0): _num(),
    vol.Optional(CONF_BLOWER_AIRFLOW, default=60): _num(),
    vol.Optional(CONF_BLOWER_PRESSURE, default=0): _num(),
})
PUMP_SCHEMA = vol.Schema({
    vol.Required(CONF_PUMP_DEVICE): _device(),
    vol.Required(CONF_PUMP_POWER_THRESHOLD, default=100): _num(0, 100000, 1),
    vol.Required(CONF_VOLUME_PER_CYCLE, default=50): _num(0, 100000, 0.1),
    vol.Optional(CONF_PUMP_MIN_RUNTIME, default=1): _num(0, 3600, 1),
})
OPTIONAL_SCHEMA = vol.Schema({
    vol.Optional(CONF_INLET_DEVICE): _device(),
    vol.Optional(CONF_ALARM_ENTITY): _entity(["alarm_control_panel"]),
    vol.Required(CONF_AWAY_TIMEOUT, default=72): _num(1, 8760, 1),
})
METHOD_SCHEMA = vol.Schema({
    vol.Required(CONF_AERATION_CONFIGURATION, default=AerationConfiguration.MANUAL.value): SelectSelector(SelectSelectorConfig(options=[AerationConfiguration.MANUAL.value, AerationConfiguration.AUTOMATIC.value], mode=SelectSelectorMode.DROPDOWN, translation_key="aeration_configuration")),
})
MODE_SCHEMA = vol.Schema({
    vol.Required(CONF_MODE_SELECTION, default=ModeSelection.AUTO.value): SelectSelector(SelectSelectorConfig(options=[mode.value for mode in ModeSelection], mode=SelectSelectorMode.DROPDOWN, translation_key="mode_selection")),
    vol.Required(CONF_MANUAL_MODE, default=OperatingMode.NORMAL.value): SelectSelector(SelectSelectorConfig(options=[mode.value for mode in OperatingMode], mode=SelectSelectorMode.DROPDOWN, translation_key="operating_mode")),
})
AUTO_SCHEMA = vol.Schema({
    vol.Required(CONF_USE_ALARM, default=True): BooleanSelector(),
    vol.Required(CONF_USE_PUMP_ACTIVITY, default=True): BooleanSelector(),
    vol.Required(CONF_USE_VOLUME, default=True): BooleanSelector(),
    vol.Required(CONF_HIGH_STARTS_HOUR, default=3): _num(1, 100, 1),
    vol.Required(CONF_MEDIUM_VOLUME_DAY, default=100): _num(0, 100000, 1),
    vol.Required(CONF_HIGH_VOLUME_DAY, default=250): _num(0, 100000, 1),
    vol.Required(CONF_INACTIVITY_TIMEOUT, default=24): _num(1, 8760, 1),
    vol.Required(CONF_AUTO_STABILIZATION, default=10): _num(0, 180, 1),
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
    VERSION = 3

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        return await self._step("user", GENERAL_SCHEMA, user_input, "household")

    async def async_step_household(self, user_input=None) -> ConfigFlowResult:
        return await self._step("household", HOUSEHOLD_SCHEMA, user_input, "blower")

    async def async_step_blower(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            try:
                async_resolve_device(self.hass, user_input[CONF_BLOWER_DEVICE], DeviceRole.BLOWER)
            except DeviceResolutionError as err:
                return self.async_show_form(step_id="blower", data_schema=BLOWER_SCHEMA, errors={"base": err.translation_key})
        return await self._step("blower", BLOWER_SCHEMA, user_input, "method")

    async def async_step_method(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None and user_input[CONF_AERATION_CONFIGURATION] == AerationConfiguration.AUTOMATIC.value:
            if float(self._data.get(CONF_BLOWER_AIRFLOW, 0)) <= 0:
                return self.async_show_form(step_id="method", data_schema=METHOD_SCHEMA, errors={"base": "airflow_required"})
        return await self._step("method", METHOD_SCHEMA, user_input, "mode_selection")

    async def async_step_mode_selection(self, user_input=None) -> ConfigFlowResult:
        return await self._step("mode_selection", MODE_SCHEMA, user_input, "pump")

    async def async_step_pump(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            try:
                async_resolve_device(self.hass, user_input[CONF_PUMP_DEVICE], DeviceRole.PUMP)
            except DeviceResolutionError as err:
                return self.async_show_form(step_id="pump", data_schema=PUMP_SCHEMA, errors={"base": err.translation_key})
        return await self._step("pump", PUMP_SCHEMA, user_input, "optional")

    async def async_step_optional(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None and user_input.get(CONF_INLET_DEVICE):
            try:
                async_resolve_device(self.hass, user_input[CONF_INLET_DEVICE], DeviceRole.INLET)
            except DeviceResolutionError as err:
                return self.async_show_form(step_id="optional", data_schema=OPTIONAL_SCHEMA, errors={"base": err.translation_key})
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
        return self.async_show_menu(step_id="init", menu_options=["devices", "settings", "schedules"])

    async def async_step_devices(self, user_input=None) -> ConfigFlowResult:
        values = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema({
            vol.Required(CONF_BLOWER_DEVICE): _device(),
            vol.Required(CONF_PUMP_DEVICE): _device(),
            vol.Optional(CONF_INLET_DEVICE): _device(),
        })
        if user_input is not None:
            for key, role in (
                (CONF_BLOWER_DEVICE, DeviceRole.BLOWER),
                (CONF_PUMP_DEVICE, DeviceRole.PUMP),
                (CONF_INLET_DEVICE, DeviceRole.INLET),
            ):
                if device_id := user_input.get(key):
                    try:
                        async_resolve_device(self.hass, device_id, role)
                    except DeviceResolutionError as err:
                        return self.async_show_form(
                            step_id="devices",
                            data_schema=_suggest(schema, {**values, **user_input}),
                            errors={"base": err.translation_key},
                        )
            updated = {**self.config_entry.options, **user_input}
            if not user_input.get(CONF_INLET_DEVICE):
                updated.pop(CONF_INLET_DEVICE, None)
            return self.async_create_entry(data=updated)
        return self.async_show_form(step_id="devices", data_schema=_suggest(schema, values))

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
            vol.Required(CONF_AUTO_STABILIZATION): _num(0, 180, 1),
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
