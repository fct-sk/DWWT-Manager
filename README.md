# DWWT Manager

DWWT Manager is a UI-configured Home Assistant custom integration for monitoring a small domestic wastewater treatment plant and scheduling its aeration blower. It creates one Home Assistant device per plant and works with entities already present in Home Assistant; it is not tied to Tasmota or any manufacturer.

> This software is operational assistance, not wastewater-process engineering advice. Confirm all schedules and thresholds with the plant manufacturer or a qualified technician.

## Features

- Multi-step Config Flow; no YAML, helpers, templates, or user automations required.
- Separate design capacity (nominal EO), actual estimated EO, and occupant count.
- Manual Visit, Residence, Fullhouse, and Holiday schedules plus transparent AUTO selection.
- Pump monitoring from a binary/switch state or, for float-controlled pumps, a power sensor threshold.
- Persistent starts, lifetime estimated volume, calendar-period totals, and rolling 1/6/24-hour activity.
- Restart-aware blower phase deadlines and persisted alarm-away timestamps.
- Optional alarm and inlet-pump assignments, English and Slovak entity translations.
- No wastewater/sludge pump control code.

## Installation

Copy `custom_components/dwwt_manager` into the Home Assistant configuration directory, restart Home Assistant, then choose **Settings → Devices & services → Add integration → DWWT Manager**. The repository also contains `hacs.json` for use as a HACS custom repository.

## Configuration

The flow asks for:

1. Plant identity, tank volume, and nominal design EO.
2. Occupants and estimated current EO. Zero means unknown; these values are not silently equated.
3. A blower `switch` or `fan` and optional nameplate data.
4. A pump state entity and/or power sensor, running threshold, and estimated discharge volume per cycle.
5. Optional inlet-pump and `alarm_control_panel` entities.
6. AUTO signals and thresholds.
7. Editable ON/OFF durations for each manual schedule.

The initial Visit 80/400, Residence 120/360, Fullhouse 240/240, and Holiday 10/470 minute values are configurable defaults based on one ECOkocka-style application. They are not universal recommendations.

### Pump detection and volume

When a power sensor is selected it takes precedence over the pump state entity. A transition from below to at/above the configured threshold records one start. Startup peaks do not create extra cycles while power remains above the threshold. If there is no power sensor, the selected switch/binary sensor's `on` state is used.

`estimated volume = detected cycles × configured liters per cycle`

The value is only an estimate unless the discharge volume per cycle has been measured and remains consistent. A direct flow meter is not implemented yet. Choose a threshold above standby/noise and below stable running power, then validate it from history; do not base it only on a startup peak.

## Entities

- Operating mode select (requested mode, including AUTO)
- Automatic blower control switch
- Active mode and AUTO reason
- Pump running and blower schedule phase
- Pump starts total and estimated pumped volume total
- Estimated volume today, this week, month, year, and last 24 hours
- Pump starts in the last 1, 6, and 24 hours
- Phase time remaining
- Disabled-by-default timestamps for last start, stop, and mode change
- Optional inlet-pump diagnostic entity

Lifetime totals use recorder-compatible `total` state classes and are also stored independently in Home Assistant's integration storage. Calendar and rolling values are derived from retained cycle timestamps.

## AUTO logic

AUTO uses an ordered, documented heuristic:

1. `armed_night` → Residence.
2. `armed_away` shorter than the configured timeout → Visit; at/after it → Holiday.
3. `armed_night → disarmed` stays Residence; `armed_away → disarmed` becomes Visit.
4. Configured high starts/hour or high 24-hour estimated volume → Fullhouse.
5. Configured normal 24-hour volume or recent starts → Residence.
6. Configured inactivity → Holiday; otherwise low measured activity → Visit.

Signals can be enabled independently. The AUTO reason sensor exposes the branch and observed value. Thresholds are application heuristics, not claims about biological treatment needs. Wi-Fi client counts are never used.

## Restart and safety behavior

The integration stores the blower phase, phase start, and wall-clock deadline. On restart it resumes the phase with its remaining time; an already-expired phase advances promptly. Mode changes start a fresh ON phase. Exactly one scheduler task belongs to each config entry and reload/unload cancels it.

If the blower entity is unavailable, DWWT Manager does not advance the schedule phase and retries once per minute. This avoids converting a temporary outage into a silently completed OFF phase. Home Assistant cannot guarantee equipment operation during a host outage, so the physical installation should have an appropriate independent fail-safe/default state. Disabling control stops service calls and leaves the blower in its current physical state.

Unavailable pump inputs do not create starts or reduce the lifetime total. The integration **never turns the wastewater/sludge pump on or off**. The optional inlet pump is currently exposed for assignment/diagnostics; it does not yet affect AUTO scoring.

## Manufacturer presets and custom plants

The data model keeps schedules under stable mode IDs and keeps equipment/plant metadata separate, allowing future preset catalogs. Version 0.1 ships editable defaults rather than enforcing an ECOkocka profile. Any other aerated plant can be configured by supplying its manufacturer-approved schedules and observed equipment entities.

## Development

Pure calculation tests run with `pytest`. Home Assistant-facing tests require a Home Assistant test environment (`pytest-homeassistant-custom-component`). Useful checks are:

```text
python -m pytest
python -m compileall custom_components tests
ruff check .
```

## Limitations and extension points

- Volume is cycle-based estimation, not direct metering.
- Inlet-pump activity is monitored only in this release.
- No dissolved oxygen, pH, ORP, turbidity, weather, anomaly detection, maintenance reminders, multiple tanks/blowers, or equipment energy accounting yet.
- Editing entity assignments and plant identity currently requires removing/re-adding the entry; numeric runtime tuning belongs in the options flow.
- The integration cannot replace manufacturer safety controls or confirm treatment performance.

The manager, persistent model, decision function, schedule map, and entity platforms are separate so direct meters, manufacturer presets, additional equipment, and more sophisticated documented load models can be added without rewriting the control engine.
