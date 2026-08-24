# custom_components/climate_ip/options_flow.py
"""Options flow handler for Climate IP."""

from __future__ import annotations

import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .const import (
    CONF_CONN_METHOD,
    CONF_DEVICE_TYPE,
    CONF_ENABLE_POLLING,
    CONF_POLL_INTERVAL,
    CONF_TARGET_TEMP_STEP,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    CONN_METHOD_AIOHTTP,
    CONN_METHOD_RAW,
    CONN_METHOD_REQUESTS,
    DEFAULT_CONF_TEMP_UNIT,
    DEFAULT_ENABLE_POLLING,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TARGET_TEMP_STEP,
    DEVICE_TYPE_AIOHTTP_SUPPORTED,
)
from .helpers import validate_poll_interval


class OptionsFlowHandler(OptionsFlow):
    """Handle options flow for Climate IP."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        schema = self._get_options_schema()

        if user_input is not None:
            if (
                CONF_POLL_INTERVAL in user_input
                and user_input[CONF_POLL_INTERVAL] is not None
            ):
                try:
                    seconds = validate_poll_interval(user_input[CONF_POLL_INTERVAL])
                    user_input[CONF_POLL_INTERVAL] = seconds
                except ValueError:
                    errors[CONF_POLL_INTERVAL] = "invalid_poll_interval"
                    return self.async_show_form(
                        step_id="init",
                        data_schema=schema,
                        errors=errors,
                    )

            if CONF_TARGET_TEMP_STEP in user_input:
                try:
                    user_input[CONF_TARGET_TEMP_STEP] = float(
                        user_input[CONF_TARGET_TEMP_STEP]
                    )
                except (ValueError, TypeError):
                    user_input[CONF_TARGET_TEMP_STEP] = DEFAULT_TARGET_TEMP_STEP

            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(step_id="init", data_schema=schema)

    def _get_options_schema(self) -> vol.Schema:
        """Return the schema for the options flow."""
        schema_dict: dict[vol.Marker, Any] = {}
        data = self._config_entry.data
        options = self._config_entry.options

        if data.get(CONF_DEVICE_TYPE) in DEVICE_TYPE_AIOHTTP_SUPPORTED:
            opt_conn = options.get(
                CONF_CONN_METHOD, data.get(CONF_CONN_METHOD, CONN_METHOD_AIOHTTP)
            )  # pragma: no mutate

            schema_dict[vol.Required(CONF_CONN_METHOD, default=opt_conn)] = (
                SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(
                                value=CONN_METHOD_REQUESTS,
                                label="Legacy (Obsolete)",
                            ),
                            SelectOptionDict(
                                value=CONN_METHOD_AIOHTTP,
                                label="Modern (aiohttp)",
                            ),
                            SelectOptionDict(
                                value=CONN_METHOD_RAW,
                                label="Robust (raw socket)",
                            ),
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="connection_method",
                    )
                )
            )

        opt_poll = options.get(
            CONF_POLL_INTERVAL, data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        )  # pragma: no mutate

        try:
            current_str = str(datetime.timedelta(seconds=int(opt_poll)))
        except (ValueError, TypeError):
            current_str = str(opt_poll)

        temp_selector = SelectSelector(
            SelectSelectorConfig(
                options=[UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )

        opt_curr = options.get(
            CONF_TEMP_NATIVE_CURRENT, DEFAULT_CONF_TEMP_UNIT
        )  # pragma: no mutate
        opt_targ = options.get(
            CONF_TEMP_NATIVE_TARGET, DEFAULT_CONF_TEMP_UNIT
        )  # pragma: no mutate
        opt_polling = options.get(
            CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING
        )  # pragma: no mutate

        opt_step = (
            options.get(CONF_TARGET_TEMP_STEP)
            or data.get(CONF_TARGET_TEMP_STEP)
            or DEFAULT_TARGET_TEMP_STEP
        )  # pragma: no mutate

        schema_dict |= {
            vol.Required(CONF_POLL_INTERVAL, default=current_str): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
            vol.Required(CONF_TEMP_NATIVE_CURRENT, default=opt_curr): temp_selector,
            vol.Required(CONF_TEMP_NATIVE_TARGET, default=opt_targ): temp_selector,
            vol.Optional(CONF_ENABLE_POLLING, default=bool(opt_polling)): bool,
            vol.Optional(CONF_TARGET_TEMP_STEP, default=str(opt_step)): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value="0.1", label="0.1°"),
                        SelectOptionDict(value="0.5", label="0.5°"),
                        SelectOptionDict(value="1.0", label="1.0°"),
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }

        return vol.Schema(schema_dict)
