"""Room Climate integration."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.climate import HVACMode
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
    AUTO_DEADBAND,
    BOOST_SETPOINT,
    CALIBRATION_AGGRESSIVE,
    CONF_AC_ENTITY,
    CONF_ADDITIONAL_TRVS,
    CONF_CALIBRATION_MODE,
    CONF_COMFORT_TEMP,
    CONF_ECO_TEMP,
    CONF_TADO_ENTITY,
    CONF_TEMP_SENSOR,
    CONF_WINDOW_CLOSE_DELAY,
    CONF_WINDOW_OPEN_DELAY,
    CONF_WINDOW_SENSOR,
    DEFAULT_COMFORT_TEMP,
    DEFAULT_ECO_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_TARGET_TEMP,
    DEFAULT_WINDOW_CLOSE_DELAY,
    DEFAULT_WINDOW_OPEN_DELAY,
    DOMAIN,
    DRY_MODE_TEMP,
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

    Manages mode routing, offset calibration, window detection, boost/presets,
    fan mode, auto heat-cool switching, and multi-TRV support.
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
        self._auto_submode: str | None = None

        # Window state
        self._window_blocked: bool = False
        self._window_open_task: asyncio.TimerHandle | None = None
        self._window_close_task: asyncio.TimerHandle | None = None

        # Per-TRV dedup to prevent redundant service calls
        self._last_applied_setpoints: dict[str, float] = {}

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
        if self.window_sensor:
            entities_to_watch.append(self.window_sensor)

        self._unsub_listeners.append(
            async_track_state_change_event(
                self.hass, entities_to_watch, self._handle_state_change
            )
        )

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
    def auto_submode(self) -> str | None:
        return self._auto_submode

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

    # ------------------------------------------------------------------
    # Calibrated setpoint calculation (per-TRV)
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

    # ------------------------------------------------------------------
    # Multi-TRV helpers
    # ------------------------------------------------------------------

    async def _heat_all_trvs(
        self, *, boost: bool = False, target: float | None = None
    ) -> None:
        """Set all TRVs to heat. Per-TRV calibration; dedup via last setpoint."""
        for trv in self.all_trvs:
            sp = BOOST_SETPOINT if boost else self._compute_tado_setpoint_for(trv, target)
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
        if hvac_mode != HVACMode.HEAT_COOL:
            self._auto_submode = None
        self._hvac_mode = hvac_mode
        self._last_applied_setpoints.clear()
        await self._async_apply()
        self._notify_entities()

    async def async_set_temperature(self, temperature: float) -> None:
        """Set a new target temperature (clears active preset)."""
        self._target_temp = temperature
        self._preset_mode = None
        self._boost_active = False
        self._last_applied_setpoints.clear()
        await self._async_apply()
        self._notify_entities()

    async def async_set_preset_mode(self, preset: str | None) -> None:
        """Activate a preset mode (comfort or eco — fixed temperatures)."""
        self._preset_mode = preset

        if preset == PRESET_ECO:
            self._target_temp = self._eco_config
        else:  # comfort or None
            self._target_temp = self._comfort_config

        self._last_applied_setpoints.clear()
        await self._async_apply()
        self._notify_entities()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode and apply to AC if active."""
        self._fan_mode = fan_mode
        if self.has_ac and self._hvac_mode in (
            HVACMode.COOL, HVACMode.HEAT_COOL, HVACMode.DRY, HVACMode.FAN_ONLY,
        ):
            await self._ac_set_fan_mode()
        if self._hvac_mode == HVACMode.HEAT and self._boost_active and self.has_ac:
            await self._ac_set_fan_mode()
        self._notify_entities()

    async def async_set_boost(self, active: bool) -> None:
        """Toggle boost via service call (separate from presets)."""
        self._boost_active = active
        if active and self._hvac_mode != HVACMode.HEAT:
            self._hvac_mode = HVACMode.HEAT
        self._last_applied_setpoints.clear()
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
        self._preset_mode = preset
        self._fan_mode = fan_mode or FAN_AUTO

    # ------------------------------------------------------------------
    # Apply current state to physical devices
    # ------------------------------------------------------------------

    async def _async_apply(self) -> None:
        """Push current master state to TRV(s) and optionally AC."""
        if self._window_blocked:
            _LOGGER.debug("%s: skipping apply — window blocked", self.name)
            return

        mode = self._hvac_mode

        if mode == HVACMode.OFF:
            await self._off_all_trvs()
            if self.has_ac:
                await self._ac_off()

        elif mode == HVACMode.HEAT:
            await self._heat_all_trvs(boost=self._boost_active)
            if self.has_ac:
                if self._boost_active:
                    await self._ac_set(HVACMode.HEAT, self._target_temp)
                else:
                    await self._ac_off()

        elif mode == HVACMode.HEAT_COOL:
            await self._apply_auto_mode()

        elif mode == HVACMode.COOL:
            await self._off_all_trvs()
            if self.has_ac:
                await self._ac_set(HVACMode.COOL, self._target_temp)

        elif mode == HVACMode.DRY:
            await self._off_all_trvs()
            if self.has_ac:
                await self._ac_set(HVACMode.DRY, DRY_MODE_TEMP)

        elif mode == HVACMode.FAN_ONLY:
            await self._off_all_trvs()
            if self.has_ac:
                await self._ac_fan_only()

    async def _apply_auto_mode(self) -> None:
        """Auto heat/cool: use deadband around target to decide action."""
        current = self.current_temp
        target = self._target_temp

        if current is None:
            self._auto_submode = "heating"
            await self._heat_all_trvs(target=target)
            if self.has_ac:
                await self._ac_off()
            return

        if current < target - AUTO_DEADBAND:
            self._auto_submode = "heating"
            await self._heat_all_trvs(target=target)
            if self.has_ac:
                await self._ac_off()

        elif current > target + AUTO_DEADBAND:
            self._auto_submode = "cooling"
            await self._off_all_trvs()
            if self.has_ac:
                await self._ac_set(HVACMode.COOL, target)

        elif self._auto_submode == "heating":
            await self._heat_all_trvs(target=target)
            if self.has_ac:
                await self._ac_off()

        elif self._auto_submode == "cooling":
            await self._off_all_trvs()
            if self.has_ac:
                await self._ac_set(HVACMode.COOL, target)

        else:
            self._auto_submode = None
            await self._off_all_trvs()
            if self.has_ac:
                await self._ac_off()

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
        else:
            if (
                self._hvac_mode in (HVACMode.HEAT, HVACMode.HEAT_COOL)
                and not self._window_blocked
            ):
                self.hass.async_create_task(self._async_recalibrate())
            self._notify_entities()

    async def _async_recalibrate(self) -> None:
        """Recalculate setpoints on sensor changes."""
        if self._hvac_mode == HVACMode.HEAT:
            if self._boost_active:
                return
            for trv in self.all_trvs:
                sp = self._compute_tado_setpoint_for(trv)
                if self._last_applied_setpoints.get(trv) != sp:
                    self._last_applied_setpoints[trv] = sp
                    await self._trv_heat_one(trv, sp)
                    _LOGGER.debug("%s: recalibrated %s → %.1f", self.name, trv, sp)
        elif self._hvac_mode == HVACMode.HEAT_COOL:
            await self._apply_auto_mode()

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

            self._window_blocked = True
            self._notify_entities()

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
        """Debounce expired — window confirmed open. Turn off HVAC."""
        self._window_open_task = None
        await self._off_all_trvs()
        if self.has_ac:
            await self._ac_off()
        _LOGGER.debug("%s: window opened — HVAC paused", self.name)

    async def _async_window_closed(self) -> None:
        """Close delay expired — restore previous state."""
        self._window_close_task = None
        self._window_blocked = False
        self._last_applied_setpoints.clear()
        await self._async_apply()
        self._notify_entities()
        _LOGGER.debug("%s: window closed — HVAC restored", self.name)

    # ------------------------------------------------------------------
    # Device helpers — TRV
    # ------------------------------------------------------------------

    async def _trv_off_one(self, entity_id: str) -> None:
        try:
            await self.hass.services.async_call(
                "climate", "turn_off", {"entity_id": entity_id}
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Failed to turn off %s: %s", entity_id, err)

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
        try:
            await self.hass.services.async_call(
                "climate", "turn_off", {"entity_id": self.ac_entity}
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Failed to turn off %s: %s", self.ac_entity, err)

    async def _ac_set(self, mode: str, temperature: float) -> None:
        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {
                    "entity_id": self.ac_entity,
                    "temperature": temperature,
                    "hvac_mode": mode,
                },
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Failed to set %s to %s at %.1f: %s",
                self.ac_entity, mode, temperature, err,
            )
            return
        await self._ac_set_fan_mode()

    async def _ac_fan_only(self) -> None:
        try:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": self.ac_entity, "hvac_mode": HVACMode.FAN_ONLY},
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Failed to set %s to fan_only: %s", self.ac_entity, err
            )
            return
        await self._ac_set_fan_mode()

    async def _ac_set_fan_mode(self) -> None:
        """Apply the selected fan mode to the AC."""
        if not self.has_ac:
            return
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
