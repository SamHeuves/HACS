"""Room Climate integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.climate import HVACMode
from homeassistant.components.climate.const import PRESET_NONE
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    Platform,
    STATE_ON,
    STATE_OPEN,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    AGGRESSIVE_MULTIPLIER,
    BOOST_FALLBACK_SETPOINT,
    CALIBRATION_AGGRESSIVE,
    DRY_MODE_TEMP,
    CONF_AC_ENTITY,
    CONF_ADDITIONAL_TRVS,
    CONF_CALIBRATION_MODE,
    CONF_COMFORT_TEMP,
    CONF_ECO_TEMP,
    CONF_HUMIDITY_SENSOR,
    CONF_TADO_ENTITY,
    CONF_TEMP_SENSOR,
    CONF_WINDOW_CLOSE_DELAY,
    CONF_WINDOW_OPEN_DELAY,
    CONF_WINDOW_SENSOR,
    DEFAULT_COMFORT_TEMP,
    DEFAULT_ECO_TEMP,
    DEFAULT_TARGET_TEMP,
    DEFAULT_WINDOW_CLOSE_DELAY,
    DEFAULT_WINDOW_OPEN_DELAY,
    DOMAIN,
    FAN_AUTO,
    PRESET_COMFORT,
    PRESET_ECO,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CLIMATE, Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Room Climate from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    coordinator = RoomClimateCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await coordinator.async_setup()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: RoomClimateCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.async_unload()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — reload the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


class RoomClimateCoordinator:
    """Central coordinator for one room.

    Manages mode routing, offset calibration, window detection, boost,
    presets, fan mode, and multi-TRV support. Owns the state machine —
    entities (climate, binary_sensor, sensor) are thin views over it.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.name: str = entry.title

        config = {**entry.data, **entry.options}

        # Devices
        self.tado_entity: str = config[CONF_TADO_ENTITY]
        self.additional_trvs: list[str] = [
            t for t in (config.get(CONF_ADDITIONAL_TRVS) or [])
            if t != self.tado_entity
        ]
        self.all_trvs: list[str] = [self.tado_entity] + self.additional_trvs
        self.ac_entity: str | None = config.get(CONF_AC_ENTITY)
        self.temp_sensor: str | None = config.get(CONF_TEMP_SENSOR)
        self.humidity_sensor: str | None = config.get(CONF_HUMIDITY_SENSOR)
        self.window_sensor: str | None = config.get(CONF_WINDOW_SENSOR)

        # Configuration
        self.calibration_mode: str = config.get(CONF_CALIBRATION_MODE, "normal")
        self.window_open_delay: int = int(
            config.get(CONF_WINDOW_OPEN_DELAY, DEFAULT_WINDOW_OPEN_DELAY)
        )
        self.window_close_delay: int = int(
            config.get(CONF_WINDOW_CLOSE_DELAY, DEFAULT_WINDOW_CLOSE_DELAY)
        )
        self._comfort_config: float = float(
            config.get(CONF_COMFORT_TEMP, DEFAULT_COMFORT_TEMP)
        )
        self._eco_config: float = float(
            config.get(CONF_ECO_TEMP, DEFAULT_ECO_TEMP)
        )

        # Master state
        self._hvac_mode: str = HVACMode.OFF
        self._target_temp: float = DEFAULT_TARGET_TEMP
        self._boost_active: bool = False
        self._preset_mode: str | None = None
        self._fan_mode: str = FAN_AUTO

        # Window state
        self._window_blocked: bool = False
        self._window_open_task: asyncio.TimerHandle | None = None
        self._window_close_task: asyncio.TimerHandle | None = None

        # Per-TRV dedup to prevent redundant service calls
        self._last_applied_setpoints: dict[str, float] = {}
        # Last AC setpoint we wrote (after offset calibration). ``None`` when
        # the AC is currently off / has no temperature concept (FAN_ONLY).
        self._last_applied_ac_setpoint: float | None = None

        # Listeners & registered entities
        self._unsub_listeners: list = []
        self._climate_entity = None
        self._window_sensor_entity = None
        self._sensor_entities: list = []

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Register state change listeners for all watched entities."""
        entities_to_watch = list(self.all_trvs)
        if self.ac_entity:
            entities_to_watch.append(self.ac_entity)
        if self.temp_sensor:
            entities_to_watch.append(self.temp_sensor)
        if self.humidity_sensor:
            entities_to_watch.append(self.humidity_sensor)
        if self.window_sensor:
            entities_to_watch.append(self.window_sensor)

        self._unsub_listeners.append(
            async_track_state_change_event(
                self.hass, entities_to_watch, self._handle_state_change
            )
        )

        # Window already open at startup: do not wait for an edge event — pause
        # HVAC immediately and still register the debounced handler so close→open
        # transitions behave consistently afterward.
        if self.window_sensor:
            state = self.hass.states.get(self.window_sensor)
            if state is not None and state.state in (
                STATE_ON,
                STATE_OPEN,
                "open",
            ):
                self._window_blocked = True
                await self._off_all_trvs()
                if self.has_ac:
                    await self._ac_off()
                _LOGGER.debug(
                    "%s: window open at startup — HVAC paused immediately",
                    self.name,
                )
                self._handle_window_change(state)

    @callback
    def async_unload(self) -> None:
        """Cancel all listeners and pending tasks."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
        if self._window_open_task:
            self._window_open_task.cancel()
        if self._window_close_task:
            self._window_close_task.cancel()

    # ------------------------------------------------------------------
    # Entity registration
    # ------------------------------------------------------------------

    def register_climate_entity(self, entity) -> None:
        self._climate_entity = entity

    def register_window_sensor_entity(self, entity) -> None:
        self._window_sensor_entity = entity

    def register_sensor_entity(self, entity) -> None:
        self._sensor_entities.append(entity)

    # ------------------------------------------------------------------
    # State properties
    # ------------------------------------------------------------------

    @property
    def hvac_mode(self) -> str:
        return self._hvac_mode

    @property
    def target_temp(self) -> float:
        return self._target_temp

    @property
    def comfort_config(self) -> float:
        """Configured comfort temperature (fixed)."""
        return self._comfort_config

    @property
    def eco_config(self) -> float:
        """Configured eco temperature (fixed)."""
        return self._eco_config

    @property
    def boost_active(self) -> bool:
        return self._boost_active

    @property
    def preset_mode(self) -> str | None:
        return self._preset_mode

    @property
    def fan_mode(self) -> str:
        return self._fan_mode

    @property
    def window_blocked(self) -> bool:
        return self._window_blocked

    @property
    def has_ac(self) -> bool:
        return self.ac_entity is not None

    @property
    def current_temp(self) -> float | None:
        """Current room temperature from external sensor or primary TRV."""
        if self.temp_sensor:
            state = self.hass.states.get(self.temp_sensor)
            if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                try:
                    return float(state.state)
                except ValueError:
                    pass
        state = self.hass.states.get(self.tado_entity)
        if state:
            return state.attributes.get("current_temperature")
        return None

    @property
    def current_humidity(self) -> float | None:
        """Current room humidity, when available.

        Priority:
        1. Dedicated external humidity sensor (if configured)
        2. Humidity attribute on the external temperature sensor
        3. None when nothing is available
        """
        if self.humidity_sensor:
            state = self.hass.states.get(self.humidity_sensor)
            if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    pass

        if self.temp_sensor:
            state = self.hass.states.get(self.temp_sensor)
            if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                hum = state.attributes.get("humidity")
                if hum is not None:
                    try:
                        return float(hum)
                    except (ValueError, TypeError):
                        pass
        return None

    @property
    def calibration_offset(self) -> float | None:
        """Current calibration offset applied to TRV setpoint."""
        if not self.temp_sensor:
            return None
        current = self.current_temp
        if current is None:
            return None
        offset = self._target_temp - current
        if self.calibration_mode == CALIBRATION_AGGRESSIVE:
            offset *= AGGRESSIVE_MULTIPLIER
        return round(offset, 2)

    @property
    def last_applied_setpoint(self) -> float | None:
        """Last setpoint sent to the primary TRV."""
        return self._last_applied_setpoints.get(self.tado_entity)

    @property
    def last_applied_setpoints(self) -> dict[str, float]:
        """All per-TRV setpoints (for diagnostics)."""
        return dict(self._last_applied_setpoints)

    @property
    def last_applied_ac_setpoint(self) -> float | None:
        """Last setpoint written to the AC (after offset calibration)."""
        return self._last_applied_ac_setpoint

    def _reset_applied_state(self) -> None:
        """Clear all per-device applied-setpoint trackers.

        Called whenever the next ``_async_apply`` must re-issue commands
        from scratch (mode change, preset change, manual temp, boost
        toggle, window restore).
        """
        self._last_applied_setpoints.clear()
        self._last_applied_ac_setpoint = None

    # ------------------------------------------------------------------
    # Calibrated setpoint calculation (per-TRV and per-AC)
    # ------------------------------------------------------------------

    def _compute_tado_setpoint_for(
        self, trv_entity: str, target: float | None = None
    ) -> float:
        """Compute calibrated setpoint for a specific TRV."""
        if target is None:
            target = self._target_temp

        if not self.temp_sensor:
            return target

        room_state = self.hass.states.get(self.temp_sensor)
        trv_state = self.hass.states.get(trv_entity)

        if not room_state or room_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return target
        if not trv_state or trv_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return target

        try:
            room_temp = float(room_state.state)
            trv_temp = float(
                trv_state.attributes.get("current_temperature", target)
            )
        except (ValueError, TypeError):
            return target

        offset = target - room_temp
        if self.calibration_mode == CALIBRATION_AGGRESSIVE:
            offset *= AGGRESSIVE_MULTIPLIER

        raw = trv_temp + offset
        mi = float(trv_state.attributes.get("min_temp", 5.0))
        ma = float(trv_state.attributes.get("max_temp", 30.0))
        step = float(trv_state.attributes.get("target_temp_step", 0.5))
        rounded = round(raw / step) * step
        return max(mi, min(rounded, ma))

    def _compute_ac_setpoint(self, target: float | None = None) -> float:
        """Compute calibrated AC setpoint, mirroring per-TRV calibration.

        The AC's internal sensor almost never agrees with the user's
        external room sensor (placement, return-air heat, sensor bias).
        Without calibration the AC's own thermostat shuts the compressor
        off when *its* sensor reads target while the actual room is still
        well off-target — exactly the "didn't stop when it reached the
        set temperature" symptom. Bias the setpoint by the (target - room)
        offset so the AC works toward the real room temperature; the
        offset converges to 0 once the room sensor reaches target, at
        which point the AC's own thermostat naturally idles the
        compressor.

        Aggressive calibration is intentionally NOT applied here: ACs
        already react aggressively, and amplifying further can drive the
        AC into corner regions of its temperature range.

        Falls back to ``target`` (no calibration) when the external sensor
        or AC state is missing or unparseable, or when the AC doesn't
        report ``current_temperature``.
        """
        if target is None:
            target = self._target_temp
        if not self.has_ac or not self.temp_sensor:
            return target

        room_state = self.hass.states.get(self.temp_sensor)
        ac_state = self.hass.states.get(self.ac_entity)
        if not room_state or room_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return target
        if not ac_state or ac_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return target

        ac_current = ac_state.attributes.get("current_temperature")
        if ac_current is None:
            return target

        try:
            room_temp = float(room_state.state)
            ac_temp = float(ac_current)
        except (ValueError, TypeError):
            return target

        offset = target - room_temp
        raw = ac_temp + offset

        mi = float(ac_state.attributes.get("min_temp", 16.0))
        ma = float(ac_state.attributes.get("max_temp", 32.0))
        return max(mi, min(round(raw), ma))

    # ------------------------------------------------------------------
    # Multi-TRV helpers
    # ------------------------------------------------------------------

    def _boost_setpoint_for(self, trv_entity: str) -> float:
        """Boost setpoint = the TRV's own max_temp (so the valve opens fully).

        Falls back to ``BOOST_FALLBACK_SETPOINT`` if the TRV doesn't expose
        ``max_temp`` (e.g. unavailable on startup).
        """
        state = self.hass.states.get(trv_entity)
        if state is not None:
            try:
                return float(state.attributes.get("max_temp", BOOST_FALLBACK_SETPOINT))
            except (ValueError, TypeError):
                pass
        return BOOST_FALLBACK_SETPOINT

    async def _heat_all_trvs(
        self, *, boost: bool = False, target: float | None = None
    ) -> None:
        """Set all TRVs to heat. Per-TRV calibration; dedup via last setpoint."""
        for trv in self.all_trvs:
            sp = (
                self._boost_setpoint_for(trv)
                if boost
                else self._compute_tado_setpoint_for(trv, target)
            )
            if self._last_applied_setpoints.get(trv) != sp:
                self._last_applied_setpoints[trv] = sp
                await self._trv_heat_one(trv, sp)

    async def _off_all_trvs(self) -> None:
        """Turn off all TRVs in a single batched service call."""
        try:
            await self.hass.services.async_call(
                "climate", "turn_off", {"entity_id": self.all_trvs}
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Failed to turn off TRVs: %s", err)
        self._last_applied_setpoints.clear()

    # ------------------------------------------------------------------
    # Public setters — called by the master climate entity
    # ------------------------------------------------------------------

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Set a new HVAC mode."""
        if hvac_mode != HVACMode.HEAT and self._boost_active:
            self._boost_active = False
        self._hvac_mode = hvac_mode
        if hvac_mode == HVACMode.DRY:
            self._target_temp = DRY_MODE_TEMP
        self._reset_applied_state()
        await self._async_apply()
        self._notify_entities()

    async def async_set_temperature(self, temperature: float) -> None:
        """Set a new target temperature (clears active preset)."""
        self._target_temp = temperature
        self._preset_mode = None
        self._boost_active = False
        self._reset_applied_state()
        await self._async_apply()
        self._notify_entities()

    async def async_set_preset_mode(self, preset: str | None) -> None:
        """Activate a preset mode (comfort or eco — fixed temperatures).

        Clearing the preset (``None``, ``PRESET_NONE``, or empty) leaves the
        current target temperature alone — only explicit comfort/eco retargets.

        Selecting a preset cancels boost so UI state stays consistent.
        """
        self._boost_active = False

        if preset in (None, PRESET_NONE, ""):
            self._preset_mode = None
        elif preset == PRESET_ECO:
            self._preset_mode = PRESET_ECO
            self._target_temp = self._eco_config
        elif preset == PRESET_COMFORT:
            self._preset_mode = PRESET_COMFORT
            self._target_temp = self._comfort_config
        else:
            self._preset_mode = None

        self._reset_applied_state()
        await self._async_apply()
        self._notify_entities()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode and apply to AC if active."""
        self._fan_mode = fan_mode
        if self.has_ac and self._hvac_mode in (
            HVACMode.COOL, HVACMode.DRY, HVACMode.FAN_ONLY,
        ):
            await self._ac_set_fan_mode()
        if self._hvac_mode == HVACMode.HEAT and self._boost_active and self.has_ac:
            await self._ac_set_fan_mode()
        self._notify_entities()

    async def async_set_boost(self, active: bool) -> None:
        """Toggle boost via service call.

        Boost is a transient override: enabling it forces HEAT mode and
        clears any active preset so the master entity's reported state
        is never internally inconsistent (e.g. ``preset=eco`` at the same
        time as boost driving the valve fully open).
        """
        self._boost_active = active
        if active:
            if self._hvac_mode != HVACMode.HEAT:
                self._hvac_mode = HVACMode.HEAT
            self._preset_mode = None
        self._reset_applied_state()
        await self._async_apply()
        self._notify_entities()

    # ------------------------------------------------------------------
    # Restore state after restart
    # ------------------------------------------------------------------

    def restore_state(
        self,
        *,
        hvac_mode: str,
        target_temp: float,
        boost: bool,
        preset: str | None,
        fan_mode: str,
    ) -> None:
        """Called by the climate entity after it restores its last state."""
        self._hvac_mode = hvac_mode
        self._target_temp = target_temp
        self._boost_active = boost
        self._preset_mode = None if boost else preset
        self._fan_mode = fan_mode or FAN_AUTO

    async def async_apply_after_restore(self) -> None:
        """Push the restored state to physical devices.

        Called once during entity setup, after ``restore_state``. Without
        this, TRVs/AC keep whatever they were doing before HA died until
        the next watched-entity state change forces a recalibration.
        """
        # Window-blocked check is handled inside ``_async_apply``.
        self._reset_applied_state()
        await self._async_apply()

    # ------------------------------------------------------------------
    # Apply current state to physical devices
    # ------------------------------------------------------------------

    async def _async_apply(self) -> None:
        """Push current master state to TRV(s) and optionally AC."""
        if self._window_blocked:
            _LOGGER.debug("%s: skipping apply — window blocked", self.name)
            return

        mode = self._hvac_mode
        _LOGGER.debug(
            "%s: _async_apply mode=%s boost=%s has_ac=%s target_temp=%.1f",
            self.name, mode, self._boost_active, self.has_ac, self._target_temp,
        )

        if mode == HVACMode.OFF:
            await self._off_all_trvs()
            if self.has_ac:
                await self._ac_off()
                self._last_applied_ac_setpoint = None

        elif mode == HVACMode.HEAT:
            await self._heat_all_trvs(boost=self._boost_active)
            if self.has_ac:
                if self._boost_active:
                    # During boost the AC actively heats — calibrate the
                    # setpoint against the room sensor so the AC works
                    # toward the real room temperature, not its own.
                    sp = self._compute_ac_setpoint()
                    await self._ac_set(HVACMode.HEAT, sp)
                    self._last_applied_ac_setpoint = sp
                else:
                    await self._ac_off()
                    self._last_applied_ac_setpoint = None

        elif mode == HVACMode.COOL:
            await self._off_all_trvs()
            if self.has_ac:
                # Calibrate the AC setpoint against the room sensor: most
                # ACs have a biased internal sensor and would otherwise
                # idle the compressor while the actual room is still off
                # target.
                sp = self._compute_ac_setpoint()
                await self._ac_set(HVACMode.COOL, sp)
                self._last_applied_ac_setpoint = sp

        elif mode == HVACMode.DRY:
            await self._off_all_trvs()
            if self.has_ac:
                # DRY mode primarily targets humidity, but most ACs still
                # honour a setpoint while in DRY. Calibrating it keeps the
                # behaviour consistent with COOL.
                sp = self._compute_ac_setpoint()
                await self._ac_set(HVACMode.DRY, sp)
                self._last_applied_ac_setpoint = sp

        elif mode == HVACMode.FAN_ONLY:
            await self._off_all_trvs()
            if self.has_ac:
                await self._ac_fan_only()
                # FAN_ONLY has no temperature concept on most ACs.
                self._last_applied_ac_setpoint = None

    # ------------------------------------------------------------------
    # State change handling
    # ------------------------------------------------------------------

    @callback
    def _handle_state_change(self, event) -> None:
        """Dispatch state change events."""
        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")

        if entity_id == self.window_sensor:
            self._handle_window_change(new_state)
            return

        if entity_id == self.ac_entity:
            # AC state changes (from our own commands or external changes)
            # MUST NOT trigger recalibration — that would create a feedback
            # loop (AC sensor change → new offset → new setpoint → AC reacts
            # → AC sensor change). Just refresh the entity views.
            self._notify_entities()
            return

        # External room sensor / TRV state changes are the legitimate
        # signals that drive recalibration: the room temperature evolved
        # and either the TRV (HEAT) or the AC (COOL/DRY/HEAT+boost) needs
        # its setpoint biased differently.
        if self._needs_recalibration():
            # _async_recalibrate notifies entities itself once the new
            # setpoints have been applied — no immediate notify here,
            # otherwise dependent sensors would report stale values for
            # one tick.
            self.hass.async_create_task(self._async_recalibrate())
        else:
            self._notify_entities()

    def _needs_recalibration(self) -> bool:
        """Whether the current state benefits from sensor-driven recalibration.

        - HEAT (with or without boost): TRVs always; AC during boost.
        - COOL / DRY: AC tracks calibrated setpoint.
        - FAN_ONLY / OFF / window-blocked: nothing to recalibrate.
        """
        if self._window_blocked:
            return False
        if self._hvac_mode == HVACMode.HEAT:
            return True
        if self._hvac_mode in (HVACMode.COOL, HVACMode.DRY) and self.has_ac:
            return True
        return False

    async def _async_recalibrate(self) -> None:
        """Recalculate TRV and AC setpoints on sensor changes.

        Auto-cancels boost once the room reaches the master target.
        """
        mode = self._hvac_mode

        if mode == HVACMode.HEAT and self._boost_active:
            # Boost auto-off: the master target was reached, so even
            # though boost was driving the valve fully open, we no
            # longer need it. Falls through to a normal apply.
            current = self.current_temp
            if current is not None and current >= self._target_temp:
                self._boost_active = False
                self._reset_applied_state()
                await self._async_apply()
                _LOGGER.debug(
                    "%s: boost auto-off — target %.1f °C reached",
                    self.name,
                    self._target_temp,
                )
            else:
                # Still boosting: TRVs are already at max, but the AC
                # still needs its setpoint recalibrated as the room warms.
                await self._maybe_recalibrate_ac()

        elif mode == HVACMode.HEAT:
            for trv in self.all_trvs:
                sp = self._compute_tado_setpoint_for(trv)
                if self._last_applied_setpoints.get(trv) != sp:
                    self._last_applied_setpoints[trv] = sp
                    await self._trv_heat_one(trv, sp)
                    _LOGGER.debug(
                        "%s: recalibrated %s → %.1f", self.name, trv, sp
                    )

        elif mode in (HVACMode.COOL, HVACMode.DRY) and self.has_ac:
            await self._maybe_recalibrate_ac()

        self._notify_entities()

    async def _maybe_recalibrate_ac(self) -> None:
        """Push a fresh calibrated setpoint to the AC if it has changed.

        Uses ``_ac_set_temperature_only`` (no mode/fan re-set) because the
        mode is already correct — only the calibrated temperature needs to
        track room evolution. Dedup is by integer comparison since AC
        setpoints are always rounded to whole degrees.
        """
        sp = self._compute_ac_setpoint()
        if self._last_applied_ac_setpoint is not None and round(
            self._last_applied_ac_setpoint
        ) == round(sp):
            return
        self._last_applied_ac_setpoint = sp
        await self._ac_set_temperature_only(sp)
        _LOGGER.debug(
            "%s: AC setpoint recalibrated → %d (room=%s, target=%.1f)",
            self.name, round(sp), self.current_temp, self._target_temp,
        )

    # ------------------------------------------------------------------
    # Window logic
    # ------------------------------------------------------------------

    @callback
    def _handle_window_change(self, new_state) -> None:
        """Handle window sensor state change with debounce."""
        if new_state is None:
            return

        is_open = new_state.state in (STATE_ON, STATE_OPEN, "open")

        if is_open:
            if self._window_close_task:
                self._window_close_task.cancel()
                self._window_close_task = None

            if self._window_open_task:
                self._window_open_task.cancel()
            self._window_open_task = self.hass.loop.call_later(
                self.window_open_delay,
                lambda: self.hass.async_create_task(
                    self._async_window_opened()
                ),
            )
        else:
            if self._window_open_task:
                self._window_open_task.cancel()
                self._window_open_task = None

            if self._window_close_task:
                self._window_close_task.cancel()
            self._window_close_task = self.hass.loop.call_later(
                self.window_close_delay,
                lambda: self.hass.async_create_task(
                    self._async_window_closed()
                ),
            )

    async def _async_window_opened(self) -> None:
        """Debounce expired — window confirmed open. Set blocked and turn off HVAC."""
        self._window_open_task = None
        self._window_blocked = True
        await self._off_all_trvs()
        if self.has_ac:
            await self._ac_off()
        self._notify_entities()
        _LOGGER.debug("%s: window opened — HVAC paused (after %s s)", self.name, self.window_open_delay)

    async def _async_window_closed(self) -> None:
        """Close delay expired — restore previous state."""
        self._window_close_task = None
        self._window_blocked = False
        self._reset_applied_state()
        await self._async_apply()
        self._notify_entities()
        _LOGGER.debug("%s: window closed — HVAC restored", self.name)

    # ------------------------------------------------------------------
    # Device helpers — TRV
    # ------------------------------------------------------------------

    async def _trv_heat_one(self, entity_id: str, setpoint: float) -> None:
        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {
                    "entity_id": entity_id,
                    "temperature": setpoint,
                    "hvac_mode": HVACMode.HEAT,
                },
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Failed to set %s to heat at %.1f: %s", entity_id, setpoint, err
            )

    # ------------------------------------------------------------------
    # Device helpers — AC
    # ------------------------------------------------------------------

    async def _ac_off(self) -> None:
        _LOGGER.debug("%s: _ac_off → %s", self.name, self.ac_entity)
        try:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": self.ac_entity, "hvac_mode": HVACMode.OFF},
            )
            _LOGGER.debug("%s: _ac_off OK", self.name)
        except HomeAssistantError as err:
            _LOGGER.warning("%s: _ac_off failed: %s", self.ac_entity, err)

    async def _ac_set(self, mode: str, temperature: float) -> None:
        temp_int = round(temperature)
        ac_state = self.hass.states.get(self.ac_entity)
        ac_mode_before = ac_state.state if ac_state else "unknown"
        ac_temp_before = (
            ac_state.attributes.get("temperature") if ac_state else "unknown"
        )
        _LOGGER.debug(
            "%s: _ac_set START → entity=%s desired_mode=%s desired_temp=%d "
            "| AC before: mode=%s temp=%s",
            self.name, self.ac_entity, mode, temp_int,
            ac_mode_before, ac_temp_before,
        )

        # ── Step 1: set HVAC mode ──
        try:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": self.ac_entity, "hvac_mode": mode},
            )
            _LOGGER.debug("%s: _ac_set step 1 OK (set_hvac_mode=%s)", self.name, mode)
        except HomeAssistantError as err:
            _LOGGER.warning(
                "%s: _ac_set step 1 failed (set_hvac_mode=%s): %s",
                self.name, mode, err,
            )
            return

        # Gree devices need ~1s to commit a mode change over UDP before they
        # accept a follow-up temperature command. The two short sleeps are
        # tuned for that hardware quirk; do not remove without validating
        # against the actual AC.
        await asyncio.sleep(1.0)

        # ── Step 2: set temperature ──
        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": self.ac_entity, "temperature": temp_int},
            )
            _LOGGER.debug(
                "%s: _ac_set step 2 OK (set_temperature=%d)", self.name, temp_int
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "%s: _ac_set step 2 failed (set_temperature=%d): %s",
                self.name, temp_int, err,
            )
            return

        await asyncio.sleep(0.5)

        # ── Step 3: set fan mode ──
        await self._ac_set_fan_mode()

        # ── Verify final AC state ──
        ac_state_after = self.hass.states.get(self.ac_entity)
        ac_mode_after = ac_state_after.state if ac_state_after else "unknown"
        ac_temp_after = (
            ac_state_after.attributes.get("temperature")
            if ac_state_after
            else "unknown"
        )
        _LOGGER.debug(
            "%s: _ac_set DONE | AC after: mode=%s temp=%s",
            self.name, ac_mode_after, ac_temp_after,
        )

    async def _ac_set_temperature_only(self, temperature: float) -> None:
        """Update only the AC's target temperature (no mode/fan re-set).

        Used by the recalibration loop while the AC stays in the same
        mode. Skips the mode-change handshake (and the Gree-specific
        sleeps) that ``_ac_set`` performs.
        """
        if not self.has_ac:
            return
        temp_int = round(temperature)
        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": self.ac_entity, "temperature": temp_int},
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "%s: _ac_set_temperature_only failed: %s",
                self.ac_entity, err,
            )

    async def _ac_fan_only(self) -> None:
        _LOGGER.debug("%s: AC fan_only → %s", self.name, self.ac_entity)
        try:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": self.ac_entity, "hvac_mode": HVACMode.FAN_ONLY},
            )
            _LOGGER.debug("%s: _ac_fan_only set_hvac_mode OK", self.name)
        except HomeAssistantError as err:
            _LOGGER.warning(
                "%s: _ac_fan_only set_hvac_mode failed: %s", self.name, err
            )
            return
        await asyncio.sleep(1.0)
        await self._ac_set_fan_mode()

    async def _ac_set_fan_mode(self) -> None:
        """Apply the selected fan mode to the AC."""
        if not self.has_ac:
            return
        _LOGGER.debug(
            "%s: AC fan_mode → %s fan=%s", self.name, self.ac_entity, self._fan_mode
        )
        try:
            await self.hass.services.async_call(
                "climate",
                "set_fan_mode",
                {"entity_id": self.ac_entity, "fan_mode": self._fan_mode},
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Failed to set fan mode on %s: %s", self.ac_entity, err
            )

    # ------------------------------------------------------------------
    # Notify registered entities
    # ------------------------------------------------------------------

    @callback
    def _notify_entities(self) -> None:
        if self._climate_entity:
            self._climate_entity.async_write_ha_state()
        if self._window_sensor_entity:
            self._window_sensor_entity.async_write_ha_state()
        for sensor in self._sensor_entities:
            sensor.async_write_ha_state()
