"""Sensor entities for Room Climate integration."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import RoomClimateCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: RoomClimateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    if coordinator.temp_sensor:
        entities.append(RoomClimateCalibrationOffset(coordinator, entry))

    entities.append(RoomClimateTRVSetpoint(coordinator, entry))
    async_add_entities(entities)


class RoomClimateCalibrationOffset(SensorEntity):
    """Shows the calibration offset currently applied to the TRV setpoint.

    No device_class — an offset is a delta, not an absolute temperature.
    Setting TEMPERATURE device_class would cause HA to convert it as an
    absolute value (e.g. 3°C → 37.4°F instead of the correct 5.4°F).
    """

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "°C"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:thermometer-plus"

    def __init__(
        self, coordinator: RoomClimateCoordinator, entry: ConfigEntry
    ) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_calibration_offset"
        self._attr_name = "Calibration Offset"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
        }

    async def async_added_to_hass(self) -> None:
        self._coordinator.register_sensor_entity(self)

    @property
    def native_value(self) -> float | None:
        return self._coordinator.calibration_offset


class RoomClimateTRVSetpoint(SensorEntity):
    """Shows the last setpoint sent to the primary TRV."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:radiator"

    def __init__(
        self, coordinator: RoomClimateCoordinator, entry: ConfigEntry
    ) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_trv_setpoint"
        self._attr_name = "TRV Setpoint"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
        }

    async def async_added_to_hass(self) -> None:
        self._coordinator.register_sensor_entity(self)

    @property
    def native_value(self) -> float | None:
        return self._coordinator.last_applied_setpoint
