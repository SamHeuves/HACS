# Room Climate — Progress & context for new chats

This file summarizes what has been done and agreed so far, so you can continue in a new chat.

---

## Project summary

- **What it is:** Home Assistant custom integration that creates a **virtual master climate entity per room**, coordinating one or more TRVs and an optional AC.
- **Repo:** `room_climate` (pushed to `https://github.com/SamHeuves/HACS`).
- **Integration path:** `custom_components/room_climate/`.
- **Docs / conventions:** See `.cursor/rules/room-climate.mdc` for file map, patterns, and coding rules. Some rules still mention “auto mode” and “away” — those features were removed (see below).

---

## What we’ve done (in order)

### 1. HACS and validation

- Added **`.github/workflows/validate.yml`** (HACS action, `category: "integration"`).
- Committed and pushed. **To install via HACS:** add custom repository `https://github.com/SamHeuves/HACS`, category **Integration**, then search for Room Climate and install.

### 2. Presets and Away removal

- **Removed Away** (preset and config: no `away_temp`, no `PRESET_AWAY`).
- **Comfort and Eco are fixed temperatures** (no “comfort minus offset”):
  - Config/options: **comfort_temp** and **eco_temp** (0–30 °C, defaults 20 and 17).
  - Coordinator: `_comfort_config`, `_eco_config`; preset Comfort → `_target_temp = _comfort_config`, Eco → `_eco_config`.
- **Boost is not a preset:** only a setting via services. Presets are **Comfort** and **Eco** only (`PRESET_MODES = [PRESET_COMFORT, PRESET_ECO]`).

### 3. Boost behaviour

- **Boost** is toggled only via **`room_climate.enable_boost`** / **`room_climate.disable_boost`** (no “boost sensor,” no auto turn-on when temp drops).
- **Auto turn-off:** when in Heat + boost and **current_temp >= target_temp**, we set `_boost_active = False` and re-apply (in `_async_recalibrate()`).
- **Services:** registered in **`__init__.py`** under domain **`room_climate`** with schema `entity_id: cv.entity_ids`; handler finds coordinator by matching `_climate_entity.entity_id` and calls `async_set_boost(True/False)`.

### 4. Heat/Cool (auto) mode removed

- **HEAT_COOL** removed from `climate.py` `hvac_modes` and from all coordinator logic.
- Removed: `_apply_auto_mode()`, `_auto_submode`, `AUTO_DEADBAND` (const), and any `auto_submode` in diagnostics/attributes.

### 5. Window-blocked behaviour

- **State when window blocked:** In `climate.py`, **`hvac_mode`** returns **OFF** when `coordinator.window_blocked`, so the card/UI show “Off” instead of “Heating” while blocked.
- **When `window_blocked` becomes true:** Only **after** the configured **window open delay** (e.g. 30 s). We do **not** set `_window_blocked = True` as soon as the sensor reports open; we set it inside **`_async_window_opened()`** after the delay. If the window closes before the delay, the timer is cancelled and `window_blocked` never turns on.
- **Notify:** We call `_notify_entities()` after turning off HVAC in `_async_window_opened()`.

### 6. Bubble Card template (`bubble-card-climate.yaml`)

- **Entity:** Card uses **`climate.maite_3`** (and `binary_sensor.maite_3_window_blocked` only in comments; overlay uses climate attribute).
- **Layout:**
  - **Main row:** **Boost** (enable) + **Normal** (disable boost), both visible when state=heat. **Only colour changes** — grey when inactive, highlighted when boost is active.
  - **Bottom row:** Off, Heat, Cool, Dry, Fan (row 1), then **Comfort** and **Eco** with **icon + text** on **row 2** (50% width each via CSS grid).
  - Comfort and Eco are on a **second line** of the bottom section: CSS grid (10 columns, 2 rows). When climate is **off**, Comfort and Eco buttons have **no color** (grey like others), even if preset is set.
- **Card config:** `rows: 2.5` for the card itself.
- **Overlay (“Window is open”):**
  - Condition: use **climate entity attribute** `window_blocked` (`s?.attributes?.window_blocked === true`), not the binary sensor entity (to avoid entity_id mismatches).
  - Append overlay to **`ha-card`** (or `card` fallback): `const host = card.querySelector('ha-card') || card; host.style.position = 'relative'; host.appendChild(overlay);` and higher z-index (999).
- **Services:** **`room_climate.enable_boost`** / **`room_climate.disable_boost`** / **`room_climate.toggle_boost`**. All take `entity_id: climate.maite_3`.

### 7. TRV setpoint (explained)

- **TRV setpoint** = the **calibrated temperature value** we send to the TRV (often higher than the room target because the TRV’s own sensor reads high). The integration computes it and exposes it via the “TRV setpoint” sensor for debugging.

---

### 8. AC fix and thorough review

