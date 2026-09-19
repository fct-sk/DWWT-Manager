# DWWT Manager

DWWT Manager is a UI-configured Home Assistant custom integration for monitoring a small domestic wastewater treatment plant and scheduling its aeration blower. It creates one Home Assistant device per plant and works with entities already present in Home Assistant; it is not tied to Tasmota or any manufacturer.

> This software is operational assistance, not wastewater-process engineering advice. Confirm all schedules and thresholds with the plant manufacturer or a qualified technician.

## Features

- Multi-step Config Flow; no YAML, helpers, templates, or user automations required.
- Separate design capacity (nominal EO), actual estimated EO, and occupant count.
- Four fixed modes (Normal operation, Low load, Higher load, and Eco / Holiday), with separate aeration configuration and MANUAL/AUTO mode selection.
- Pump monitoring from a binary/switch state or, for float-controlled pumps, a power sensor threshold.
- Persistent starts, lifetime estimated volume, calendar-period totals, and rolling 1/6/24-hour activity.
- Restart-aware blower phase deadlines and persisted alarm-away timestamps.
- Optional alarm and inlet-pump assignments, English and Slovak entity translations.
- No wastewater/sludge pump control code.

## Installation

Copy `custom_components/dwwt_manager` into the Home Assistant configuration directory, restart Home Assistant, then choose **Settings → Devices & services → Add integration → DWWT Manager**. The repository also contains `hacs.json` for use as a HACS custom repository.

## Configuration

The three equipment assignments use Home Assistant device selection rather than entity IDs. They can be changed later under **Configure → Power devices**. Dedicated smart plugs are recommended: the blower device must expose one switch, while each pump device must expose one sensor with the `power` device class.

The flow asks for:

1. Plant identity, tank volume, and nominal design EO.
2. Occupants and estimated current EO. Zero means unknown; these values are not silently equated.
3. A Home Assistant device representing the blower smart plug; its single switch entity is discovered automatically.
4. A device representing the outlet-pump smart plug; its power sensor is discovered automatically, while its switch is never controlled.
5. An optional inlet-pump smart-plug device and optional `alarm_control_panel`; the inlet power sensor is discovered automatically.
6. AUTO signals and thresholds.
7. Editable ON/OFF durations for each manual schedule.

Manual ON/OFF values are configurable for all four modes. In automatic aeration V1, nominal_eo means the plant's rated/design capacity in equivalent inhabitants (EO), not current occupant count or current load. The occupants and estimated_eo fields are separate and do not enter the V1 calculation.

Operating mode represents current relative load independently of nominal capacity: NORMAL uses factor 1.0, LOW_LOAD 1/3, and HEAVY_LOAD 1.25. ECO uses a separate fixed 10/470-minute baseline. The factors and scaling are V1 heuristic assumptions.

For a 3 m3 tank and 60 L/min blower:

- A plant rated at 6 nominal EO gives NORMAL 240/240, LOW_LOAD 80/400, HEAVY_LOAD 300/180, and ECO 10/470 minutes ON/OFF.
- A plant rated at 2 nominal EO gives NORMAL 80/400 minutes ON/OFF.

A 6-EO plant in LOW_LOAD and a 2-EO plant in NORMAL therefore produce the same schedule but remain distinct capacity/mode combinations in the data model.

Automatic ON time is rounded to five-minute increments and clamped to 10–420 minutes; OFF is 480 minus ON. The 420-minute ceiling is a technical/heuristic limit, not a technologically validated boundary. These schedules are heuristic estimates.

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

1. `armed_night` → Normal operation.
2. `armed_away` shorter than the configured timeout → Low load; at/after it → Eco / Holiday.
3. `armed_night → disarmed` stays Normal operation; `armed_away → disarmed` becomes Low load.
4. Configured high starts/hour or high 24-hour estimated volume → Higher load.
5. Configured normal 24-hour volume or recent starts → Normal operation.
6. Prolonged configured inactivity → Eco / Holiday; otherwise low measured activity → Low load. Load-driven changes must remain stable for the configured debounce window.

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
