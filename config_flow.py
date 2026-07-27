# pylint: disable=broad-exception-caught,import-outside-toplevel,unused-argument
# custom_components/climate_ip/config_flow.py
# pylint: disable=too-many-lines
"""Config flow for the Climate IP integration."""

import asyncio
import datetime
import logging
import os
from pathlib import Path
import ssl
from typing import Any, Self

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
    SOURCE_RECONFIGURE,
)
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_TOKEN,
    UnitOfTemperature,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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
    CONF_CONFIG_FILE,
    CONF_CONN_METHOD,
    CONF_DEVICE_ID,
    CONF_TARGET_TEMP_STEP,
    CONF_DEVICE_TYPE,
    CONF_DEVICES,
    CONF_DISCOVERED_DEVICES,
    CONF_ENABLE_POLLING,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_SELECTED_DEVICES,
    CONF_TEMP_NATIVE_CURRENT,
    CONF_TEMP_NATIVE_TARGET,
    CONFIG_DEVICE_NAME,
    CONFIG_FILE_TO_DEVICE_TYPE,
    CONN_METHOD_AIOHTTP,
    CONN_METHOD_RAW,
    CONN_METHOD_REQUESTS,
    DEFAULT_CONF_CERT_FILE,
    DEFAULT_CONF_TEMP_UNIT,
    DEFAULT_ENABLE_POLLING,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TARGET_TEMP_STEP,
    DEVICE_TYPE_8888_GROUP,
    DEVICE_TYPE_AIOHTTP_SUPPORTED,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DEVICE_TYPE_TO_CONFIG_FILE,
    DOMAIN,
    GLOBAL_HTTP_TIMEOUT,
    PORT_SAMSUNG_2878,
    PORT_SAMSUNG_8888,
)
from .controller_yaml import YamlController
from .exceptions import (
    AuthError,
    AuthTurnedOffError,
    CannotConnect,
    InvalidHeaderError,
    TokenAcquisitionError,
)
from .helpers import (
    async_get_mac_address,
    sanitize_token,
    resolve_cert_path,
    validate_poll_interval,
)
from .token_acquirer import SamsungTokenAcquirer
from .token_acquirer_8888 import SamsungTokenAcquirer8888

_LOGGER = logging.getLogger(__name__)


class ClimateIpConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """
    Config flow implementing a robust, multi-step pairing process.
    Supports legacy Samsung ACs (2878), modern units (8888),
    MIM-H03 heatpumps and SmartThings cloud devices.
    """

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow variables."""
        self.flow_data: dict[str, Any] = {}
        self.task: asyncio.Task | None = None
        self.acquirer: Any | None = None
        self.reauth_entry: ConfigEntry | None = None

        _LOGGER.debug(
            "Initializing new Climate IP config flow handler."
        )  # pragma: no mutate

    def is_matching(self, other_flow: Self) -> bool:
        """Return True if other_flow matches this flow (same physical device)."""
        self_ip = self.context.get(CONF_IP_ADDRESS) or self.flow_data.get(
            CONF_IP_ADDRESS
        )
        other_ip = other_flow.context.get(CONF_IP_ADDRESS) or other_flow.flow_data.get(
            CONF_IP_ADDRESS
        )

        if self_ip and other_ip and self_ip == other_ip:
            return True

        self_mac = self.context.get(CONF_MAC) or self.flow_data.get(CONF_MAC)
        other_mac = other_flow.context.get(CONF_MAC) or other_flow.flow_data.get(
            CONF_MAC
        )

        if self_mac and other_mac and self_mac.upper() == other_mac.upper():
            return True

        return False

    async def async_step_import(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        """Handle the import of a YAML configuration (legacy platform)."""
        _LOGGER.debug(
            "Starting YAML import for: %s", user_input.get(CONF_IP_ADDRESS)
        )  # pragma: no mutate

        mac_address = user_input.get(CONF_MAC)
        if mac_address is not None:
            user_input[CONF_MAC] = str(mac_address).replace(":", "").upper()

        unique_id = user_input.get(CONF_MAC)
        if not unique_id:
            _LOGGER.error(
                "YAML import failed: No MAC address provided."
            )  # pragma: no mutate
            return self.async_abort(reason="no_mac_address_found")

        await self.async_set_unique_id(str(unique_id))
        self._abort_if_unique_id_configured()

        config_file = user_input.get(CONF_CONFIG_FILE)
        if config_file is not None:
            if config_file in CONFIG_FILE_TO_DEVICE_TYPE:
                user_input[CONF_DEVICE_TYPE] = CONFIG_FILE_TO_DEVICE_TYPE[config_file]
                # fmt: off
                _LOGGER.debug("Inferred device_type '%s' from config_file '%s'", user_input[CONF_DEVICE_TYPE], config_file)  # pragma: no mutate
                # fmt: on

        device_name = str(user_input.get(CONFIG_DEVICE_NAME, f"Climate {unique_id}"))

        self.flow_data.update(user_input)
        if CONF_DEVICE_TYPE in self.flow_data:
            test_result = await self._test_connection_safe()
            if not test_result.get("ok"):
                _LOGGER.error(
                    "YAML import failed: Could not connect to device."
                )  # pragma: no mutate
                return self.async_abort(reason="cannot_connect")

        _LOGGER.info(
            "Creating new entry for '%s' from imported YAML.", device_name
        )  # pragma: no mutate
        return self.async_create_entry(title=device_name, data=user_input)

    @callback
    def async_remove(self) -> None:
        """Clean up background tasks if the user cancels the flow."""
        _LOGGER.debug("Config flow cancelled. Cleaning up tasks.")  # pragma: no mutate
        if self.task is not None:
            self.task.cancel()
        if self.acquirer is not None:
            self.hass.async_create_task(self.acquirer.async_close())

    async def _async_force_arp_update(self, ip_address: str) -> None:
        """Force the OS to resolve the MAC and populate the ARP table concurrently."""

        async def _poke_port(port: int) -> None:
            """Attempt to open a raw connection to force a SYN packet emission."""
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip_address, port),
                    timeout=0.5,  # pragma: no mutate
                )
                writer.close()
                await writer.wait_closed()
            except (OSError, asyncio.TimeoutError):
                pass

        await asyncio.gather(
            _poke_port(PORT_SAMSUNG_2878), _poke_port(PORT_SAMSUNG_8888)
        )

    async def _async_resolve_mac_and_set_unique_id(
        self, ip_address: str, mac_address: str | None
    ) -> str | None:
        """Resolve MAC address using getmac library or user input."""
        if mac_address:
            self.flow_data[CONF_MAC] = (
                dr.format_mac(mac_address).replace(":", "").upper()
            )
        else:
            _LOGGER.debug(
                "MAC not provided, attempting discovery for %s", ip_address
            )  # pragma: no mutate

            discovered_mac = await async_get_mac_address(ip_address)

            if discovered_mac is None:
                await self._async_force_arp_update(ip_address)
                discovered_mac = await async_get_mac_address(ip_address)

            if discovered_mac is not None:
                formatted_mac = dr.format_mac(discovered_mac)
                _LOGGER.info(
                    "MAC discovered via ARP: %s", formatted_mac
                )  # pragma: no mutate
                self.flow_data[CONF_MAC] = formatted_mac.replace(":", "").upper()
            else:
                _LOGGER.info(
                    "MAC auto-discovery failed. Requesting manual input."
                )  # pragma: no mutate
                return "mac_resolve_failed"

        await self.async_set_unique_id(str(self.flow_data[CONF_MAC]))
        if self.reauth_entry is None:
            if self.source != SOURCE_RECONFIGURE:
                self._abort_if_unique_id_configured()

        return None

    async def _async_validate_cert_path(self, user_cert_path: str | None) -> bool:
        """Validate if the certificate file exists on disk."""
        if not user_cert_path:
            return True

        path_to_check = resolve_cert_path(
            user_cert_path, str(Path(__file__).parent), self.hass
        )
        if path_to_check is None:
            return True

        exists: bool = await self.hass.async_add_executor_job(
            os.path.exists, path_to_check
        )
        return exists

    async def _initiate_pairing_safe(self) -> dict[str, Any]:
        """Async wrapper for the initiate_pairing phase with exception handling."""
        _LOGGER.debug(
            "Executing safe wrapper: _initiate_pairing_safe"
        )  # pragma: no mutate
        try:
            if self.acquirer is None:
                return {"ok": False, "error": "unknown_error"}

            successful_config = await self.acquirer.async_initiate_pairing()
            # fmt: off
            _LOGGER.debug('_initiate_pairing_safe successful with config: %s', successful_config)  # pragma: no mutate
            # fmt: on
            return {"ok": True, "config": successful_config}
        except CannotConnect as err:
            ip_address = str(self.flow_data.get(CONF_IP_ADDRESS, "Unknown"))  # pragma: no mutate
            _LOGGER.error(
                "Fatal pairing failure at %s. Details: %s", ip_address, err
            )  # pragma: no mutate
            return {
                "ok": False,
                "error": "pairing_connection_failed",
                "error_details": str(err),
            }
        except (AuthError, TokenAcquisitionError) as err:
            _LOGGER.warning(
                "Connection error during pairing initiation: %s", err
            )  # pragma: no mutate
            return {
                "ok": False,
                "error": "pairing_connection_failed",
                "error_details": str(err),
            }
        except TimeoutError as err:
            ip_address = str(self.flow_data.get(CONF_IP_ADDRESS, "Unknown"))  # pragma: no mutate
            _LOGGER.warning(
                "Timeout connecting to %s. Wrong IP?", ip_address
            )  # pragma: no mutate
            return {
                "ok": False,
                "error": "timeout_connect",
                "error_details": str(err),
            }
        except Exception as e:
            _LOGGER.error(
                "Unexpected error during pairing: %s", e, exc_info=True
            )  # pragma: no mutate
            return {"ok": False, "error": "unknown_error"}

    async def _wait_token_safe(self) -> dict[str, Any]:
        """Async wrapper for the token acquisition phase with exception handling."""
        _LOGGER.debug("Executing safe wrapper: _wait_token_safe")  # pragma: no mutate
        try:
            if self.acquirer is None:
                return {"ok": False, "error": "unknown_error"}

            token = await self.acquirer.async_wait_for_token()
            _LOGGER.debug(
                "_wait_token_safe successful, token acquired."
            )  # pragma: no mutate
            return {"ok": True, "token": token}
        except TimeoutError as err:
            ip_address = str(self.flow_data.get(CONF_IP_ADDRESS, "Unknown"))  # pragma: no mutate
            _LOGGER.warning(
                "Timeout connecting to %s. Wrong IP?", ip_address
            )  # pragma: no mutate
            return {
                "ok": False,
                "error": "timeout_connect",
                "error_details": str(err),
            }
        except (TokenAcquisitionError, AuthTurnedOffError) as e:
            _LOGGER.warning("Token acquisition failed: %s", e)  # pragma: no mutate
            return {"ok": False, "error": "token_acquisition_failed"}
        except Exception as e:
            _LOGGER.error(
                "Unknown error while waiting for token: %s", e, exc_info=True
            )  # pragma: no mutate
            return {"ok": False, "error": "unknown_error"}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: The user chooses the device type."""
        if user_input:
            device_type = str(user_input[CONF_DEVICE_TYPE])
            self.flow_data[CONF_DEVICE_TYPE] = device_type

            if device_type == DEVICE_TYPE_SAMSUNG_2878:
                return await self.async_step_samsung_2878()

            if device_type in DEVICE_TYPE_8888_GROUP:
                return await self.async_step_samsung_8888()

            if device_type in (
                DEVICE_TYPE_SMARTTHINGS_HVAC,
                DEVICE_TYPE_SMARTTHINGS_DHW,
            ):
                return await self.async_step_rest_api()

            return self.async_abort(reason="not_implemented")

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_TYPE): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            DEVICE_TYPE_SAMSUNG_2878,
                            DEVICE_TYPE_SAMSUNG_8888,
                            DEVICE_TYPE_MIM_H03,
                            DEVICE_TYPE_SMARTTHINGS_HVAC,
                            DEVICE_TYPE_SMARTTHINGS_DHW,
                        ],
                        translation_key="device_type",
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

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
                CONF_IP_ADDRESS, default=str(self.flow_data.get(CONF_IP_ADDRESS, ""))
            )
        ] = str

        if mac_required is True:
            schema_dict[vol.Required(CONF_MAC, default=formatted_mac)] = str
        else:
            schema_dict[vol.Optional(CONF_MAC, default=formatted_mac)] = str

        schema_dict[
            vol.Optional(CONF_NAME, default=str(self.flow_data.get(CONF_NAME, "")))
        ] = str
        schema_dict[
            vol.Optional(CONF_TOKEN, default=str(self.flow_data.get(CONF_TOKEN, "")))
        ] = str

        cert_default = DEFAULT_CONF_CERT_FILE
        schema_dict[
            vol.Optional(
                CONF_CERT, default=str(self.flow_data.get(CONF_CERT, cert_default))
            )
        ] = str

        schema_dict[vol.Optional(CONF_POLL_INTERVAL, default=interval_str)] = (
            TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
        )

        if is_8888 is False:
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
                ),
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

    async def _async_process_samsung_device_step(
        self, step_id: str, is_8888: bool, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Common logic for processing Samsung network configuration steps."""
        errors: dict[str, str] = {}
        schema_generator = (
            self._get_samsung_8888_schema
            if is_8888 is True
            else self._get_samsung_2878_schema
        )

        if user_input is not None:
            self.flow_data.update(user_input)

            # 1. MAC discovery
            ip_addr = str(self.flow_data[CONF_IP_ADDRESS])
            mac_val = self.flow_data.get(CONF_MAC)
            error_reason = await self._async_resolve_mac_and_set_unique_id(
                ip_address=ip_addr, mac_address=mac_val
            )

            if error_reason is not None:
                errors["base"] = error_reason
                req = error_reason == "mac_resolve_failed"
                return self.async_show_form(
                    step_id=step_id,
                    data_schema=schema_generator(mac_required=req),
                    errors=errors,
                )

            # 2. Validation of poll interval
            if (
                CONF_POLL_INTERVAL in user_input
                and user_input[CONF_POLL_INTERVAL] is not None
            ):
                try:
                    seconds = validate_poll_interval(user_input[CONF_POLL_INTERVAL])
                    self.flow_data[CONF_POLL_INTERVAL] = seconds
                except ValueError:
                    errors[CONF_POLL_INTERVAL] = "invalid_poll_interval"
                    return self.async_show_form(
                        step_id=step_id,
                        data_schema=schema_generator(mac_required=False),
                        errors=errors,
                    )

            # 3. If token is already present
            token_val = self.flow_data.get(CONF_TOKEN)
            if token_val:
                return await self.async_step_test_connection()

            # 4. Check certificate path if provided
            cert_val = self.flow_data.get(CONF_CERT, "")
            is_valid_cert = await self._async_validate_cert_path(str(cert_val))
            if is_valid_cert is False:
                errors["base"] = "cert_not_found"
                return self.async_show_form(
                    step_id=step_id,
                    data_schema=schema_generator(mac_required=False),
                    errors=errors,
                )

            # 5. Initialize the appropriate token acquirer
            if is_8888 is True:
                target_cert = str(cert_val) if cert_val else "ac14k_m.pem"
                self.acquirer = SamsungTokenAcquirer8888(
                    self.hass, ip_addr, target_cert
                )
            else:
                self.acquirer = SamsungTokenAcquirer(self.hass, ip_addr, str(cert_val))

            return await self.async_step_initiate_pairing()

        return self.async_show_form(
            step_id=step_id,
            data_schema=schema_generator(mac_required=False),
            errors=errors,
        )

    async def async_step_samsung_2878(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Process step for Port 2878 devices."""
        return await self._async_process_samsung_device_step(
            step_id="samsung_2878", is_8888=False, user_input=user_input
        )

    async def async_step_samsung_8888(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Process step for Port 8888 devices."""
        return await self._async_process_samsung_device_step(
            step_id="samsung_8888", is_8888=True, user_input=user_input
        )

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
        is_st = (
            device_type == DEVICE_TYPE_SMARTTHINGS_HVAC
            or device_type == DEVICE_TYPE_SMARTTHINGS_DHW
        )

        try:
            val = self.flow_data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            interval_str = str(datetime.timedelta(seconds=int(val)))
        except (ValueError, TypeError):
            interval_str = str(self.flow_data.get(CONF_POLL_INTERVAL, ""))

        token_from_data = self.flow_data.get(CONF_TOKEN)
        if token_from_data:
            default_token = str(token_from_data)
        elif is_st is True:
            st_token = self._get_smartthings_token()
            default_token = st_token if st_token is not None else ""
        else:
            default_token = ""

        schema_dict: dict[vol.Marker, Any] = {}

        ip_default = str(
            self.flow_data.get(CONF_IP_ADDRESS, "api.smartthings.com" if is_st else "")
        )

        if is_st is True:
            schema_dict[vol.Required(CONF_IP_ADDRESS, default=ip_default)] = str
            schema_dict[vol.Optional(CONF_DEVICE_ID)] = str
        else:
            if ip_default:
                schema_dict[vol.Required(CONF_IP_ADDRESS, default=ip_default)] = str
            else:
                schema_dict[vol.Required(CONF_IP_ADDRESS)] = str

        schema_dict[vol.Required(CONF_TOKEN, default=default_token)] = str
        schema_dict[vol.Optional(CONF_NAME)] = str
        schema_dict[vol.Optional(CONF_POLL_INTERVAL, default=interval_str)] = (
            TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
        )

        return vol.Schema(schema_dict)

    async def async_step_rest_api(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle configuration for REST API devices with manual token."""
        errors: dict[str, str] = {}
        if user_input:
            self.flow_data.update(user_input)

            raw_token = self.flow_data.get(CONF_TOKEN)
            if raw_token:
                safe_token = sanitize_token(str(raw_token))
                if not safe_token:
                    errors[CONF_TOKEN] = "invalid_token_format"
                    step_id_err = "rest_api"
                    schema_err = self._get_rest_api_schema()
                    return self.async_show_form(
                        step_id=step_id_err, data_schema=schema_err, errors=errors
                    )
                self.flow_data[CONF_TOKEN] = safe_token  # pragma: no mutate

            device_type = self.flow_data.get(CONF_DEVICE_TYPE)
            if device_type:
                if device_type in DEVICE_TYPE_TO_CONFIG_FILE:
                    self.flow_data[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE[
                        device_type
                    ]

            if (
                CONF_POLL_INTERVAL in user_input
                and user_input[CONF_POLL_INTERVAL] is not None
            ):
                try:
                    seconds = validate_poll_interval(user_input[CONF_POLL_INTERVAL])
                    self.flow_data[CONF_POLL_INTERVAL] = seconds
                except ValueError:
                    errors[CONF_POLL_INTERVAL] = "invalid_poll_interval"
                    step_id_err2 = "rest_api"
                    schema_err2 = self._get_rest_api_schema()
                    return self.async_show_form(
                        step_id=step_id_err2, data_schema=schema_err2, errors=errors
                    )

            try:
                _LOGGER.debug(
                    "Testing lightweight REST API connection..."
                )  # pragma: no mutate
                session = async_get_clientsession(self.hass)
                ip_addr = str(self.flow_data[CONF_IP_ADDRESS])
                host_str = (
                    f"[{ip_addr}]" if ":" in ip_addr else ip_addr
                )  # pragma: no mutate
                url = f"https://{host_str}/v1/devices"
                headers = {"Authorization": f"Bearer {self.flow_data.get(CONF_TOKEN)}"}

                async with session.get(
                    url, headers=headers, timeout=GLOBAL_HTTP_TIMEOUT
                ) as response:  # pragma: no mutate
                    if response.status != 200:
                        _LOGGER.warning(
                            "REST API connection test failed..."
                        )  # pragma: no mutate
                        raise CannotConnect("HTTP Status Error")  # pragma: no mutate

                dev_id = self.flow_data.get(CONF_DEVICE_ID)
                mac_id = self.flow_data.get(CONF_MAC)
                if dev_id is not None:
                    unique_id = str(dev_id)
                elif mac_id is not None:
                    unique_id = str(mac_id)
                else:
                    unique_id = ""  # pragma: no mutate
                if not unique_id:
                    _LOGGER.error(
                        "REST API connection test failed..."
                    )  # pragma: no mutate
                    return self.async_abort(reason="no_mac_address_found")

                await self.async_set_unique_id(unique_id)
                if self.reauth_entry is None:
                    self._abort_if_unique_id_configured()
                return await self._create_entry()

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception as e:  # pylint: disable=broad-except
                if e.__class__.__name__ == "AbortFlow":
                    raise
                _LOGGER.exception(
                    "Unexpected error during connection test"
                )  # pragma: no mutate
                errors["base"] = "unknown_error"

        step_id_def = "rest_api"
        schema_def = self._get_rest_api_schema()
        return self.async_show_form(
            step_id=step_id_def,
            data_schema=schema_def,
            errors=errors,
        )

    async def async_step_initiate_pairing(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Phase 1: Put the device in pairing mode using a safe wrapper."""
        _LOGGER.debug("Entering async_step_initiate_pairing.")  # pragma: no mutate
        if self.task is None:
            _LOGGER.debug(
                "Creating task for _initiate_pairing_safe."
            )  # pragma: no mutate
            self.task = self.hass.async_create_task(self._initiate_pairing_safe())

        if self.task is not None and self.task.done():
            try:
                result = self.task.result()
            except Exception as e:
                _LOGGER.error("Task failed unexpectedly: %s", e)  # pragma: no mutate
                result = {"ok": False, "error": "unknown_error"}  # pragma: no mutate
            self.task = None

            if result.get("ok"):
                # fmt: off
                _LOGGER.debug('Pairing initiation successful, advancing to await_button.')  # pragma: no mutate
                # fmt: on
                successful_config = result.get("config")
                if successful_config is not None:
                    self.flow_data["preferred_connection"] = successful_config
                    # fmt: off
                    _LOGGER.info('Successfully found working connection config, will save: %s', successful_config)  # pragma: no mutate
                    # fmt: on
                return self.async_show_progress_done(next_step_id="await_button")

            fallback_attempted = self.flow_data.get("_fallback_attempted")
            if fallback_attempted is not True:
                self.flow_data["_fallback_attempted"] = True
                # fmt: off
                _LOGGER.info('Pairing initiation failed. Attempting automatic port fallback.')  # pragma: no mutate
                # fmt: on

                device_type = self.flow_data[CONF_DEVICE_TYPE]
                ip_address = str(self.flow_data[CONF_IP_ADDRESS])
                cert_path = str(self.flow_data.get(CONF_CERT, ""))

                if device_type == DEVICE_TYPE_SAMSUNG_2878:
                    # fmt: off
                    _LOGGER.info('Falling back from port %s to port %s topology.', PORT_SAMSUNG_2878, PORT_SAMSUNG_8888)  # pragma: no mutate
                    # fmt: on
                    # We intentionally update flow_data with the fallback value so the UI reflects the attempted state if it fails. This is expected behavior.
                    self.flow_data[CONF_DEVICE_TYPE] = DEVICE_TYPE_SAMSUNG_8888
                    target_cert = cert_path if cert_path else "ac14k_m.pem"
                    self.flow_data[CONF_CERT] = target_cert
                    self.acquirer = SamsungTokenAcquirer8888(
                        self.hass, ip_address, target_cert
                    )
                elif device_type == DEVICE_TYPE_SAMSUNG_8888:
                    # fmt: off
                    _LOGGER.info('Falling back from port %s to port %s topology.', PORT_SAMSUNG_8888, PORT_SAMSUNG_2878)  # pragma: no mutate
                    # fmt: on
                    # We intentionally update flow_data with the fallback value so the UI reflects the attempted state if it fails. This is expected behavior.
                    self.flow_data[CONF_DEVICE_TYPE] = DEVICE_TYPE_SAMSUNG_2878
                    self.acquirer = SamsungTokenAcquirer(
                        self.hass, ip_address, cert_path
                    )

                self.task = self.hass.async_create_task(self._initiate_pairing_safe())
                return self.async_show_progress(
                    step_id="initiate_pairing",
                    progress_action="initiating_pairing",
                    progress_task=self.task,
                )

            self.flow_data["error_key"] = result.get("error", "unknown_error")
            if "error_details" in result:
                self.flow_data["error_details"] = result["error_details"]
            return self.async_show_progress_done(next_step_id="handle_error")

        return self.async_show_progress(
            step_id="initiate_pairing",
            progress_action="initiating_pairing",
            progress_task=self.task,
        )

    # pylint: disable=unused-argument
    async def async_step_await_button(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Phase 2: Wait for the user to press the required button."""
        _LOGGER.debug("Entering async_step_await_button.")  # pragma: no mutate
        if self.task is None:
            _LOGGER.debug("Creating task for _wait_token_safe.")  # pragma: no mutate
            self.task = self.hass.async_create_task(self._wait_token_safe())

        if self.task is not None and self.task.done():
            try:
                result = self.task.result()
            except Exception as e:
                _LOGGER.error("Task failed unexpectedly: %s", e)  # pragma: no mutate
                result = {"ok": False, "error": "unknown_error"}  # pragma: no mutate
            self.task = None
            if result.get("ok"):
                raw_token = str(result.get("token", ""))
                safe_token = sanitize_token(raw_token)

                if not safe_token:
                    # fmt: off
                    _LOGGER.error('Acquired token was rejected by sanitizer - aborting pairing. This may indicate a compromised or malformed AC response.')  # pragma: no mutate
                    # fmt: on
                    self.flow_data["error_key"] = "token_acquisition_failed"
                    return self.async_show_progress_done(next_step_id="handle_error")

                self.flow_data[CONF_TOKEN] = safe_token

                if self.flow_data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_SAMSUNG_2878:
                    # fmt: off
                    _LOGGER.debug('Token for 2878 device acquired. Routing to test connection.')  # pragma: no mutate
                    # fmt: on
                    return self.async_show_progress_done(next_step_id="test_connection")

                # fmt: off
                _LOGGER.debug('Token acquisition successful, advancing to discover_uuid.')  # pragma: no mutate
                # fmt: on
                return self.async_show_progress_done(next_step_id="discover_uuid")

            self.flow_data["error_key"] = result.get(
                "error", "unknown_error"
            )  # pragma: no mutate
            if "error_details" in result:
                self.flow_data["error_details"] = result["error_details"]
            return self.async_show_progress_done(next_step_id="handle_error")

        return self.async_show_progress(
            step_id="await_button",
            progress_action="awaiting_button_press",
            progress_task=self.task,
            description_placeholders={
                "ip_address": self.flow_data.get(CONF_IP_ADDRESS, "")
            },
        )

    # pylint: disable=too-many-locals,too-many-branches
    async def _test_connection_safe(self) -> dict[str, Any]:
        """Safe and lightweight wrapper for testing the connection."""
        _LOGGER.debug(
            "Executing lightweight connection test: _test_connection_safe"
        )  # pragma: no mutate
        try:
            device_type = self.flow_data[CONF_DEVICE_TYPE]
            ip_address = str(self.flow_data.get(CONF_IP_ADDRESS, "Unknown"))  # pragma: no mutate
            token = str(self.flow_data.get(CONF_TOKEN) or "")

            if device_type in DEVICE_TYPE_8888_GROUP:
                session = async_get_clientsession(self.hass)
                url = f"https://{ip_address}:{PORT_SAMSUNG_8888}/devices"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }

                ssl_context = ssl.create_default_context()
                cert_path = str(self.flow_data.get(CONF_CERT) or "")

                if cert_path:
                    full_path = resolve_cert_path(cert_path, os.path.dirname(__file__))
                    if full_path is not None:
                        cert_exists = await self.hass.async_add_executor_job(
                            os.path.exists, full_path
                        )
                        if cert_exists:
                            ssl_context.load_verify_locations(cafile=full_path)
                else:
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

                async with session.get(
                    url,
                    headers=headers,
                    ssl=ssl_context,
                    timeout=GLOBAL_HTTP_TIMEOUT,  # pragma: no mutate
                ) as response:
                    if response.status == 200:
                        _LOGGER.debug(
                            "Lightweight 8888 connection test successful."
                        )  # pragma: no mutate
                        return {"ok": True}

                    # fmt: off
                    _LOGGER.warning('8888 connection test failed with status: %s', response.status)  # pragma: no mutate
                    # fmt: on
                    return {"ok": False, "error": "cannot_connect"}

            elif device_type == DEVICE_TYPE_SAMSUNG_2878:
                config_data = self.flow_data.copy()
                if "unique_id" not in config_data:
                    config_data["unique_id"] = config_data.get(CONF_MAC, "")

                if CONF_CONFIG_FILE not in config_data:
                    if device_type in DEVICE_TYPE_TO_CONFIG_FILE:
                        config_data[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE[
                            device_type
                        ]

                controller = YamlController(config=config_data, logger=_LOGGER)
                controller.hass = self.hass
                # pylint: disable=protected-access
                controller._session = async_get_clientsession(self.hass)

                initialized = await controller.initialize()
                if not initialized:
                    return {"ok": False, "error": "cannot_connect"}

                state_data = None
                if (
                    controller.loader is not None
                    and controller.loader.state_getter is not None
                ):
                    state_data = (
                        await controller.loader.state_getter.async_update_state(
                            None, False
                        )
                    )
                await controller.async_shutdown()

                return {"ok": state_data is not None}

            else:
                # fmt: off
                _LOGGER.error('Unknown device type for connection test: %s', device_type)  # pragma: no mutate
                # fmt: on
                return {"ok": False, "error": "cannot_connect"}

        except CannotConnect as err:
            ip_address = str(self.flow_data.get(CONF_IP_ADDRESS, "Unknown"))  # pragma: no mutate
            _LOGGER.error(
                "Fatal pairing failure at %s. Details: %s", ip_address, err
            )  # pragma: no mutate
            return {
                "ok": False,
                "error": "pairing_connection_failed",
                "error_details": str(err),
            }
        except TimeoutError as err:
            ip_address = str(self.flow_data.get(CONF_IP_ADDRESS, "Unknown"))  # pragma: no mutate
            _LOGGER.warning(
                "Timeout connecting to %s. Wrong IP?", ip_address
            )  # pragma: no mutate
            return {
                "ok": False,
                "error": "timeout_connect",
                "error_details": str(err),
            }
        except AuthError as err:
            _LOGGER.warning(
                "AC rejected token during pairing."
            )  # pragma: no mutate
            return {"ok": False, "error": "invalid_auth", "error_details": str(err)}
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error(
                "Unknown error during connection test: %s", e, exc_info=True
            )  # pragma: no mutate
            return {"ok": False, "error": "cannot_connect"}

    # pylint: disable=unused-argument
    async def async_step_test_connection(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Phase to validate the IP and token."""
        _LOGGER.debug("Entering async_step_test_connection.")  # pragma: no mutate
        if self.task is None:
            _LOGGER.debug(
                "Creating task for _test_connection_safe."
            )  # pragma: no mutate
            self.task = self.hass.async_create_task(self._test_connection_safe())

        if self.task is not None and self.task.done():
            try:
                result = self.task.result()
            except Exception as e:
                _LOGGER.error("Task failed unexpectedly: %s", e)  # pragma: no mutate
                result = {"ok": False, "error": "unknown_error"}  # pragma: no mutate
            self.task = None
            if result.get("ok"):
                _LOGGER.debug(
                    "Connection test successful, advancing to discovery."
                )  # pragma: no mutate
                dev_type = self.flow_data[CONF_DEVICE_TYPE]
                dev_id = self.flow_data.get(CONF_DEVICE_ID)

                if dev_type != DEVICE_TYPE_SAMSUNG_2878 and not dev_id:
                    return self.async_show_progress_done(next_step_id="discover_uuid")
                return self.async_show_progress_done(next_step_id="create_entry")

            self.flow_data.pop(CONF_TOKEN, None)

            err_raw = result.get("error")
            err_val = str(err_raw) if err_raw else "cannot_connect"

            self.flow_data["error_key"] = err_val
            return self.async_show_progress_done(next_step_id="handle_error")

        ip_addr = str(self.flow_data[CONF_IP_ADDRESS])
        desc_dict = {"ip_address": ip_addr}
        p_task = self.task

        return self.async_show_progress(
            step_id="test_connection",
            progress_action="testing_connection",
            progress_task=p_task,
            description_placeholders=desc_dict,
        )

    async def _async_process_mim_h03(
        self, discovered_devices: list[Any]
    ) -> ConfigFlowResult:
        """Helper to process discovery for MIM-H03 coordinators and their AC units."""
        internal_coordinator = None
        ac_units_info = []

        for device in discovered_devices:
            if not isinstance(device, dict):
                continue

            # PHASE 1 FIX APPLIED: Avoid casting None to "None"
            device_id = str(device.get("id") or "")
            has_mode = "Mode" in device

            if device_id == "0" or has_mode is False:
                if internal_coordinator is None or device_id == "0":
                    internal_coordinator = device
                continue

            name = str(device.get("name") or f"Indoor Unit {device_id}")
            ac_units_info.append(
                {
                    "id": device_id,
                    "uuid": str(device.get("uuid", "")),
                    "name": f"ID {device_id} ({name})",
                    "description": str(device.get("description", name)),
                }
            )

        if internal_coordinator is not None:
            coordinator_uuid = str(internal_coordinator.get("uuid", ""))
            if coordinator_uuid:
                await self.async_set_unique_id(
                    coordinator_uuid, raise_on_progress=False
                )
                coord_name = str(
                    internal_coordinator.get("name", "MIM-H03 Coordinator")
                )
                self.flow_data.update(
                    {
                        "unique_id": coordinator_uuid,
                        CONF_DEVICE_ID: str(internal_coordinator.get("id") or ""),
                        CONF_NAME: f"{coord_name} {coordinator_uuid}",
                    }
                )
                # PHASE 1 FIX APPLIED: Do not abort prematurely on reconfigurations
                if self.reauth_entry is None and self.source != SOURCE_RECONFIGURE:
                    self._abort_if_unique_id_configured(updates=self.flow_data)

                if ac_units_info:
                    self.flow_data[CONF_DISCOVERED_DEVICES] = ac_units_info
                    return await self.async_step_select_devices()
                return await self._create_entry()
            return self.async_abort(reason="no_coordinator_uuid")
        return self.async_abort(reason="no_coordinator_found")

    async def _async_process_samsung_8888_discovery(
        self, discovered_devices: list[Any]
    ) -> ConfigFlowResult:
        """Helper to process discovery for standard 8888 devices."""
        device_uuid = str(discovered_devices[0].get("uuid") or "")
        if not device_uuid:
            device_uuid = str(discovered_devices[0].get("id") or "")

        if device_uuid:
            mac_str = str(self.flow_data[CONF_MAC])
            self.flow_data.update(
                {
                    CONF_DEVICE_ID: device_uuid,
                    CONF_NAME: f"Samsung AC {mac_str}",
                }
            )
            return await self._create_entry()
        return self.async_abort(reason="discovery_failed")

    async def _async_process_generic_discovery(
        self, discovered_devices: list[Any]
    ) -> ConfigFlowResult:
        """Helper to process discovery for generic or legacy multi-split devices."""
        devices_info = []
        for d in discovered_devices:
            if isinstance(d, dict):
                did = str(d.get("id") or str(d))
                dname = str(d.get("name", f"Indoor Unit {did}"))
                devices_info.append(
                    {
                        "id": did,
                        "uuid": str(d.get("uuid") or ""),
                        "name": dname,
                        "description": str(d.get("description", dname)),
                    }
                )

        if not devices_info:
            return await self._create_entry()

        self.flow_data[CONF_DISCOVERED_DEVICES] = devices_info
        return await self.async_step_select_devices()

    async def _async_fallback_raw_discovery(
        self, config_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Helper to handle the fallback to raw socket connection if HTTP fails."""
        _LOGGER.warning(
            "[%s] Malformed HTTP headers detected during discovery. Automatically retrying with 'Robust (raw socket)' engine.",  # pragma: no mutate
            self.unique_id or "?",
        )  # pragma: no mutate
        self.flow_data[CONF_CONN_METHOD] = CONN_METHOD_RAW
        config_data[CONF_CONN_METHOD] = CONN_METHOD_RAW

        controller = None
        try:
            controller = YamlController(
                config=config_data,
                logger=_LOGGER,
                hass=self.hass,
                session=async_get_clientsession(self.hass),
            )

            init_fb = await controller.initialize()
            status_fb = await controller.async_get_status()

            if not init_fb or not status_fb:
                _LOGGER.error(
                    "Failed to initialize with raw engine during discovery fallback."
                )  # pragma: no mutate
                return self.async_abort(reason="cannot_connect")

            return await self._create_entry()
        except Exception as raw_exc:  # pylint: disable=broad-exception-caught
            _LOGGER.exception(
                "Raw-engine fallback also failed: %s", raw_exc
            )  # pragma: no mutate
            return self.async_abort(reason="cannot_connect")
        finally:
            if controller is not None:
                await controller.async_shutdown()

    # pylint: disable=too-many-return-statements,too-many-branches,too-many-statements,unused-argument
    async def async_step_discover_uuid(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Step to discover indoor units from the device (Director)."""
        config_data = self.flow_data.copy()
        if self.unique_id is not None:
            config_data["unique_id"] = self.unique_id

        device_type = config_data.get(CONF_DEVICE_TYPE)
        if CONF_CONFIG_FILE not in config_data and device_type is not None:
            cf = DEVICE_TYPE_TO_CONFIG_FILE.get(device_type)
            if cf is not None:
                config_data[CONF_CONFIG_FILE] = cf

        controller = None
        try:
            controller = YamlController(
                config=config_data,
                logger=_LOGGER,
                hass=self.hass,
                session=async_get_clientsession(self.hass),
            )

            initialized: bool = await controller.initialize()
            status_ok: bool = await controller.async_get_status()

            if not initialized or not status_ok:
                _LOGGER.error(
                    "Failed to initialize or get status during discovery."
                )  # pragma: no mutate
                return self.async_abort(reason="cannot_connect")

            raw_devs: list[Any] = []  # pragma: no mutate
            if hasattr(controller, "discovered_devices"):
                raw_devs = controller.discovered_devices

            discovered_devices = []
            if raw_devs:
                for dev in raw_devs:
                    discovered_devices.append(dev)

            # Scenario A: Blind device (no sub-devices)
            if not discovered_devices:
                _LOGGER.warning(
                    "Could not discover indoor units. Creating a single entry."
                )  # pragma: no mutate
                if controller.unique_id:
                    await self.async_set_unique_id(
                        str(controller.unique_id), raise_on_progress=False
                    )
                    if controller.device_id:
                        self.flow_data[CONF_DEVICE_ID] = str(controller.device_id)

                    # PHASE 1 FIX APPLIED: Do not abort prematurely on reconfigurations
                    if self.reauth_entry is None and self.source != SOURCE_RECONFIGURE:
                        self._abort_if_unique_id_configured(updates=self.flow_data)
                return await self._create_entry()

            _LOGGER.debug(
                "Discovered devices for %s: %s", device_type, discovered_devices
            )  # pragma: no mutate

            # Scenario B: Parse delegation by type
            if device_type == DEVICE_TYPE_MIM_H03:
                return await self._async_process_mim_h03(discovered_devices)

            if device_type == DEVICE_TYPE_SAMSUNG_8888:
                return await self._async_process_samsung_8888_discovery(
                    discovered_devices
                )

            return await self._async_process_generic_discovery(discovered_devices)

        except InvalidHeaderError:
            # Shut down current HTTP controller before attempting raw fallback
            if controller is not None:
                await controller.async_shutdown()
                controller = None
            return await self._async_fallback_raw_discovery(config_data)

        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.exception("Discovery failed: %s", e)  # pragma: no mutate
            return self.async_abort(reason="unknown_error")
        finally:
            if controller is not None:
                await controller.async_shutdown()

    async def async_step_select_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow the user to select which indoor units to add."""
        discovered_devices = self.flow_data.get(CONF_DISCOVERED_DEVICES) or []
        device_options = {
            str(device["id"]): str(device.get("name") or f"Indoor Unit {device['id']}")
            for device in discovered_devices
        }

        if user_input:
            selected_devices_ids = user_input.get(CONF_SELECTED_DEVICES) or []
            if not selected_devices_ids:
                step_id_def = "select_devices"

                def_keys = []
                for k in device_options:
                    def_keys.append(k)

                dev_count = len(discovered_devices)
                err_dict = {"base": "no_devices_selected"}
                desc_dict = {"device_count": dev_count}

                req_key = vol.Required(CONF_SELECTED_DEVICES, default=def_keys)
                schema_dict = {req_key: cv.multi_select(device_options)}

                return self.async_show_form(
                    step_id=step_id_def,
                    data_schema=vol.Schema(schema_dict),
                    errors=err_dict,
                    description_placeholders=desc_dict,
                )

            self.flow_data[CONF_DEVICES] = [
                d for d in discovered_devices if str(d["id"]) in selected_devices_ids
            ]

            main_unique_id = self.flow_data.get("unique_id")
            if not main_unique_id:
                main_unique_id = self.flow_data.get(CONF_MAC)
            if not main_unique_id:
                main_unique_id = self.flow_data.get(CONF_DEVICE_ID)

            if main_unique_id:
                await self.async_set_unique_id(
                    str(main_unique_id), raise_on_progress=False
                )
                if self.reauth_entry is None and self.source != SOURCE_RECONFIGURE:
                    self._abort_if_unique_id_configured(updates=self.flow_data)
                return await self._create_entry()
            return self.async_abort(reason="no_unique_id")

        step_id_def2 = "select_devices"

        def_keys2 = []
        for k in device_options:
            def_keys2.append(k)

        dev_count2 = len(discovered_devices)
        desc_dict2 = {"device_count": dev_count2}

        req_key2 = vol.Required(CONF_SELECTED_DEVICES, default=def_keys2)
        schema_dict2 = {req_key2: cv.multi_select(device_options)}
        schema = vol.Schema(schema_dict2)

        return self.async_show_form(
            step_id=step_id_def2,
            data_schema=schema,
            description_placeholders=desc_dict2,
        )

    # pylint: disable=unused-argument
    async def async_step_handle_error(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Handles the display of errors after a progress step fails."""
        error_key = str(
            self.flow_data.pop("error_key", "unknown_error")
        )  # pragma: no mutate
        error_details = str(
            self.flow_data.pop("error_details", "")
        )  # pragma: no mutate
        device_type = self.flow_data[CONF_DEVICE_TYPE]
        ip_address = str(self.flow_data.get(CONF_IP_ADDRESS, "Unknown"))  # pragma: no mutate

        # Directive 1: Lethal Failures -> Verbose Abort with Placeholders
        if error_key == "pairing_connection_failed":
            details_str = error_details or "Connection refused or unreachable"
            _LOGGER.error(
                "Fatal pairing failure at %s. Details: %s", ip_address, details_str
            )  # pragma: no mutate
            return self.async_abort(
                reason="pairing_connection_failed",
                description_placeholders={
                    "ip_address": ip_address,
                    "error_details": details_str,
                },
            )

        if device_type == DEVICE_TYPE_MIM_H03:
            step_id = "mim_h03"
        elif device_type == DEVICE_TYPE_SAMSUNG_8888:
            step_id = "samsung_8888"
        else:
            step_id = "samsung_2878"

        schema_generator = (
            self._get_samsung_8888_schema
            if device_type in DEVICE_TYPE_8888_GROUP
            else self._get_samsung_2878_schema
        )

        req_mac = False
        errors: dict[str, str] = {}

        # Directive 2: Recoverable Failures -> Form Retry with Targeted Errors
        if error_key == "mac_resolve_failed":
            req_mac = True
            errors["base"] = "mac_resolve_failed"
        elif error_key == "timeout_connect":
            _LOGGER.warning(
                "Timeout connecting to %s. Wrong IP?", ip_address
            )  # pragma: no mutate
            errors[CONF_IP_ADDRESS] = "timeout_connect"
        elif error_key == "invalid_auth":
            _LOGGER.warning(
                "AC rejected token during pairing."
            )  # pragma: no mutate
            errors["base"] = "invalid_auth"
        else:
            errors["base"] = error_key

        return self.async_show_form(
            step_id=step_id,
            data_schema=schema_generator(mac_required=req_mac),
            errors=errors,
        )

    # pylint: disable=unused-argument
    async def async_step_create_entry(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Final invisible step that creates the config entry."""
        return await self._create_entry()

    async def _create_entry(self) -> ConfigFlowResult:
        """Create the config entry and finish the flow."""
        device_type = self.flow_data[CONF_DEVICE_TYPE]

        uid_data = str(self.flow_data.get("unique_id", ""))
        mac_data = str(self.flow_data.get(CONF_MAC, ""))
        final_unique_id = uid_data if uid_data else mac_data

        if not final_unique_id:
            return self.async_abort(reason="no_mac_address_found")

        await self.async_set_unique_id(final_unique_id)
        if self.reauth_entry is None and self.source != SOURCE_RECONFIGURE:
            self._abort_if_unique_id_configured(updates=self.flow_data)
        self.flow_data["unique_id"] = final_unique_id

        title = (
            str(self.flow_data.get(CONF_NAME, "")).strip()
            or f"Samsung AC {final_unique_id}"
        )
        self.flow_data[CONF_NAME] = title

        if (
            device_type in [DEVICE_TYPE_SAMSUNG_8888, DEVICE_TYPE_MIM_H03]
            and final_unique_id not in title
        ):
            title = f"{title} ({final_unique_id})"

        transient_keys = (CONF_DISCOVERED_DEVICES, CONF_SELECTED_DEVICES)

        if self.reauth_entry is not None:
            _LOGGER.debug(
                "Re-auth successful. Updating config entry."
            )  # pragma: no mutate
            entry_data = {
                k: v for k, v in self.flow_data.items() if k not in transient_keys
            }
            self.hass.config_entries.async_update_entry(
                self.reauth_entry, data=entry_data
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.reauth_entry.entry_id)
            )
            return self.async_abort(reason="reauth_successful")

        if self.source == SOURCE_RECONFIGURE:
            # fmt: off
            _LOGGER.debug('Reconfigure successful via pairing flow. Updating config entry.')  # pragma: no mutate
            # fmt: on
            reconfigure_entry = self._get_reconfigure_entry()
            entry_data = {
                k: v for k, v in self.flow_data.items() if k not in transient_keys
            }
            updated_data = {**reconfigure_entry.data, **entry_data}
            self.hass.config_entries.async_update_entry(
                reconfigure_entry, data=updated_data
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(reconfigure_entry.entry_id)
            )
            return self.async_abort(reason="reconfigure_successful")

        entry_data = {
            k: v for k, v in self.flow_data.items() if k not in transient_keys
        }
        return self.async_create_entry(title=title, data=entry_data)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication failure from the integration."""
        _LOGGER.debug(
            "Entering async_step_reauth with data: %s", entry_data
        )  # pragma: no mutate
        eid_raw = self.context.get("entry_id")
        eid_str = str(eid_raw) if eid_raw is not None else ""
        self.reauth_entry = self.hass.config_entries.async_get_entry(eid_str)

        if self.reauth_entry is not None:
            self.flow_data = dict(self.reauth_entry.data)

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-authentication and route to the correct data acquisition step."""
        if user_input is not None and self.reauth_entry is not None:
            # fmt: off
            _LOGGER.debug('Reauth confirmed, clearing old token and routing to pairing step.')  # pragma: no mutate
            # fmt: on
            self.flow_data.pop(CONF_TOKEN, None)

            device_type = self.flow_data.get(CONF_DEVICE_TYPE)
            if (
                device_type == DEVICE_TYPE_SMARTTHINGS_HVAC
                or device_type == DEVICE_TYPE_SMARTTHINGS_DHW
            ):
                return await self.async_step_rest_api()

            if device_type == DEVICE_TYPE_SAMSUNG_2878:
                return await self.async_step_samsung_2878()
            return await self.async_step_samsung_8888()

        name = (
            self.reauth_entry.title
            if self.reauth_entry is not None
            else "Unknown Device"
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"device_name": name},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a reconfiguration flow initiated by the user."""
        reconfigure_entry = self._get_reconfigure_entry()
        if not self.flow_data:
            self.flow_data = dict(reconfigure_entry.data)

        u_input = user_input
        return await self.async_step_reconfigure_confirm(u_input)

    async def async_step_reconfigure_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the reconfiguration form and process its submission."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        device_type = self.flow_data[CONF_DEVICE_TYPE]
        self.flow_data[CONF_DEVICE_TYPE] = device_type
        is_8888 = (
            device_type in DEVICE_TYPE_8888_GROUP or device_type == DEVICE_TYPE_MIM_H03
        )

        base_schema = vol.Schema(
            {
                vol.Required(CONF_IP_ADDRESS): str,
                vol.Optional(CONF_MAC): str,
                vol.Optional(CONF_TOKEN): str,
                vol.Optional(CONF_CERT): str,
            }
        )

        raw_ip_def = self.flow_data.get(CONF_IP_ADDRESS)
        ip_def = str(raw_ip_def) if raw_ip_def is not None else ""
        raw_mac_def = str(self.flow_data.get(CONF_MAC) or "")
        mac_def = dr.format_mac(raw_mac_def).upper() if raw_mac_def else ""
        token_def = str(self.flow_data.get(CONF_TOKEN) or "")
        is_samsung = is_8888 or device_type == DEVICE_TYPE_SAMSUNG_2878

        # CERTIFICATE HARDENING
        cert_def = str(self.flow_data.get(CONF_CERT, "")).strip()
        if not cert_def:
            cert_def = DEFAULT_CONF_CERT_FILE if is_samsung else ""

        suggested = {
            CONF_IP_ADDRESS: ip_def,
            CONF_MAC: mac_def,
            CONF_TOKEN: token_def,
            CONF_CERT: cert_def,
        }
        schema = self.add_suggested_values_to_schema(base_schema, suggested)

        if user_input:
            self.flow_data[CONF_IP_ADDRESS] = str(user_input.get(CONF_IP_ADDRESS) or "")
            self.flow_data[CONF_MAC] = str(user_input.get(CONF_MAC) or "")
            self.flow_data[CONF_TOKEN] = str(user_input.get(CONF_TOKEN) or "")
            self.flow_data[CONF_CERT] = str(user_input.get(CONF_CERT) or "")

            if device_type not in (
                DEVICE_TYPE_SMARTTHINGS_HVAC,
                DEVICE_TYPE_SMARTTHINGS_DHW,
            ):
                # FAIL FAST APPLIED: No phantom fallbacks
                ip_for_mac = str(self.flow_data[CONF_IP_ADDRESS])
                mac_for_mac = self.flow_data.get(CONF_MAC)
                error_reason = await self._async_resolve_mac_and_set_unique_id(
                    ip_address=ip_for_mac, mac_address=mac_for_mac
                )

                if error_reason:
                    errors["base"] = error_reason
                    ip_err_def = str(self.flow_data[CONF_IP_ADDRESS])
                    raw_mac_err = str(self.flow_data[CONF_MAC])
                    mac_err_def = (
                        dr.format_mac(raw_mac_err).upper() if raw_mac_err else ""
                    )
                    token_err_def = str(self.flow_data[CONF_TOKEN])
                    cert_err_def = str(self.flow_data[CONF_CERT])

                    error_suggested = {
                        CONF_IP_ADDRESS: ip_err_def,
                        CONF_MAC: mac_err_def,
                        CONF_TOKEN: token_err_def,
                        CONF_CERT: cert_err_def,
                    }

                    return self.async_show_form(
                        step_id="reconfigure_confirm",
                        data_schema=self.add_suggested_values_to_schema(
                            base_schema, error_suggested
                        ),
                        errors=errors,
                    )

            cert_value = str(self.flow_data.get(CONF_CERT) or "")
            if not cert_value:
                _LOGGER.warning(
                    "Reconfigure: certificate path was cleared..."
                )  # pragma: no mutate

            if not await self._async_validate_cert_path(cert_value):
                errors["base"] = "cert_not_found"
                ip_err_def = str(self.flow_data[CONF_IP_ADDRESS])
                # EXTRA EXTRACTION for MAC (Preparing ground for tests)
                raw_mac_err = str(self.flow_data[CONF_MAC])
                mac_err_def = dr.format_mac(raw_mac_err).upper() if raw_mac_err else ""
                token_err_def = str(self.flow_data[CONF_TOKEN])
                cert_err_def = str(self.flow_data[CONF_CERT])

                error_suggested = {
                    CONF_IP_ADDRESS: ip_err_def,
                    CONF_MAC: mac_err_def,
                    CONF_TOKEN: token_err_def,
                    CONF_CERT: cert_err_def,
                }

                return self.async_show_form(
                    step_id="reconfigure_confirm",
                    data_schema=self.add_suggested_values_to_schema(
                        base_schema, error_suggested
                    ),
                    errors=errors,
                )

            token_raw = self.flow_data.get(CONF_TOKEN)
            token_val = (
                str(token_raw) if token_raw is not None else ""
            )  # pragma: no mutate
            if not token_val and device_type not in (
                DEVICE_TYPE_SMARTTHINGS_HVAC,
                DEVICE_TYPE_SMARTTHINGS_DHW,
            ):
                _LOGGER.info(
                    "Token absent during reconfigure. Setting up acquirer for discovery."
                )  # pragma: no mutate
                target_cert_name = "ac14k_m.pem"
                target_cert = cert_value if cert_value else target_cert_name

                # FAIL FAST APPLIED: Direct dictionary access
                ip_val = str(self.flow_data[CONF_IP_ADDRESS])

                if is_8888:
                    self.acquirer = SamsungTokenAcquirer8888(
                        self.hass, ip_val, target_cert
                    )
                else:
                    self.acquirer = SamsungTokenAcquirer(self.hass, ip_val, cert_value)
                return await self.async_step_initiate_pairing()

            updated_data = {**reconfigure_entry.data, **self.flow_data}
            self.hass.config_entries.async_update_entry(
                reconfigure_entry, data=updated_data
            )
            _LOGGER.info(
                "Reconfigure: updated entry '%s' with new connectivity parameters.",
                reconfigure_entry.title,
            )  # pragma: no mutate
            await self.hass.config_entries.async_reload(reconfigure_entry.entry_id)
            return self.async_abort(reason="reconfigure_successful")

        r_ip = reconfigure_entry.data.get(CONF_IP_ADDRESS)
        desc_ip = str(r_ip) if r_ip is not None else ""
        desc_placeholders = {
            "device_name": reconfigure_entry.title,
            "ip_address": desc_ip,
        }

        return self.async_show_form(
            step_id="reconfigure_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders=desc_placeholders,
        )


class OptionsFlowHandler(OptionsFlow):  # pylint: disable=too-few-public-methods
    """Handle an options flow for climate_ip."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
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
                    return self.async_show_form(
                        step_id="init",
                        data_schema=schema,
                        errors={CONF_POLL_INTERVAL: "invalid_poll_interval"},
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
                            {
                                "value": CONN_METHOD_REQUESTS,
                                "label": "Legacy (Obsolete)",
                            },
                            {"value": CONN_METHOD_AIOHTTP, "label": "Modern (aiohttp)"},
                            {"value": CONN_METHOD_RAW, "label": "Robust (raw socket)"},
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
                        {"value": "0.1", "label": "0.1°"},
                        {"value": "0.5", "label": "0.5°"},
                        {"value": "1.0", "label": "1.0°"},
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }

        return vol.Schema(schema_dict)
