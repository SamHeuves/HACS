"""Config flow for Room Climate integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CALIBRATION_MODES,
    CALIBRATION_NORMAL,
    CONF_AC_ENTITY,
    CONF_ADDITIONAL_TRVS,
    CONF_AWAY_TEMP,
    CONF_CALIBRATION_MODE,
    CONF_ECO_TEMP_OFFSET,
    CONF_TADO_ENTITY,
    CONF_TEMP_SENSOR,
    CONF_WINDOW_CLOSE_DELAY,
    CONF_WINDOW_OPEN_DELAY,
    CONF_WINDOW_SENSOR,
    DEFAULT_AWAY_TEMP,
    DEFAULT_ECO_OFFSET,
    DEFAULT_WINDOW_CLOSE_DELAY,
    DEFAULT_WINDOW_OPEN_DELAY,
    DOMAIN,
)


class RoomClimateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Room Climate."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}

    # Step 1: Room name + primary TRV
    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_TADO_ENTITY])
            self._abort_if_unique_id_configured()
            self._data.update(user_input)
            return await self.async_step_optional_devices()

        schema = vol.Schema(
            {
                vol.Required("name"): selector.TextSelector(),
                vol.Required(CONF_TADO_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=CLIMATE_DOMAIN)
                ),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    # Step 2: Optional AC, temp sensor, additional TRVs
    async def async_step_optional_devices(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_window()

        schema = vol.Schema(
            {
                vol.Optional(CONF_AC_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=CLIMATE_DOMAIN)
                ),
                vol.Optional(CONF_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        device_class=SensorDeviceClass.TEMPERATURE
                    )
                ),
                vol.Optional(CONF_ADDITIONAL_TRVS): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=CLIMATE_DOMAIN, multiple=True
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="optional_devices", data_schema=schema
        )

    # Step 3: Window sensor + delays
    async def async_step_window(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            if self._data.get(CONF_TEMP_SENSOR):
                return await self.async_step_calibration()
            return await self.async_step_presets()

        schema = vol.Schema(
            {
                vol.Optional(CONF_WINDOW_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        device_class=BinarySensorDeviceClass.WINDOW
                    )
                ),
                vol.Optional(
                    CONF_WINDOW_OPEN_DELAY, default=DEFAULT_WINDOW_OPEN_DELAY
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=300, step=1,
                        unit_of_measurement="s", mode="box",
                    )
                ),
                vol.Optional(
                    CONF_WINDOW_CLOSE_DELAY, default=DEFAULT_WINDOW_CLOSE_DELAY
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=300, step=1,
                        unit_of_measurement="s", mode="box",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="window", data_schema=schema)

    # Step 4: Calibration (only when temp sensor selected)
    async def async_step_calibration(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_presets()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CALIBRATION_MODE, default=CALIBRATION_NORMAL
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=CALIBRATION_MODES,
                        translation_key="calibration_mode",
                        mode="list",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="calibration", data_schema=schema)

    # Step 5: Presets (eco offset + away temp)
    async def async_step_presets(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return self._create_entry()

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ECO_TEMP_OFFSET, default=DEFAULT_ECO_OFFSET
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=10, step=0.5,
                        unit_of_measurement="°C", mode="slider",
                    )
                ),
                vol.Optional(
                    CONF_AWAY_TEMP, default=DEFAULT_AWAY_TEMP
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=20, step=0.5,
                        unit_of_measurement="°C", mode="slider",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="presets", data_schema=schema)

    def _create_entry(self):
        return self.async_create_entry(
            title=self._data.get("name", "Room Climate"),
            data=self._data,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return RoomClimateOptionsFlow()


# ======================================================================
# Options Flow (reconfigure an existing room)
# ======================================================================


class RoomClimateOptionsFlow(config_entries.OptionsFlow):
    """Handle options (re-configure an existing room)."""

    def __init__(self) -> None:
        self._data: dict = {}

    async def async_step_init(self, user_input=None):
        self._data = {**self.config_entry.data, **self.config_entry.options}
        return await self.async_step_optional_devices()

    async def async_step_optional_devices(self, user_input=None):
        if user_input is not None:
            self._data[CONF_AC_ENTITY] = user_input.get(CONF_AC_ENTITY)
            self._data[CONF_TEMP_SENSOR] = user_input.get(CONF_TEMP_SENSOR)
            self._data[CONF_ADDITIONAL_TRVS] = (
                user_input.get(CONF_ADDITIONAL_TRVS) or []
            )
            return await self.async_step_window()

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_AC_ENTITY,
                    description={
                        "suggested_value": self._data.get(CONF_AC_ENTITY)
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=CLIMATE_DOMAIN)
                ),
                vol.Optional(
                    CONF_TEMP_SENSOR,
                    description={
                        "suggested_value": self._data.get(CONF_TEMP_SENSOR)
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        device_class=SensorDeviceClass.TEMPERATURE
                    )
                ),
                vol.Optional(
                    CONF_ADDITIONAL_TRVS,
                    description={
                        "suggested_value": self._data.get(CONF_ADDITIONAL_TRVS)
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=CLIMATE_DOMAIN, multiple=True
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="optional_devices", data_schema=schema
        )

    async def async_step_window(self, user_input=None):
        if user_input is not None:
            self._data[CONF_WINDOW_SENSOR] = user_input.get(CONF_WINDOW_SENSOR)
            self._data[CONF_WINDOW_OPEN_DELAY] = user_input.get(
                CONF_WINDOW_OPEN_DELAY, DEFAULT_WINDOW_OPEN_DELAY
            )
            self._data[CONF_WINDOW_CLOSE_DELAY] = user_input.get(
                CONF_WINDOW_CLOSE_DELAY, DEFAULT_WINDOW_CLOSE_DELAY
            )
            if self._data.get(CONF_TEMP_SENSOR):
                return await self.async_step_calibration()
            return await self.async_step_presets()

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_WINDOW_SENSOR,
                    description={
                        "suggested_value": self._data.get(CONF_WINDOW_SENSOR)
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        device_class=BinarySensorDeviceClass.WINDOW
                    )
                ),
                vol.Optional(
                    CONF_WINDOW_OPEN_DELAY,
                    default=self._data.get(
                        CONF_WINDOW_OPEN_DELAY, DEFAULT_WINDOW_OPEN_DELAY
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=300, step=1,
                        unit_of_measurement="s", mode="box",
                    )
                ),
                vol.Optional(
                    CONF_WINDOW_CLOSE_DELAY,
                    default=self._data.get(
                        CONF_WINDOW_CLOSE_DELAY, DEFAULT_WINDOW_CLOSE_DELAY
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=300, step=1,
                        unit_of_measurement="s", mode="box",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="window", data_schema=schema)

    async def async_step_calibration(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_presets()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CALIBRATION_MODE,
                    default=self._data.get(
                        CONF_CALIBRATION_MODE, CALIBRATION_NORMAL
                    ),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=CALIBRATION_MODES,
                        translation_key="calibration_mode",
                        mode="list",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="calibration", data_schema=schema)

    async def async_step_presets(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="", data=self._data)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ECO_TEMP_OFFSET,
                    default=self._data.get(
                        CONF_ECO_TEMP_OFFSET, DEFAULT_ECO_OFFSET
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=10, step=0.5,
                        unit_of_measurement="°C", mode="slider",
                    )
                ),
                vol.Optional(
                    CONF_AWAY_TEMP,
                    default=self._data.get(CONF_AWAY_TEMP, DEFAULT_AWAY_TEMP),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=20, step=0.5,
                        unit_of_measurement="°C", mode="slider",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="presets", data_schema=schema)
