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
            "comfort_temp": coordinator.comfort_config,
            "eco_temp": coordinator.eco_config,
            "current_temp": coordinator.current_temp,
            "current_humidity": coordinator.current_humidity,
            "preset_mode": coordinator.preset_mode,
            "fan_mode": coordinator.fan_mode,
            "boost_active": coordinator.boost_active,
            "window_blocked": coordinator.window_blocked,
            "calibration_mode": coordinator.calibration_mode,
            "calibration_offset": coordinator.calibration_offset,
            "last_applied_setpoints": coordinator.last_applied_setpoints,
            "last_applied_ac_setpoint": coordinator.last_applied_ac_setpoint,
        },
        "devices": {
            "all_trvs": coordinator.all_trvs,
            "ac_entity": coordinator.ac_entity,
            "temp_sensor": coordinator.temp_sensor,
            "humidity_sensor": coordinator.humidity_sensor,
            "window_sensor": coordinator.window_sensor,
        },
    }