- **AC bug fix (critical):** `_ac_set()` was using `climate.set_temperature` with `hvac_mode` parameter in a single call. Many AC integrations ignore the `hvac_mode` parameter and only set temperature, leaving the AC off/unchanged. **Fixed:** now calls `climate.set_hvac_mode` first, then `climate.set_temperature` as separate service calls.
- **AC off:** Changed from `climate.turn_off` to `climate.set_hvac_mode` with `HVACMode.OFF` for better compatibility.
- **Debug logging:** All AC helper methods (`_ac_off`, `_ac_set`, `_ac_fan_only`, `_ac_set_fan_mode`) now log at DEBUG level, showing entity_id, mode, and temperature. Boost service calls also log. Enable debug logging for `custom_components.room_climate` in HA to see them.
- **Cleanup:** Removed dead `_trv_off_one()` method (only `_off_all_trvs` is used). Fixed `binary_sensor.py` docstring. Updated `manifest.json` URLs to actual repo. Removed stale "auto modes" text from `strings.json` / `en.json`.

### 9. Gree/Vaillant AC timing fix

- **AC model:** Vaillant-branded Gree (uses HA's built-in `gree` integration, local UDP protocol).
- **Root cause of temperature-not-applying bug:** The Gree integration sends commands as UDP packets via `push_state_update()`. The physical device processes each UDP packet before it's ready for the next. Calling `climate.set_temperature` **immediately** after `climate.set_hvac_mode` (no delay) meant the device silently processed only the mode-change packet and dropped the temperature packet. Result: AC changed mode but stayed at old/default temperature (e.g. 16 °C minimum).
- **Fix:** Added `asyncio.sleep(0.5)` in `_ac_set()` between the `set_hvac_mode` call and the `set_temperature` call.
- **DRY / FAN_ONLY not working:** These HVAC modes may not be supported on this specific Vaillant unit. When a mode is not in the entity's `hvac_modes`, HA throws `ServiceValidationError` (caught, logged as warning). This is a hardware limitation — no code fix possible.
- **AC state changes excluded from TRV recalibration:** `_handle_state_change` skips `_async_recalibrate` when the state-changing entity is `self.ac_entity` (prevents the AC's own state change response from triggering unwanted setpoint recalculation on TRVs).

---

## Discussed but not (fully) implemented

- **Temperature range 0–25 °C:** Discussed; entity still uses `DEFAULT_MIN_TEMP = 5`, `DEFAULT_MAX_TEMP = 35`. Config flow presets use 0–30 for comfort/eco. If you want the thermostat slider to be 0–25, change defaults in `const.py` and use them in `climate.py`.
- **Fan mode names and icons:** Goal: nicer labels and icons for fan modes (e.g. mapping raw AC values to translations). Not implemented; currently we pass through AC’s `fan_modes` as-is.
- **Swing / air direction:** When AC is present, expose swing (and optionally horizontal swing on HA 2024.12+), read from AC and forward `set_swing_mode`. Not implemented.

---

## Important code locations

| Topic | Where |
|--------|--------|
| Boost services (enable/disable/toggle) | `__init__.py`: `_async_handle_boost_service`, `async_handle_toggle_boost`, registration in `async_setup_entry` |
| AC control (set_hvac_mode + set_temperature) | `__init__.py`: `_ac_set`, `_ac_off`, `_ac_fan_only`, `_ac_set_fan_mode` |
| Window open delay → set blocked | `__init__.py`: `_handle_window_change` (no immediate `_window_blocked = True`), `_async_window_opened` (sets `_window_blocked = True`) |
| Presets (comfort/eco fixed temps) | `const.py`: `CONF_COMFORT_TEMP`, `CONF_ECO_TEMP`, `PRESET_MODES`; `__init__.py`: `_comfort_config`/`_eco_config`, `async_set_preset_mode`; `config_flow.py`: presets step |
| Climate state OFF when window blocked | `climate.py`: `hvac_mode` property returns `HVACMode.OFF` when `coordinator.window_blocked` |
| Boost auto-off when target reached | `__init__.py`: inside `_async_recalibrate()`, when `_boost_active` and `current_temp >= _target_temp` |
| Card overlay and entity | `bubble-card-climate.yaml`: JS uses `climate.maite_3` and `s?.attributes?.window_blocked`; overlay appended to `ha-card` |

---

## Conventions (from rules; still apply)

- Config: `{**entry.data, **entry.options}`.
- All UI text in `strings.json` and `translations/en.json` (keep in sync).
- Use `HVACMode` enum, no raw mode strings.
- New constants in `const.py`; new services in `services.yaml`.
- Options flow: `self.config_entry`; optional fields with `user_input.get(KEY)` so clearing sets `None`.

---

## How to continue in a new chat

- Say you’re working on **Room Climate** (HA custom integration in `custom_components/room_climate/`).
- Refer to **`progress.md`** for what’s done and what was discussed (presets, boost, window, card, HACS).
- For coding patterns and file map, use **`.cursor/rules/room-climate.mdc`** (ignore references to “auto mode” and “away”; those are removed).
- Repo is at **`https://github.com/SamHeuves/HACS`**; default card entity in the template is **`climate.maite_3`**.
