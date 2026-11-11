# pylint: disable=too-few-public-methods,line-too-long,consider-using-in
# custom_components/climate_ip/config_flow_schemas.py
"""Schema definitions for Climate IP config flow."""

import logging
from typing import TYPE_CHECKING, Any, cast

import probatio

from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN, UnitOfTemperature
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_CERT,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_ENABLE_POLLING,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_SELECTED_DEVICES,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    DEFAULT_CONF_CERT_FILE,
    DEFAULT_CONF_TEMP_UNIT,
    DEFAULT_ENABLE_POLLING,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SMARTTHINGS_HOST,
    DEVICE_TYPE_8888_GROUP,
    DEVICE_TYPE_INTESISBOX,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DEVICE_TYPES,
)
from .helpers import format_poll_interval

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlow

    _FlowMixinBase = ConfigFlow
else:
    _FlowMixinBase = object


class ConfigFlowSchemasMixin(_FlowMixinBase):
    """Mixin containing schema generation logic for Climate IP config flow."""

    flow_data: dict[str, Any]
    hass: Any
    _device_type: str | None
    _discovered_devices: dict[str, dict[str, Any]]
    _last_user_input: dict[str, Any]
    add_suggested_values_to_schema: Any

    def _default_poll_interval_seconds(self) -> int:
        """Return the default poll interval in seconds."""
        return DEFAULT_POLL_INTERVAL

    def _get_base_samsung_schema(
        self, mac_required: bool, is_8888: bool
    ) -> probatio.Schema:
        """Helper to generate the shared configuration schema for all Samsung devices."""
        if not isinstance(mac_required, bool):
            raise TypeError(
                f"mac_required must be a strict bool, got {type(mac_required)}"
            )  # pragma: no mutate
        raw_mac = str(self.flow_data.get(CONF_MAC) or "")
        formatted_mac = dr.format_mac(raw_mac).upper() if raw_mac else ""

        if (
            CONF_POLL_INTERVAL in self.flow_data
            and self.flow_data[CONF_POLL_INTERVAL] is None
        ):
            interval_str = ""
        else:
            def_poll_raw = self.flow_data.get(CONF_POLL_INTERVAL)
            interval_str = format_poll_interval(
                def_poll_raw, self._default_poll_interval_seconds()
            )

        # Strict dictionary composition
        schema_dict: dict[probatio.Marker, Any] = {}

        schema_dict[
            probatio.Required(
                CONF_IP_ADDRESS,
                default=str(
                    self.flow_data.get(CONF_IP_ADDRESS, "")
                ),  # pragma: no mutate
            )
        ] = str

        if mac_required:
            schema_dict[probatio.Required(CONF_MAC, default=formatted_mac)] = (
                str  # pragma: no mutate
            )
        else:
            schema_dict[probatio.Optional(CONF_MAC, default=formatted_mac)] = (
                str  # pragma: no mutate
            )

        schema_dict[
            probatio.Optional(
                CONF_NAME, default=str(self.flow_data.get(CONF_NAME, ""))
            )  # pragma: no mutate
        ] = str  # pragma: no mutate
        schema_dict[
            probatio.Optional(
                probatio.Secret(CONF_TOKEN),
                default=str(self.flow_data.get(CONF_TOKEN, "")),
            )  # pragma: no mutate
        ] = str

        cert_default = DEFAULT_CONF_CERT_FILE
        schema_dict[
            probatio.Optional(
                CONF_CERT,
                default=str(
                    self.flow_data.get(CONF_CERT, cert_default)
                ),  # pragma: no mutate
            )
        ] = str

        schema_dict[probatio.Optional(CONF_POLL_INTERVAL, default=interval_str)] = (
            TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
        )

        if not is_8888:
            schema_dict[
                probatio.Optional(
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
            probatio.Optional(
                CONF_TEMP_NATIVE_CURRENT,
                default=self.flow_data.get(
                    CONF_TEMP_NATIVE_CURRENT, DEFAULT_CONF_TEMP_UNIT
                ),  # pragma: no mutate
            )
        ] = temp_selector

        schema_dict[
            probatio.Optional(
                CONF_TEMP_NATIVE_TARGET,
                default=self.flow_data.get(
                    CONF_TEMP_NATIVE_TARGET, DEFAULT_CONF_TEMP_UNIT
                ),
            )
        ] = temp_selector

        return probatio.Schema(schema_dict)

    def _get_samsung_2878_schema(self, mac_required: bool = False) -> probatio.Schema:
        """Return schema for older Samsung units."""
        is_8888 = False
        return self._get_base_samsung_schema(mac_required, is_8888)

    def _get_samsung_8888_schema(self, mac_required: bool = False) -> probatio.Schema:
        """Return schema for modern Samsung units."""
        is_8888 = True
        return self._get_base_samsung_schema(mac_required, is_8888)

    def _get_smartthings_token(self) -> str | None:
        """Attempt to automatically retrieve the token from the official SmartThings integration."""
        st_entries = self.hass.config_entries.async_entries("smartthings")
        if st_entries:
            # fmt: off
            _LOGGER.debug('Found official SmartThings config entry. Auto-filling access token')  # pragma: no mutate
            # fmt: on
            tok = st_entries[0].data.get("access_token")
            return str(tok) if tok is not None else ""
        return None

    def _get_rest_api_schema(self) -> probatio.Schema:
        """Generate the schema for REST API based devices that require manual token."""
        device_type = self.flow_data[CONF_DEVICE_TYPE]
        is_st = device_type in (
            DEVICE_TYPE_SMARTTHINGS_HVAC,
            DEVICE_TYPE_SMARTTHINGS_DHW,
        )

        if (
            CONF_POLL_INTERVAL in self.flow_data
            and self.flow_data[CONF_POLL_INTERVAL] is None
        ):
            interval_str = ""
        else:
            def_poll_raw = self.flow_data.get(CONF_POLL_INTERVAL)
            interval_str = format_poll_interval(
                def_poll_raw, self._default_poll_interval_seconds()
            )

        token_from_data = self.flow_data.get(CONF_TOKEN)
        if token_from_data:
            default_token = str(token_from_data)
        elif is_st:
            st_token = self._get_smartthings_token()
            default_token = st_token if st_token is not None else ""
        else:
            default_token = ""

        schema_dict: dict[probatio.Marker, Any] = {}

        ip_default = (
            self.flow_data.get(
                CONF_IP_ADDRESS, DEFAULT_SMARTTHINGS_HOST if is_st else ""
            )
            or ""
        )

        # PROTECTED ZONE: Probatio schema key composition
        if is_st:
            schema_dict[probatio.Required(CONF_IP_ADDRESS, default=ip_default)] = (
                str  # pragma: no mutate
            )
            schema_dict[probatio.Optional(CONF_DEVICE_ID)] = str  # pragma: no mutate
        elif ip_default:
            schema_dict[probatio.Required(CONF_IP_ADDRESS, default=ip_default)] = (
                str  # pragma: no mutate
            )
        else:
            schema_dict[probatio.Required(CONF_IP_ADDRESS)] = str  # pragma: no mutate

        schema_dict[
            probatio.Required(probatio.Secret(CONF_TOKEN), default=default_token)
        ] = str  # pragma: no mutate
        schema_dict[probatio.Optional(CONF_NAME)] = str  # pragma: no mutate
        schema_dict[probatio.Optional(CONF_POLL_INTERVAL, default=interval_str)] = (
            TextSelector(  # pragma: no mutate
                TextSelectorConfig(type=TextSelectorType.TEXT)
            )
        )

        return probatio.Schema(schema_dict)

    def _get_user_schema(self) -> probatio.Schema:
        """Build schema for the initial user device-type selection step."""
        return probatio.Schema(
            {
                probatio.Required(CONF_DEVICE_TYPE): SelectSelector(
                    SelectSelectorConfig(
                        options=DEVICE_TYPES,
                        translation_key=CONF_DEVICE_TYPE,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

    def _get_intesisbox_schema(self) -> probatio.Schema:
        """Build schema for IntesisBox configuration."""
        data_source = {
            **getattr(self, "flow_data", {}),
            **getattr(self, "_last_user_input", {}),
        }
        def_ip = data_source.get(CONF_IP_ADDRESS, "")
        def_mac = data_source.get(CONF_MAC, "")
        return probatio.Schema(
            {
                probatio.Required(CONF_IP_ADDRESS, default=def_ip): str,
                probatio.Optional(
                    CONF_MAC,
                    description={"suggested_value": def_mac},
                ): str,
                probatio.Optional(CONF_POLL_INTERVAL, default=60): int,
            }
        )

    def _get_reconfigure_schema(
        self, suggested_values: dict[str, Any] | None = None
    ) -> probatio.Schema:
        """Build schema for the reconfigure confirmation step."""
        base_schema = probatio.Schema(
            {
                probatio.Required(CONF_IP_ADDRESS): str,
                probatio.Optional(CONF_MAC): str,
                probatio.Optional(probatio.Secret(CONF_TOKEN)): str,
                probatio.Optional(CONF_CERT): str,
            }
        )
        if suggested_values is not None:
            add_suggested = getattr(self, "add_suggested_values_to_schema", None)
            if callable(add_suggested):
                return cast(
                    probatio.Schema, add_suggested(base_schema, suggested_values)
                )
        return base_schema

    def _get_select_devices_schema(
        self,
        device_options: dict[str, str],
        default_keys: list[str] | None = None,
    ) -> probatio.Schema:
        """Build schema for multi-device selection step."""
        if default_keys is None:
            last_input = getattr(self, "_last_user_input", None) or {}
            if CONF_SELECTED_DEVICES in last_input:
                default_keys = last_input[CONF_SELECTED_DEVICES]
            elif hasattr(self, "_discovered_devices") and isinstance(
                self._discovered_devices, dict
            ):
                default_keys = list(self._discovered_devices.keys())
            else:
                default_keys = list(device_options.keys())
        return probatio.Schema(
            {
                probatio.Required(
                    CONF_SELECTED_DEVICES, default=default_keys
                ): cv.multi_select(device_options),
            }
        )

    def build_device_config_schema(
        self,
        device_type: str | None = None,
        *,
        mac_required: bool = False,
        is_reconfigure: bool = False,
        suggested_values: dict[str, Any] | None = None,
    ) -> probatio.Schema:
        """Build a dynamic device configuration schema based on device family and flow context."""
        if is_reconfigure:
            return self._get_reconfigure_schema(suggested_values)
        target_type = (
            device_type
            or getattr(self, "_device_type", None)
            or self.flow_data.get(CONF_DEVICE_TYPE)
        )
        if target_type == DEVICE_TYPE_SAMSUNG_2878:
            return self._get_samsung_2878_schema(mac_required=mac_required)
        if target_type in DEVICE_TYPE_8888_GROUP:
            return self._get_samsung_8888_schema(mac_required=mac_required)
        if target_type == DEVICE_TYPE_INTESISBOX:
            return self._get_intesisbox_schema()
        if target_type and CONF_DEVICE_TYPE not in self.flow_data:
            self.flow_data[CONF_DEVICE_TYPE] = target_type
        return self._get_rest_api_schema()

    def _async_show_reconfigure_form(
        self,
        errors: dict[str, str],
        suggested_values: dict[str, Any],
        description_placeholders: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Build and return the reconfigure_confirm form with the given suggested values."""
        return self.async_show_form(
            step_id="reconfigure_confirm",
            data_schema=self._get_reconfigure_schema(suggested_values),
            errors=errors,
            description_placeholders=description_placeholders or {},
        )

    def _current_reconfigure_suggested(self) -> dict[str, Any]:
        """Return suggested-values dict built from the current flow_data."""
        raw_mac = str(self.flow_data.get(CONF_MAC) or "")
        return {
            CONF_IP_ADDRESS: self.flow_data.get(CONF_IP_ADDRESS) or "",
            CONF_MAC: dr.format_mac(raw_mac).upper() if raw_mac else "",
            CONF_TOKEN: str(self.flow_data.get(CONF_TOKEN) or ""),
            CONF_CERT: str(self.flow_data.get(CONF_CERT) or ""),
        }

    def _get_initial_reconfigure_suggested(self) -> dict[str, Any]:
        """Return initial suggested-values dict with Samsung certificate hardening."""
        suggested = self._current_reconfigure_suggested()
        cert_def = str(suggested[CONF_CERT]).strip()
        if not cert_def:
            device_type = self.flow_data.get(CONF_DEVICE_TYPE)
            is_samsung = device_type in (
                *DEVICE_TYPE_8888_GROUP,
                DEVICE_TYPE_MIM_H03,
                DEVICE_TYPE_SAMSUNG_2878,
            )
            cert_def = DEFAULT_CONF_CERT_FILE if is_samsung else ""
        suggested[CONF_CERT] = cert_def
        return suggested
