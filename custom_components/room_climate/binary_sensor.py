"""Binary sensor for window-blocked state."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
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
    if coordinator.window_sensor:
        async_add_entities([RoomClimateWindowBlocked(coordinator, entry)])


class RoomClimateWindowBlocked(BinarySensorEntity):
    """
    Binary sensor that is ON when the window is open and climate is blocked.

    Turns ON immediately when the window opens (before the debounce expires),
    and turns OFF only after the close delay has passed and state is restored.
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(
        self, coordinator: RoomClimateCoordinator, entry: ConfigEntry
    ) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_window_blocked"
        self._attr_name = "Window Blocked"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Room Climate",
            "model": "Virtual Climate Controller",
        }

    async def async_added_to_hass(self) -> None:
        self._coordinator.register_window_sensor_entity(self)

    @property
    def is_on(self) -> bool:
        return self._coordinator.window_blocked
