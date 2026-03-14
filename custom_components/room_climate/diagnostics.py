"""Diagnostics support for Room Climate integration."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import RoomClimateCoordinator
from .const import DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: RoomClimateCoordinator = hass.data[DOMAIN][entry.entry_id]

    return {
        "config": {**entry.data, **entry.options},
        "state": {
            "hvac_mode": coordinator.hvac_mode,
            "target_temp": coordinator.target_temp,
            "comfort_temp": coordinator.comfort_temp,
            "current_temp": coordinator.current_temp,
            "preset_mode": coordinator.preset_mode,
            "fan_mode": coordinator.fan_mode,
            "boost_active": coordinator.boost_active,
            "window_blocked": coordinator.window_blocked,
            "auto_submode": coordinator.auto_submode,
            "calibration_mode": coordinator.calibration_mode,
            "calibration_offset": coordinator.calibration_offset,
            "last_applied_setpoints": coordinator.last_applied_setpoints,
        },
        "devices": {
            "all_trvs": coordinator.all_trvs,
            "ac_entity": coordinator.ac_entity,
            "temp_sensor": coordinator.temp_sensor,
            "window_sensor": coordinator.window_sensor,
        },
    }
