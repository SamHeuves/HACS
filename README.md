# Room Climate

A Home Assistant custom integration that unifies **one or more TRVs** (Thermostatic Radiator Valves) and an optional **AC unit** into a single virtual climate entity per room — with automatic temperature offset calibration, preset modes for scheduling, fan speed control, auto heat/cool switching, window-open detection, and full diagnostics.

## Features

| Feature | Description |
|---------|-------------|
| **Unified Control** | One climate entity to control all heating and cooling in a room |
| **Multi-TRV Support** | Rooms with multiple radiators — each TRV gets an individually calibrated setpoint |
| **Offset Calibration** | External temperature sensor corrects TRV sensor drift for accurate room temperature |
| **Auto Mode** | Automatically switches between heating and cooling based on temperature with deadband hysteresis |
| **Preset Modes** | Comfort, Eco, Away, and Boost presets — combine with automations for scheduling |
| **Fan Speed Control** | Reads available fan modes from the AC entity and lets you control them from the master entity |
| **Boost Mode** | Drives all TRV valves fully open and engages the AC for rapid warm-up |
| **Window Detection** | Pauses all HVAC when a window opens, restores when it closes (configurable debounce) |
| **HVAC Action** | Reports real-time heating/cooling/idle status for the thermostat card |
| **Debug Sensors** | Calibration offset and TRV setpoint sensors for monitoring and troubleshooting |
| **Diagnostics** | Full state export via HA's diagnostics panel |
| **State Persistence** | Remembers mode, temperature, preset, fan mode, and boost state across restarts |

## How It Works

### The Problem

TRVs like Tado have a built-in temperature sensor that sits right on the radiator. This sensor often reads several degrees higher than the actual room temperature, causing the TRV to stop heating too early. Meanwhile, if you also have an AC unit, you're managing separate climate entities for the same room. And if you have multiple radiators, each one needs its own setpoint.

### The Solution

Room Climate creates a **virtual master climate entity** that:

1. Takes your target temperature (e.g., 21 °C)
2. Reads the actual room temperature from an external sensor (e.g., 19 °C)
3. Calculates a per-TRV calibrated setpoint that keeps the valve open as needed
4. Continuously recalibrates as sensor readings change
5. Routes cooling/dry/fan/auto commands to the AC
6. Monitors a window sensor and shuts everything down when the window opens
7. Supports preset modes for easy scheduling via automations

### Calibration Modes

| Mode | Formula | Best For |
|------|---------|----------|
| **Normal** | `setpoint = trv_reading + (target − room_reading)` | Most rooms |
| **Aggressive** | `setpoint = trv_reading + (target − room_reading) × 1.5` | Rooms with poor heat distribution |

Each TRV is individually calibrated based on its own sensor reading.

### HVAC Mode Routing

| Master Mode | TRV(s) | AC |
|-------------|--------|-----|
| Off | Off | Off |
| Heat | Calibrated setpoint | Off |
| Heat + Boost | Max setpoint (25 °C) | Heat at target temp |
| Heat/Cool (Auto) | Heat if below target − 0.5 °C | Cool if above target + 0.5 °C |
| Cool | Off | Cool at target temp |
| Dry | Off | Dry at 16 °C |
| Fan Only | Off | Fan only |

### Preset Modes

| Preset | Behavior |
|--------|----------|
| **Comfort** | Uses your manually set target temperature |
| **Eco** | Reduces target by a configurable offset (default 3 °C) |
| **Away** | Sets a fixed low temperature (default 15 °C) |
| **Boost** | Drives TRVs to max, engages AC in heat — auto-switches to heat mode |

