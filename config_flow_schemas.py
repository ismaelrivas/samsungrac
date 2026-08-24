# pylint: disable=too-few-public-methods,line-too-long,consider-using-in
# custom_components/climate_ip/config_flow_schemas.py
"""Schema definitions for Climate IP config flow."""

from __future__ import annotations

import datetime
import logging
from typing import Any

from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_TOKEN,
    UnitOfTemperature,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .const import (
    CONF_CERT,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_ENABLE_POLLING,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    DEFAULT_CONF_CERT_FILE,
    DEFAULT_CONF_TEMP_UNIT,
    DEFAULT_ENABLE_POLLING,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SMARTTHINGS_HOST,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
)

_LOGGER = logging.getLogger(__name__)


class ConfigFlowSchemasMixin:
    """Mixin containing schema generation logic for Climate IP config flow."""

    flow_data: dict[str, Any]
    hass: Any

    def _get_base_samsung_schema(self, mac_required: bool, is_8888: bool) -> vol.Schema:
        """Helper to generate the shared configuration schema for all Samsung devices."""
        if not isinstance(mac_required, bool):
            raise TypeError(
                f"mac_required must be a strict bool, got {type(mac_required)}"
            )  # pragma: no mutate
        raw_mac = str(self.flow_data.get(CONF_MAC) or "")
        formatted_mac = dr.format_mac(raw_mac).upper() if raw_mac else ""

        try:
            val = self.flow_data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            interval_str = str(datetime.timedelta(seconds=int(val)))
        except (ValueError, TypeError):
            raw_interval = self.flow_data.get(CONF_POLL_INTERVAL)
            interval_str = str(raw_interval) if raw_interval is not None else ""

        # Strict dictionary composition
        schema_dict: dict[vol.Marker, Any] = {}

        schema_dict[
            vol.Required(
                CONF_IP_ADDRESS,
                default=str(
                    self.flow_data.get(CONF_IP_ADDRESS, "")
                ),  # pragma: no mutate
            )
        ] = str

        if mac_required:
            schema_dict[vol.Required(CONF_MAC, default=formatted_mac)] = (
                str  # pragma: no mutate
            )
        else:
            schema_dict[vol.Optional(CONF_MAC, default=formatted_mac)] = (
                str  # pragma: no mutate
            )

        schema_dict[
            vol.Optional(
                CONF_NAME, default=str(self.flow_data.get(CONF_NAME, ""))
            )  # pragma: no mutate
        ] = str  # pragma: no mutate
        schema_dict[
            vol.Optional(
                CONF_TOKEN, default=str(self.flow_data.get(CONF_TOKEN, ""))
            )  # pragma: no mutate
        ] = str

        cert_default = DEFAULT_CONF_CERT_FILE
        schema_dict[
            vol.Optional(
                CONF_CERT,
                default=str(
                    self.flow_data.get(CONF_CERT, cert_default)
                ),  # pragma: no mutate
            )
        ] = str

        schema_dict[vol.Optional(CONF_POLL_INTERVAL, default=interval_str)] = (
            TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
        )

        if not is_8888:
            schema_dict[
                vol.Optional(
                    CONF_ENABLE_POLLING,
                    default=bool(
                        self.flow_data.get(CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING)
                    ),
                )
            ] = bool

        temp_selector = SelectSelector(
            SelectSelectorConfig(
                options=[UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
        schema_dict[
            vol.Optional(
                CONF_TEMP_NATIVE_CURRENT,
                default=self.flow_data.get(
                    CONF_TEMP_NATIVE_CURRENT, DEFAULT_CONF_TEMP_UNIT
                ),  # pragma: no mutate
            )
        ] = temp_selector

        schema_dict[
            vol.Optional(
                CONF_TEMP_NATIVE_TARGET,
                default=self.flow_data.get(
                    CONF_TEMP_NATIVE_TARGET, DEFAULT_CONF_TEMP_UNIT
                ),
            )
        ] = temp_selector

        return vol.Schema(schema_dict)

    def _get_samsung_2878_schema(self, mac_required: bool) -> vol.Schema:
        """Return schema for older Samsung units."""
        is_8888 = False
        return self._get_base_samsung_schema(mac_required, is_8888)

    def _get_samsung_8888_schema(self, mac_required: bool) -> vol.Schema:
        """Return schema for modern Samsung units."""
        is_8888 = True
        return self._get_base_samsung_schema(mac_required, is_8888)

    def _get_smartthings_token(self) -> str | None:
        """Attempt to automatically retrieve the token from the official SmartThings integration."""
        st_entries = self.hass.config_entries.async_entries("smartthings")
        if st_entries:
            # fmt: off
            _LOGGER.debug('Found official SmartThings config entry. Auto-filling access token.')  # pragma: no mutate
            # fmt: on
            tok = st_entries[0].data.get("access_token")
            return str(tok) if tok is not None else ""
        return None

    def _get_rest_api_schema(self) -> vol.Schema:
        """Generate the schema for REST API based devices that require manual token."""
        device_type = self.flow_data[CONF_DEVICE_TYPE]
        is_st = device_type in (
            DEVICE_TYPE_SMARTTHINGS_HVAC,
            DEVICE_TYPE_SMARTTHINGS_DHW,
        )

        try:
            val = self.flow_data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            interval_str = str(datetime.timedelta(seconds=int(val)))
        except (ValueError, TypeError):
            raw_interval = self.flow_data.get(CONF_POLL_INTERVAL)
            interval_str = str(raw_interval) if raw_interval is not None else ""

        token_from_data = self.flow_data.get(CONF_TOKEN)
        if token_from_data:
            default_token = str(token_from_data)
        elif is_st:
            st_token = self._get_smartthings_token()
            default_token = st_token if st_token is not None else ""
        else:
            default_token = ""

        schema_dict: dict[vol.Marker, Any] = {}

        ip_default = (
            self.flow_data.get(
                CONF_IP_ADDRESS, DEFAULT_SMARTTHINGS_HOST if is_st else ""
            )
            or ""
        )

        # PROTECTED ZONE: Voluptuous crashes the core C validator if keys/values are mutated to None
        if is_st:
            schema_dict[vol.Required(CONF_IP_ADDRESS, default=ip_default)] = (
                str  # pragma: no mutate
            )
            schema_dict[vol.Optional(CONF_DEVICE_ID)] = str  # pragma: no mutate
        elif ip_default:
            schema_dict[vol.Required(CONF_IP_ADDRESS, default=ip_default)] = (
                str  # pragma: no mutate
            )
        else:
            schema_dict[vol.Required(CONF_IP_ADDRESS)] = str  # pragma: no mutate

        schema_dict[vol.Required(CONF_TOKEN, default=default_token)] = (
            str  # pragma: no mutate
        )
        schema_dict[vol.Optional(CONF_NAME)] = str  # pragma: no mutate
        schema_dict[vol.Optional(CONF_POLL_INTERVAL, default=interval_str)] = (
            TextSelector(  # pragma: no mutate
                TextSelectorConfig(type=TextSelectorType.TEXT)
            )
        )

        return vol.Schema(schema_dict)
