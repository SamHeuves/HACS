"""Master climate entity for Room Climate integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import RoomClimateCoordinator
from .const import (
    DEFAULT_FAN_MODES,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_TARGET_TEMP,
    DEFAULT_TEMP_STEP,
    DOMAIN,
    FAN_AUTO,
    PRESET_MODES,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RoomClimateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RoomClimateMaster(coordinator, entry)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "enable_boost", {}, "async_enable_boost"
    )
    platform.async_register_entity_service(
        "disable_boost", {}, "async_disable_boost"
    )
    platform.async_register_entity_service(
        "toggle_boost", {}, "async_toggle_boost"
    )


class RoomClimateMaster(ClimateEntity, RestoreEntity):
    """Master climate entity for a room.

    Delegates all device control to the coordinator.  Exposes presets,
    fan mode (when AC is configured), auto heat/cool, and hvac_action
    for a polished thermostat-card experience.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = DEFAULT_MIN_TEMP
    _attr_max_temp = DEFAULT_MAX_TEMP
    _attr_target_temperature_step = DEFAULT_TEMP_STEP

    def __init__(
        self, coordinator: RoomClimateCoordinator, entry: ConfigEntry
    ) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_climate"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Room Climate",
            "model": "Virtual Climate Controller",
            "sw_version": "1.3.0",
        }

    async def async_added_to_hass(self) -> None:
        """Restore last state and register with coordinator.

        Validates the restored HVAC mode against the *current* hvac_modes
        list — otherwise a previously-saved mode (e.g. ``cool`` after the
        user removed their AC via options) would put the entity into an
        unselectable state. Falls back to OFF when invalid or missing.
        """
        self._coordinator.register_climate_entity(self)

        valid_modes = set(self.hvac_modes)
        last_state = await self.async_get_last_state()

        if last_state and last_state.state not in (
            "unknown", "unavailable", None
        ):
            try:
                hvac_mode = HVACMode(last_state.state)
            except ValueError:
                hvac_mode = HVACMode.OFF
            if hvac_mode not in valid_modes:
                hvac_mode = HVACMode.OFF

            try:
                target_temp = float(
                    last_state.attributes.get("temperature", DEFAULT_TARGET_TEMP)
                )
            except (TypeError, ValueError):
                target_temp = DEFAULT_TARGET_TEMP

            boost = bool(last_state.attributes.get("boost_active", False))
            preset = last_state.attributes.get("preset_mode")
            if preset not in PRESET_MODES:
                preset = None
            fan = last_state.attributes.get("fan_mode", FAN_AUTO)

            self._coordinator.restore_state(
                hvac_mode=hvac_mode,
                target_temp=target_temp,
                boost=boost,
                preset=preset,
                fan_mode=fan,
            )
            _LOGGER.debug(
                "%s: restored state hvac=%s temp=%.1f preset=%s fan=%s boost=%s",
                self._coordinator.name, hvac_mode, target_temp, preset, fan, boost,
            )
            # Push the restored state to the physical devices so they don't
            # drift out of sync until the next sensor update.
            await self._coordinator.async_apply_after_restore()
        else:
            await self._coordinator.async_set_hvac_mode(HVACMode.OFF)

    # ------------------------------------------------------------------
    # Dynamic supported features
    # ------------------------------------------------------------------

    @property
    def supported_features(self) -> ClimateEntityFeature:
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.PRESET_MODE
        )
        if self._coordinator.has_ac:
            features |= ClimateEntityFeature.FAN_MODE
        return features

    # ------------------------------------------------------------------
    # HVAC modes
    # ------------------------------------------------------------------

    @property
    def hvac_modes(self) -> list[HVACMode]:
        if self._coordinator.has_ac:
            return [
                HVACMode.OFF,
                HVACMode.HEAT,
                HVACMode.COOL,
                HVACMode.DRY,
                HVACMode.FAN_ONLY,
            ]
        return [HVACMode.OFF, HVACMode.HEAT]

    @property
    def hvac_mode(self) -> HVACMode:
        """Report OFF when window is open so card and UI show 'Off' instead of 'Heating'."""
        if self._coordinator.window_blocked:
            return HVACMode.OFF
        return HVACMode(self._coordinator.hvac_mode)

    @property
    def hvac_action(self) -> HVACAction | None:
        """Report what the system is currently doing for the thermostat card.

        Shows IDLE when the room temperature has already reached the target,
        so the thermostat card correctly turns grey instead of staying orange/blue.
        """
        if self._coordinator.window_blocked:
            return HVACAction.OFF

        mode = self._coordinator.hvac_mode
        if mode == HVACMode.OFF:
            return HVACAction.OFF

        current = self._coordinator.current_temp
        target = self._coordinator.target_temp

        if mode == HVACMode.HEAT:
            if current is not None and current >= target:
                return HVACAction.IDLE
            return HVACAction.HEATING
        if mode == HVACMode.COOL:
            if current is not None and current <= target:
                return HVACAction.IDLE
            return HVACAction.COOLING
        if mode == HVACMode.DRY:
            return HVACAction.DRYING
        if mode == HVACMode.FAN_ONLY:
            return HVACAction.FAN
        return None

    # ------------------------------------------------------------------
    # Temperature
    # ------------------------------------------------------------------

    @property
    def current_temperature(self) -> float | None:
        return self._coordinator.current_temp

    @property
    def target_temperature(self) -> float:
        return self._coordinator.target_temp

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    @property
    def preset_modes(self) -> list[str]:
        return PRESET_MODES

    @property
    def preset_mode(self) -> str | None:
        return self._coordinator.preset_mode

    # ------------------------------------------------------------------
    # Fan mode (only when AC is configured)
    # ------------------------------------------------------------------

    @property
    def fan_modes(self) -> list[str] | None:
        if not self._coordinator.has_ac:
            return None
        ac_state = self.hass.states.get(self._coordinator.ac_entity)
        if ac_state:
            modes = ac_state.attributes.get("fan_modes")
            if modes:
                return list(modes)
        return DEFAULT_FAN_MODES

    @property
    def fan_mode(self) -> str | None:
        if not self._coordinator.has_ac:
            return None
        return self._coordinator.fan_mode

    # ------------------------------------------------------------------
    # Extra attributes for dashboards and state restoration
    # ------------------------------------------------------------------

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "boost_active": self._coordinator.boost_active,
            "window_blocked": self._coordinator.window_blocked,
            "calibration_mode": self._coordinator.calibration_mode,
            "has_ac": self._coordinator.has_ac,
            "comfort_temp": self._coordinator.comfort_config,
            "eco_temp": self._coordinator.eco_config,
        }
        # Optional humidity, when we can derive it from a humidity sensor or
        # from the temp sensor's humidity attribute. Cards use this as
        # current_humidity.
        humidity = self._coordinator.current_humidity
        if humidity is not None:
            attrs["current_humidity"] = humidity
        if len(self._coordinator.all_trvs) > 1:
            attrs["trv_count"] = len(self._coordinator.all_trvs)
            # Per-TRV setpoints help debugging multi-radiator rooms; only
            # surface them when there's actually more than one TRV.
            setpoints = self._coordinator.last_applied_setpoints
            if setpoints:
                attrs["trv_setpoints"] = setpoints
        # AC's calibrated setpoint (after offset bias) — exposed when set
        # so the user can see what the integration is actually telling
        # the AC vs the master target.
        ac_sp = self._coordinator.last_applied_ac_setpoint
        if ac_sp is not None:
            attrs["ac_setpoint"] = ac_sp
        return attrs

    # ------------------------------------------------------------------
    # Service handlers
    # ------------------------------------------------------------------

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self._coordinator.async_set_hvac_mode(hvac_mode)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self._coordinator.async_set_temperature(float(temp))

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._coordinator.async_set_preset_mode(preset_mode)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._coordinator.async_set_fan_mode(fan_mode)

    async def async_turn_on(self) -> None:
        await self._coordinator.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self._coordinator.async_set_hvac_mode(HVACMode.OFF)

    async def async_enable_boost(self) -> None:
        """Enable boost mode — opens TRV valve fully and engages AC."""
        await self._coordinator.async_set_boost(True)

    async def async_disable_boost(self) -> None:
        """Disable boost mode — returns to normal calibrated operation."""
        await self._coordinator.async_set_boost(False)

    async def async_toggle_boost(self) -> None:
        """Toggle boost mode on or off."""
        await self._coordinator.async_set_boost(not self._coordinator.boost_active)