Presets are the recommended way to implement **scheduling**: create HA automations that switch presets at specific times (e.g., Eco at night, Comfort in the morning, Away when nobody's home).

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add your repository URL with category **Integration**
4. Search for **Room Climate** and install
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration → Room Climate**

### Manual Installation

1. Download or clone this repository
2. Copy the `custom_components/room_climate` folder into your Home Assistant's `custom_components/` directory
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration → Room Climate**

## Configuration

The integration uses a guided multi-step config flow:

1. **Room Setup** — Name the room and select the primary TRV
2. **Optional Devices** — Add an AC unit, external temperature sensor, and/or additional TRVs
3. **Window Sensor** — Add a window sensor with configurable open/close debounce delays
4. **Calibration** — Choose Normal or Aggressive mode (only shown when a temp sensor is configured)
5. **Presets** — Configure Eco temperature reduction and Away temperature

All settings can be changed later via **Configure** on the integration card.

## Entities Created

| Entity | Type | Description |
|--------|------|-------------|
| `climate.<room>` | Climate | The master climate controller |
| `sensor.<room>_calibration_offset` | Sensor | Current calibration offset in °C (only with temp sensor) |
| `sensor.<room>_trv_setpoint` | Sensor | Last setpoint sent to the primary TRV |
| `binary_sensor.<room>_window_blocked` | Binary Sensor | ON when window is open and HVAC is paused |

## Services

| Service | Description |
|---------|-------------|
| `room_climate.enable_boost` | Activates boost mode for rapid warm-up |
| `room_climate.disable_boost` | Deactivates boost mode |

Both services target a Room Climate entity and can be called from automations, scripts, or the developer tools.

## Entity Attributes

The master climate entity exposes these extra attributes for dashboards and templates:

| Attribute | Type | Description |
|-----------|------|-------------|
| `boost_active` | bool | Whether boost mode is currently active |
| `window_blocked` | bool | Whether HVAC is paused due to an open window |
| `calibration_mode` | string | Current calibration mode |
| `has_ac` | bool | Whether an AC unit is configured |
| `comfort_temp` | float | The base comfort temperature (before preset adjustments) |
| `auto_submode` | string | Current auto action: `heating`, `cooling`, or `null` (only in auto mode) |
| `trv_count` | int | Number of TRVs (only shown when > 1) |

## Dashboard Tips

The HA thermostat card works beautifully out of the box with this integration:

- **HVAC Action colors** — The card automatically shows orange for heating, blue for cooling, and grey for idle based on the `hvac_action` attribute
- **Preset chips** — All four presets (Comfort, Eco, Away, Boost) appear as selectable options
- **Fan mode** — When AC is configured, a fan mode dropdown appears
- **Auto mode** — Select "Heat/Cool" to let the system automatically switch between heating and cooling

For custom dashboard cards, use the `window_blocked` attribute to show a window-open overlay and disable controls.

## Scheduling with Automations

Use HA automations to switch presets on a schedule:

```yaml
automation:
  - alias: "Night mode"
    trigger:
      - platform: time
        at: "22:00"
    action:
      - service: climate.set_preset_mode
        target:
          entity_id: climate.living_room
        data:
          preset_mode: eco

  - alias: "Morning comfort"
    trigger:
      - platform: time
        at: "07:00"
    action:
      - service: climate.set_preset_mode
        target:
          entity_id: climate.living_room
        data:
          preset_mode: comfort
```

## Architecture

```
┌─────────────────────────────────────────┐
│         RoomClimateMaster               │  ← User-facing climate entity
│  (climate.py + RestoreEntity)           │
│  Presets · Fan mode · HVAC Action       │
└─────────────┬───────────────────────────┘
              │ delegates to
┌─────────────▼───────────────────────────┐
│       RoomClimateCoordinator            │  ← Central state machine
│  (__init__.py)                          │
│                                         │
│  • Per-TRV calibrated setpoints         │
│  • Auto heat/cool with deadband         │
│  • Preset mode management               │
│  • Fan mode passthrough to AC           │
│  • Window debounce logic                │
│  • Boost mode (TRV max + AC heat)       │
│  • Continuous recalibration             │
└──────┬──────────┬───────┬───────────────┘
       │          │       │
   ┌───▼───┐  ┌──▼──┐  ┌─▼────┐
   │ TRV 1 │  │ TRV │  │  AC  │  ← Physical devices
   │(primary)│ │ 2..N│  │      │    (via HA service calls)
   └───────┘  └─────┘  └──────┘
```

## Diagnostics

Go to **Settings → Devices & Services → Room Climate → (your room) → 3 dots → Download diagnostics** to get a JSON dump of all configuration and state for debugging.

## Repository Structure

```
room-climate/
├── README.md
├── hacs.json
└── custom_components/
    └── room_climate/
        ├── __init__.py          # Coordinator + entry setup
        ├── binary_sensor.py     # Window-blocked binary sensor
        ├── climate.py           # Master climate entity
        ├── config_flow.py       # Config + options flow
        ├── const.py             # Constants and defaults
        ├── diagnostics.py       # Diagnostics export
        ├── manifest.json        # Integration metadata
        ├── sensor.py            # Calibration offset + TRV setpoint sensors
        ├── services.yaml        # Service definitions
        ├── strings.json         # Translation source
        └── translations/
            └── en.json          # English translations
```

## License

MIT
