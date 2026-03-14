# Room Climate — Project Overview

## Purpose
Home Assistant custom integration that creates a virtual master climate entity per room,
coordinating a TRV (thermostatic radiator valve) and optional AC unit with:
- Offset calibration using an external temperature sensor
- Window-open detection with configurable debounce
- Boost mode for rapid warm-up
- State persistence across HA restarts

## Tech Stack
- **Language**: Python 3.12+
- **Framework**: Home Assistant Core (custom integration)
- **Package management**: None (HA manages deps via `manifest.json` requirements)
- **Config**: Multi-step UI config flow + options flow

## Codebase Structure
```
room_climate/                         ← GitHub repo root
├── README.md
├── hacs.json                         ← HACS metadata
├── .cursor/rules/                    ← Cursor IDE rules
└── custom_components/room_climate/   ← The actual HA integration
    ├── __init__.py                   ← RoomClimateCoordinator + entry setup/teardown
    ├── climate.py                    ← RoomClimateMaster ClimateEntity + RestoreEntity
    ├── binary_sensor.py              ← RoomClimateWindowBlocked BinarySensorEntity
    ├── config_flow.py                ← ConfigFlow + OptionsFlow (multi-step)
    ├── const.py                      ← All constants, config keys, defaults
    ├── manifest.json                 ← Integration metadata (domain, version, iot_class)
    ├── services.yaml                 ← Service definitions (enable_boost, disable_boost)
    ├── strings.json                  ← Translation source of truth
    └── translations/en.json          ← English translations (must match strings.json)
```

## Key Architecture
- **Coordinator pattern**: `RoomClimateCoordinator` is the state machine per room.
- **Multi-TRV**: `all_trvs = [primary] + additional_trvs`, per-TRV calibration.
- **Config merging**: `{**entry.data, **entry.options}` for options flow support.
- **Continuous recalibration**: sensor changes trigger `_async_recalibrate()`.
- **Auto mode**: `HVACMode.HEAT_COOL` with deadband ±0.5 °C, `_auto_submode` tracking.
- **Presets**: comfort/eco/away/boost; `_comfort_temp` stores base, presets derive `_target_temp`.
- **Fan mode**: read from AC entity attributes, passthrough via `set_fan_mode`.
- **Sensors**: calibration offset + TRV setpoint for debugging.
- **Diagnostics**: full state export via `diagnostics.py`.
- **Entity services**: boost enable/disable via `platform.async_register_entity_service()`.