# pylint: disable=broad-exception-caught,import-outside-toplevel,unused-argument
# custom_components/climate_ip/config_flow.py
# pylint: disable=too-many-lines
"""Config flow for the Climate IP integration."""

import asyncio
import datetime
import logging
import os
import ssl
from typing import Any, Self

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
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
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
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
from .helpers import async_get_mac_address, sanitize_token
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

        _LOGGER.debug("Initializing new Climate IP config flow handler.")  # pragma: no mutate

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
        return bool(self_mac and other_mac and self_mac.upper() == other_mac.upper())

    async def async_step_import(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        """
        Handle the import of a YAML configuration (legacy platform).
        This is triggered by async_setup_platform in climate.py.
        """
        _LOGGER.debug("Starting YAML import for: %s", user_input.get(CONF_IP_ADDRESS))  # pragma: no mutate

        mac_address = user_input.get(CONF_MAC)
        if mac_address:
            user_input[CONF_MAC] = mac_address.replace(":", "").upper()

        unique_id = user_input.get(CONF_MAC)
        if not unique_id:
            _LOGGER.error("YAML import failed: No MAC address provided.")  # pragma: no mutate
            return self.async_abort(reason="no_mac_address_found")

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        config_file = user_input.get(CONF_CONFIG_FILE)
        if config_file and config_file in CONFIG_FILE_TO_DEVICE_TYPE:
            user_input[CONF_DEVICE_TYPE] = CONFIG_FILE_TO_DEVICE_TYPE[config_file]
            # fmt: off
            _LOGGER.debug("Inferred device_type '%s' from config_file '%s'", user_input[CONF_DEVICE_TYPE], config_file)  # pragma: no mutate
            # fmt: on

        device_name = user_input.get(CONFIG_DEVICE_NAME, f"Climate {unique_id}")

        _LOGGER.info("Creating new entry for '%s' from imported YAML.", device_name)  # pragma: no mutate
        return self.async_create_entry(title=device_name, data=user_input)

    @callback
    def async_remove(self) -> None:
        """Clean up background tasks if the user cancels the flow."""
        _LOGGER.debug("Config flow cancelled. Cleaning up tasks.")  # pragma: no mutate
        if self.task:
            self.task.cancel()
        if self.acquirer:
            self.hass.async_create_task(self.acquirer.async_close())

    async def _async_force_arp_update(self, ip_address: str) -> None:
        """
        Force the OS to resolve the MAC and populate the ARP table natively via async.
        Uses a TCP connection attempt to trigger standard ARP discovery.
        """
        for port in (PORT_SAMSUNG_2878, PORT_SAMSUNG_8888):
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip_address, port), timeout=0.5
                )
                writer.close()
                await writer.wait_closed()
                break  # pragma: no mutate
            except (OSError, asyncio.TimeoutError):
                pass

    async def _async_resolve_mac_and_set_unique_id(
        self, ip_address: str, mac_address: str | None
    ) -> str | None:
        """
        Resolve MAC address using getmac library or user input.
        Returns an error key string if resolution fails.
        """
        if mac_address:
            self.flow_data[CONF_MAC] = (
                dr.format_mac(mac_address).replace(":", "").upper()
            )
        else:
            _LOGGER.debug("MAC not provided, attempting discovery for %s", ip_address)  # pragma: no mutate

            # Step 1: Try immediate resolution (cache check)
            discovered_mac = await async_get_mac_address(ip_address)

            if not discovered_mac:
                # Step 2: Force an ARP update via TCP attempt
                # Standard ARP resolution happens at the OS level during a connection attempt
                await self._async_force_arp_update(ip_address)
                # Step 3: Try resolution again immediately after traffic
                discovered_mac = await async_get_mac_address(ip_address)

            if discovered_mac:
                formatted_mac = dr.format_mac(discovered_mac)
                _LOGGER.info("MAC discovered via ARP: %s", formatted_mac)  # pragma: no mutate
                self.flow_data[CONF_MAC] = formatted_mac.replace(":", "").upper()
            else:
                _LOGGER.info("MAC auto-discovery failed. Requesting manual input.")  # pragma: no mutate
                return "mac_resolve_failed"

        await self.async_set_unique_id(self.flow_data[CONF_MAC])
        if not self.reauth_entry and self.source != "reconfigure":
            self._abort_if_unique_id_configured()

        return None

    async def _async_validate_cert_path(self, user_cert_path: str | None) -> bool:
        """Validate if the certificate file exists on disk."""
        if not user_cert_path:
            return True

        from .helpers import resolve_cert_path

        path_to_check = resolve_cert_path(
            user_cert_path, os.path.dirname(__file__), self.hass
        )
        if not path_to_check:
            return True
        return await self.hass.async_add_executor_job(os.path.exists, path_to_check)

    async def _initiate_pairing_safe(self) -> dict[str, Any]:
        """Async wrapper for the initiate_pairing phase with exception handling."""
        _LOGGER.debug("Executing safe wrapper: _initiate_pairing_safe")  # pragma: no mutate
        try:
            if self.acquirer is None:
                return {"ok": False, "error": "unknown_error"}

            successful_config = await self.acquirer.async_initiate_pairing()
            # fmt: off
            _LOGGER.debug('_initiate_pairing_safe successful with config: %s', successful_config)  # pragma: no mutate
            # fmt: on
            return {"ok": True, "config": successful_config}
        except (CannotConnect, AuthError, TokenAcquisitionError) as e:
            _LOGGER.warning("Connection error during pairing initiation: %s", e)  # pragma: no mutate
            return {"ok": False, "error": "cannot_connect"}
        except Exception as e:
            _LOGGER.error("Unexpected error during pairing: %s", e, exc_info=True)  # pragma: no mutate
            return {"ok": False, "error": "unknown_error"}

    async def _wait_token_safe(self) -> dict[str, Any]:
        """Async wrapper for the token acquisition phase with exception handling."""
        _LOGGER.debug("Executing safe wrapper: _wait_token_safe")  # pragma: no mutate
        try:
            if self.acquirer is None:
                return {"ok": False, "error": "unknown_error"}

            token = await self.acquirer.async_wait_for_token()
            _LOGGER.debug("_wait_token_safe successful, token acquired.")  # pragma: no mutate
            return {"ok": True, "token": token}
        except (TokenAcquisitionError, AuthTurnedOffError) as e:
            _LOGGER.warning("Token acquisition failed: %s", e)  # pragma: no mutate
            return {"ok": False, "error": "token_acquisition_failed"}
        except Exception as e:
            _LOGGER.error("Unknown error while waiting for token: %s", e, exc_info=True)  # pragma: no mutate
            return {"ok": False, "error": "unknown_error"}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """
        Step 1: The user chooses the device type.
        This is the main entry point for manual configuration.
        """
        if user_input is not None:
            self.flow_data[CONF_DEVICE_TYPE] = user_input[CONF_DEVICE_TYPE]
            device_type = self.flow_data[CONF_DEVICE_TYPE]

            if device_type == DEVICE_TYPE_SAMSUNG_2878:
                return await self.async_step_samsung_2878()

            if device_type in DEVICE_TYPE_8888_GROUP:
                return await self.async_step_samsung_8888()

            if device_type in [
                DEVICE_TYPE_SMARTTHINGS_HVAC,
                DEVICE_TYPE_SMARTTHINGS_DHW,
            ]:
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

    def _get_base_samsung_schema(
        self, mac_required: bool = False, is_8888: bool = False
    ) -> vol.Schema:
        """Helper to generate the shared configuration schema for all Samsung devices."""
        raw_mac = self.flow_data.get(CONF_MAC)
        formatted_mac = (
            ":".join(raw_mac[i : i + 2] for i in range(0, len(raw_mac), 2))
            if raw_mac
            else ""
        )

        try:
            interval_str = str(
                datetime.timedelta(
                    seconds=int(
                        self.flow_data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
                    )
                )
            )
        except (ValueError, TypeError):
            interval_str = str(self.flow_data.get(CONF_POLL_INTERVAL))

        schema_dict: dict[vol.Marker, Any] = {
            vol.Required(
                CONF_IP_ADDRESS, default=self.flow_data.get(CONF_IP_ADDRESS, "")
            ): str,
            (vol.Required if mac_required else vol.Optional)(
                CONF_MAC, default=formatted_mac
            ): str,
            vol.Optional(CONF_NAME, default=self.flow_data.get(CONF_NAME, "")): str,
            vol.Optional(CONF_TOKEN, default=self.flow_data.get(CONF_TOKEN, "")): str,
            vol.Optional(
                CONF_CERT,
                default=self.flow_data.get(CONF_CERT, "ac14k_m.pem" if is_8888 else ""),
            ): str,
            vol.Optional(CONF_POLL_INTERVAL, default=interval_str): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
        }

        if not is_8888:
            schema_dict[
                vol.Optional(
                    CONF_ENABLE_POLLING,
                    default=self.flow_data.get(
                        CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING
                    ),
                )
            ] = bool

        temp_selector = SelectSelector(
            SelectSelectorConfig(
                options=[UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
        schema_dict |= {
            vol.Optional(
                CONF_TEMP_NATIVE_CURRENT,
                default=self.flow_data.get(
                    CONF_TEMP_NATIVE_CURRENT, DEFAULT_CONF_TEMP_UNIT
                ),
            ): temp_selector,
            vol.Optional(
                CONF_TEMP_NATIVE_TARGET,
                default=self.flow_data.get(
                    CONF_TEMP_NATIVE_TARGET, DEFAULT_CONF_TEMP_UNIT
                ),
            ): temp_selector,
        }
        return vol.Schema(schema_dict)

    def _get_samsung_2878_schema(self, mac_required: bool = False) -> vol.Schema:
        """Return schema for older Samsung units."""
        return self._get_base_samsung_schema(mac_required=mac_required, is_8888=False)

    def _get_samsung_8888_schema(self, mac_required: bool = False) -> vol.Schema:
        """Return schema for modern Samsung units."""
        return self._get_base_samsung_schema(mac_required=mac_required, is_8888=True)

    def _validate_poll_interval(self, user_input: dict[str, Any]) -> int | None:
        """Extract and validate poll interval from user input."""
        if (val := user_input.get(CONF_POLL_INTERVAL)) is None:
            return None

        seconds = (
            int(val)
            if isinstance(val, (int, float))
            else int(cv.time_period_str(str(val)).total_seconds())
        )
        if not MIN_POLL_INTERVAL <= seconds <= MAX_POLL_INTERVAL:
            # fmt: off
            raise vol.Invalid(f'Interval must be between {MIN_POLL_INTERVAL} and {MAX_POLL_INTERVAL} seconds')  # pragma: no mutate
            # fmt: on

        return seconds

    async def _async_process_samsung_device_step(
        self, step_id: str, is_8888: bool, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Common logic for processing Samsung network configuration steps."""
        errors: dict[str, str] = {}
        schema_generator = (
            self._get_samsung_8888_schema if is_8888 else self._get_samsung_2878_schema
        )

        if user_input is not None:
            self.flow_data.update(user_input)

            # 1. MAC discovery
            error_reason = await self._async_resolve_mac_and_set_unique_id(
                self.flow_data[CONF_IP_ADDRESS], self.flow_data.get(CONF_MAC)
            )
            if error_reason:
                errors["base"] = error_reason
                return self.async_show_form(
                    step_id=step_id,
                    data_schema=schema_generator(
                        mac_required=error_reason == "mac_resolve_failed"
                    ),
                    errors=errors,
                )

            # 2. Validation of poll interval
            if CONF_POLL_INTERVAL in user_input:
                try:
                    seconds = self._validate_poll_interval(user_input)
                    if seconds is not None:
                        self.flow_data[CONF_POLL_INTERVAL] = seconds
                except (vol.Invalid, ValueError):
                    errors[CONF_POLL_INTERVAL] = "invalid_poll_interval"
                    return self.async_show_form(
                        step_id=step_id, data_schema=schema_generator(), errors=errors
                    )

            # 3. If token is already present (Reauth or manually entered), go to test
            if self.flow_data.get(CONF_TOKEN):
                return await self.async_step_test_connection()

            # 4. Check certificate path if provided
            if not await self._async_validate_cert_path(
                self.flow_data.get(CONF_CERT) or ""
            ):
                errors["base"] = "cert_not_found"
                return self.async_show_form(
                    step_id=step_id, data_schema=schema_generator(), errors=errors
                )

            # 5. Initialize the appropriate token acquirer
            if is_8888:
                self.acquirer = SamsungTokenAcquirer8888(
                    self.hass,
                    self.flow_data[CONF_IP_ADDRESS],
                    self.flow_data.get(CONF_CERT) or "ac14k_m.pem",
                )
            else:
                self.acquirer = SamsungTokenAcquirer(
                    self.hass,
                    self.flow_data[CONF_IP_ADDRESS],
                    self.flow_data.get(CONF_CERT),
                )

            return await self.async_step_initiate_pairing()

        return self.async_show_form(
            step_id=step_id, data_schema=schema_generator(), errors=errors
        )

    async def async_step_samsung_2878(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Process step for Port 2878 devices."""
        return await self._async_process_samsung_device_step(
            "samsung_2878", False, user_input
        )

    async def async_step_samsung_8888(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Process step for Port 8888 devices."""
        return await self._async_process_samsung_device_step(
            "samsung_8888", True, user_input
        )

    def _get_smartthings_token(self) -> str | None:
        """
        Attempt to automatically retrieve the token from the official SmartThings integration.
        This handles the case where the user already authorized HA via the official cloud component.
        """
        st_entries = self.hass.config_entries.async_entries("smartthings")
        if st_entries:
            # fmt: off
            _LOGGER.debug('Found official SmartThings config entry. Auto-filling access token.')  # pragma: no mutate
            # fmt: on
            # The official SmartThings integration stores the token as 'access_token'
            return st_entries[0].data.get("access_token")
        return None

    def _get_rest_api_schema(self) -> vol.Schema:
        """Generate the schema for REST API based devices that require manual token."""
        device_type = self.flow_data.get(CONF_DEVICE_TYPE)
        is_st = device_type in (
            DEVICE_TYPE_SMARTTHINGS_HVAC,
            DEVICE_TYPE_SMARTTHINGS_DHW,
        )

        try:
            interval_str = str(
                datetime.timedelta(
                    seconds=int(
                        self.flow_data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
                    )
                )
            )
        except (ValueError, TypeError):
            interval_str = str(self.flow_data.get(CONF_POLL_INTERVAL))

        default_token = self.flow_data.get(CONF_TOKEN) or (
            self._get_smartthings_token() if is_st else ""
        )

        schema: dict[vol.Marker, Any] = (
            {
                (
                    vol.Required(CONF_IP_ADDRESS, default="api.smartthings.com")
                    if is_st
                    else vol.Required(CONF_IP_ADDRESS)
                ): str,
            }
            | ({vol.Optional(CONF_DEVICE_ID): str} if is_st else {})
            | {
                vol.Required(CONF_TOKEN, default=default_token): str,
                vol.Optional(CONF_NAME): str,
                vol.Optional(CONF_POLL_INTERVAL, default=interval_str): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.TEXT)
                ),
            }
        )

        return vol.Schema(schema)

    async def async_step_rest_api(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle configuration for REST API devices with manual token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self.flow_data.update(user_input)

            # Sanitize manually-entered token to prevent injection via crafted strings.
            raw_token = self.flow_data.get(CONF_TOKEN)
            if raw_token:
                safe_token = sanitize_token(raw_token)
                if not safe_token:
                    errors[CONF_TOKEN] = "invalid_token_format"
                    return self.async_show_form(
                        step_id="rest_api",
                        data_schema=self._get_rest_api_schema(),
                        errors=errors,
                    )
                self.flow_data[CONF_TOKEN] = safe_token

            device_type = self.flow_data.get(CONF_DEVICE_TYPE)

            if device_type:
                self.flow_data[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE.get(
                    device_type
                )

            if CONF_POLL_INTERVAL in user_input:
                try:
                    seconds = self._validate_poll_interval(user_input)
                    if seconds is not None:
                        self.flow_data[CONF_POLL_INTERVAL] = seconds
                except (vol.Invalid, ValueError):
                    errors[CONF_POLL_INTERVAL] = "invalid_poll_interval"
                    return self.async_show_form(
                        step_id="rest_api",
                        data_schema=self._get_rest_api_schema(),
                        errors=errors,
                    )

            try:
                _LOGGER.debug("Testing lightweight REST API connection...")  # pragma: no mutate
                session = async_get_clientsession(self.hass)
                url = f"https://{self.flow_data.get(CONF_IP_ADDRESS)}/v1/devices"
                headers = {"Authorization": f"Bearer {self.flow_data.get(CONF_TOKEN)}"}

                async with session.get(
                    url, headers=headers, timeout=GLOBAL_HTTP_TIMEOUT
                ) as response:
                    if response.status != 200:
                        # fmt: off
                        _LOGGER.warning('REST API connection test failed with status %s', response.status)  # pragma: no mutate
                        # fmt: on
                        raise CannotConnect("HTTP Status Error")  # pragma: no mutate

                self.flow_data.update(user_input)
                unique_id = self.flow_data.get(CONF_DEVICE_ID) or self.flow_data.get(
                    CONF_MAC
                )
                if not unique_id:
                    # fmt: off
                    _LOGGER.error('REST API connection test failed: No MAC/Device ID available.')  # pragma: no mutate
                    # fmt: on
                    return self.async_abort(reason="no_mac_address_found")

                await self.async_set_unique_id(unique_id)
                if not self.reauth_entry:
                    self._abort_if_unique_id_configured()
                return await self._create_entry()

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected error during connection test")  # pragma: no mutate
                errors["base"] = "unknown_error"

        return self.async_show_form(
            step_id="rest_api",
            data_schema=self._get_rest_api_schema(),
            errors=errors,
        )

    async def async_step_initiate_pairing(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Phase 1: Put the device in pairing mode using a safe wrapper."""
        _LOGGER.debug("Entering async_step_initiate_pairing.")  # pragma: no mutate
        if not self.task:
            _LOGGER.debug("Creating task for _initiate_pairing_safe.")  # pragma: no mutate
            self.task = self.hass.async_create_task(self._initiate_pairing_safe())

        if self.task and self.task.done():
            result = self.task.result()
            self.task = None
            if result["ok"]:
                # fmt: off
                _LOGGER.debug('Pairing initiation successful, advancing to await_button.')  # pragma: no mutate
                # fmt: on
                successful_config = result.get("config")
                if successful_config:
                    self.flow_data["preferred_connection"] = successful_config
                    # fmt: off
                    _LOGGER.info('Successfully found working connection config, will save: %s', successful_config)  # pragma: no mutate
                    # fmt: on

                return self.async_show_progress_done(next_step_id="await_button")

            if not self.flow_data.get("_fallback_attempted"):
                self.flow_data["_fallback_attempted"] = True
                # fmt: off
                _LOGGER.info('Pairing initiation failed. Attempting automatic port fallback.')  # pragma: no mutate
                # fmt: on

                device_type = self.flow_data.get(CONF_DEVICE_TYPE)
                ip_address = self.flow_data.get(CONF_IP_ADDRESS)
                cert_path = self.flow_data.get(CONF_CERT)

                if device_type == DEVICE_TYPE_SAMSUNG_2878:
                    # fmt: off
                    _LOGGER.info('Falling back from port %s to port %s topology.', PORT_SAMSUNG_2878, PORT_SAMSUNG_8888)  # pragma: no mutate
                    # fmt: on
                    self.flow_data[CONF_DEVICE_TYPE] = DEVICE_TYPE_SAMSUNG_8888
                    if not cert_path:
                        self.flow_data[CONF_CERT] = "ac14k_m.pem"
                    self.acquirer = SamsungTokenAcquirer8888(
                        self.hass, str(ip_address), str(self.flow_data.get(CONF_CERT))
                    )
                elif device_type == DEVICE_TYPE_SAMSUNG_8888:
                    # fmt: off
                    _LOGGER.info('Falling back from port %s to port %s topology.', PORT_SAMSUNG_8888, PORT_SAMSUNG_2878)  # pragma: no mutate
                    # fmt: on
                    self.flow_data[CONF_DEVICE_TYPE] = DEVICE_TYPE_SAMSUNG_2878
                    self.acquirer = SamsungTokenAcquirer(
                        self.hass, str(ip_address), cert_path
                    )

                self.task = self.hass.async_create_task(self._initiate_pairing_safe())
                return self.async_show_progress(
                    step_id="initiate_pairing",
                    progress_action="initiating_pairing",
                    progress_task=self.task,
                )

            self.flow_data["error_key"] = result["error"]
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
        if not self.task:
            _LOGGER.debug("Creating task for _wait_token_safe.")  # pragma: no mutate
            self.task = self.hass.async_create_task(self._wait_token_safe())

        if self.task and self.task.done():
            result = self.task.result()
            self.task = None
            if result["ok"]:
                raw_token = result["token"]
                safe_token = sanitize_token(raw_token)
                if not safe_token:
                    # fmt: off
                    _LOGGER.error('Acquired token was rejected by sanitizer — aborting pairing. This may indicate a compromised or malformed AC response.')  # pragma: no mutate
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

            self.flow_data["error_key"] = result["error"]
            return self.async_show_progress_done(next_step_id="handle_error")

        if self.flow_data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_MIM_H03:
            progress_action = "awaiting_ap_button_press"
        else:
            progress_action = "awaiting_button_press"

        return self.async_show_progress(
            step_id="await_button",
            progress_action=progress_action,
            progress_task=self.task,
            description_placeholders={
                "ip_address": self.flow_data.get(CONF_IP_ADDRESS)
            },
        )

    # pylint: disable=too-many-locals,too-many-branches
    async def _test_connection_safe(self) -> dict[str, Any]:
        """Safe and lightweight wrapper for testing the connection."""
        _LOGGER.debug("Executing lightweight connection test: _test_connection_safe")  # pragma: no mutate
        try:
            device_type = self.flow_data.get(CONF_DEVICE_TYPE)
            ip_address = self.flow_data.get(CONF_IP_ADDRESS)
            token = self.flow_data.get(CONF_TOKEN)

            if device_type in DEVICE_TYPE_8888_GROUP:
                session = async_get_clientsession(self.hass)
                url = f"https://{ip_address}:{PORT_SAMSUNG_8888}/devices"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }

                ssl_context = ssl.create_default_context()
                cert_path = self.flow_data.get(CONF_CERT)
                if cert_path:
                    # pylint: disable=import-outside-toplevel
                    from .helpers import resolve_cert_path

                    full_path = resolve_cert_path(cert_path, os.path.dirname(__file__))
                    if full_path and os.path.exists(full_path):
                        ssl_context.load_verify_locations(cafile=full_path)
                else:
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

                async with session.get(
                    url, headers=headers, ssl=ssl_context, timeout=GLOBAL_HTTP_TIMEOUT
                ) as response:
                    if response.status == 200:
                        _LOGGER.debug("Lightweight 8888 connection test successful.")  # pragma: no mutate
                        return {"ok": True}

                    # fmt: off
                    _LOGGER.warning('8888 connection test failed with status: %s', response.status)  # pragma: no mutate
                    # fmt: on
                    return {"ok": False, "error": "cannot_connect"}

            elif device_type == DEVICE_TYPE_SAMSUNG_2878:
                config_data = self.flow_data.copy()
                config_data.setdefault("unique_id", config_data.get(CONF_MAC))

                if not config_data.get(CONF_CONFIG_FILE) and device_type:
                    config_data[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE.get(
                        device_type
                    )

                controller = YamlController(config=config_data, logger=_LOGGER)
                controller.hass = self.hass
                # pylint: disable=protected-access
                controller._session = async_get_clientsession(self.hass)

                if not await controller.initialize():
                    return {"ok": False, "error": "cannot_connect"}

                if controller.loader and controller.loader.state_getter:
                    state_data = (
                        await controller.loader.state_getter.async_update_state(
                            None, False
                        )
                    )
                else:
                    state_data = None
                await controller.async_shutdown()

                return {"ok": state_data is not None}

            else:
                # fmt: off
                _LOGGER.error('Unknown device type for connection test: %s', device_type)  # pragma: no mutate
                # fmt: on
                return {"ok": False, "error": "cannot_connect"}

        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Unknown error during connection test: %s", e, exc_info=True)  # pragma: no mutate
            return {"ok": False, "error": "cannot_connect"}

    # pylint: disable=unused-argument
    async def async_step_test_connection(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Phase to validate the IP and token."""
        _LOGGER.debug("Entering async_step_test_connection.")  # pragma: no mutate
        if not self.task:
            _LOGGER.debug("Creating task for _test_connection_safe.")  # pragma: no mutate
            self.task = self.hass.async_create_task(self._test_connection_safe())

        if self.task and self.task.done():
            result = self.task.result()
            self.task = None
            if result.get("ok"):
                _LOGGER.debug("Connection test successful, advancing to discovery.")  # pragma: no mutate
                if self.flow_data.get(
                    CONF_DEVICE_TYPE
                ) != DEVICE_TYPE_SAMSUNG_2878 and not self.flow_data.get(
                    CONF_DEVICE_ID
                ):
                    return self.async_show_progress_done(next_step_id="discover_uuid")
                return self.async_show_progress_done(next_step_id="create_entry")

            self.flow_data.pop(CONF_TOKEN, None)
            self.flow_data["error_key"] = result.get("error", "cannot_connect")
            return self.async_show_progress_done(next_step_id="handle_error")

        return self.async_show_progress(
            step_id="test_connection",
            progress_action="testing_connection",
            progress_task=self.task,
            description_placeholders={
                "ip_address": self.flow_data.get(CONF_IP_ADDRESS)
            },
        )

    # pylint: disable=too-many-return-statements,too-many-branches,too-many-statements,unused-argument
    async def async_step_discover_uuid(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Step to discover indoor units from the device."""
        config_data = self.flow_data.copy()
        if self.unique_id:
            config_data["unique_id"] = self.unique_id

        device_type = config_data.get(CONF_DEVICE_TYPE)
        if not config_data.get(CONF_CONFIG_FILE) and device_type:
            config_data[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE.get(device_type)

        controller = None  # pragma: no mutate
        try:
            # CRITICAL: hass and session MUST be passed as explicit kwargs, not via
            # config_data.update(). YamlController.__init__ pops them from the dict
            # but only assigns them from the named parameters (default=None).
            controller = YamlController(
                config=config_data,
                logger=_LOGGER,
                hass=self.hass,
                session=async_get_clientsession(self.hass),
            )
            if (
                not await controller.initialize()
                or not await controller.async_get_status()
            ):
                _LOGGER.error("Failed to initialize or get status during discovery.")  # pragma: no mutate
                return self.async_abort(reason="cannot_connect")

            discovered_devices_raw = controller.discovered_devices

            if (
                not isinstance(discovered_devices_raw, list)
                or not discovered_devices_raw
            ):
                # fmt: off
                _LOGGER.warning('Could not discover indoor units. Creating a single entry.')  # pragma: no mutate
                # fmt: on
                if controller.unique_id:
                    await self.async_set_unique_id(
                        controller.unique_id, raise_on_progress=False
                    )
                    if controller.device_id:
                        self.flow_data[CONF_DEVICE_ID] = controller.device_id
                    if not self.reauth_entry:
                        self._abort_if_unique_id_configured(updates=self.flow_data)
                return await self._create_entry()

            discovered_devices = list(discovered_devices_raw)
            _LOGGER.debug("Discovered devices for %s: %s", device_type, discovered_devices)  # pragma: no mutate

            if device_type == DEVICE_TYPE_MIM_H03:
                internal_coordinator = None
                ac_units_info = []
                for device in discovered_devices:
                    if not isinstance(device, dict):
                        continue

                    device_id = device.get("id")

                    # Explicitly identify coordinator (ID 0 or missing Mode)
                    # We prefer ID 0 if multiple candidates exist.
                    if device_id == "0" or "Mode" not in device:
                        if internal_coordinator is None or device_id == "0":
                            internal_coordinator = device
                        continue

                    # Everything else is an AC unit
                    name = device.get("name") or f"Indoor Unit {device_id}"
                    display_name = f"ID {device_id} ({name})"

                    ac_units_info.append(
                        {
                            "id": device_id,
                            "uuid": device.get("uuid"),
                            "name": display_name,
                            "description": device.get(
                                "description",
                                name,
                            ),
                        }
                    )

                if internal_coordinator:
                    coordinator_uuid = internal_coordinator.get("uuid")
                    if coordinator_uuid:
                        await self.async_set_unique_id(
                            coordinator_uuid, raise_on_progress=False
                        )
                        self.flow_data.update(
                            {
                                "unique_id": coordinator_uuid,
                                CONF_DEVICE_ID: internal_coordinator.get("id"),
                                CONF_NAME: (
                                    f"{internal_coordinator.get('name', 'MIM-H03 Coordinator')} "
                                    f"{coordinator_uuid}"
                                ),
                            }
                        )
                        if not self.reauth_entry:
                            self._abort_if_unique_id_configured(updates=self.flow_data)
                        if ac_units_info:
                            self.flow_data[CONF_DISCOVERED_DEVICES] = ac_units_info
                            return await self.async_step_select_devices()
                        return await self._create_entry()
                    return self.async_abort(reason="no_coordinator_uuid")
                return self.async_abort(reason="no_coordinator_found")

            if device_type == DEVICE_TYPE_SAMSUNG_8888:
                if device_uuid := (
                    discovered_devices[0].get("uuid")
                    or discovered_devices[0].get("id")
                ):
                    self.flow_data.update(
                        {
                            CONF_DEVICE_ID: device_uuid,
                            CONF_NAME: f"Samsung AC {self.flow_data.get(CONF_MAC)}",
                        }
                    )
                    return await self._create_entry()
                return self.async_abort(reason="discovery_failed")

            devices_info = [
                {
                    "id": d.get("id") or str(d),
                    "uuid": d.get("uuid"),
                    "name": d.get("name", f"Indoor Unit {d.get('id') or str(d)}"),
                    "description": d.get(
                        "description",
                        d.get("name", f"Indoor Unit {d.get('id') or str(d)}"),
                    ),
                }
                for d in discovered_devices
                if isinstance(d, dict)
            ]

            if not devices_info:
                return await self._create_entry()

            self.flow_data[CONF_DISCOVERED_DEVICES] = devices_info
            return await self.async_step_select_devices()

        except InvalidHeaderError:
            # The device sends malformed HTTP headers — aiohttp cannot handle them.
            # Automatically switch to the raw socket engine and retry, exactly as the
            # coordinator does post-setup. We do NOT abort the flow.
            # fmt: off
            _LOGGER.warning("[%s] Malformed HTTP headers detected during discovery. Automatically retrying with 'Robust (raw socket)' engine.", self.unique_id or '?')  # pragma: no mutate
            # fmt: on
            if controller:
                await controller.async_shutdown()
                controller = None  # pragma: no mutate

            # Persist the engine switch so it survives into the created entry.
            self.flow_data[CONF_CONN_METHOD] = CONN_METHOD_RAW
            config_data[CONF_CONN_METHOD] = CONN_METHOD_RAW

            try:
                controller = YamlController(
                    config=config_data,
                    logger=_LOGGER,
                    hass=self.hass,
                    session=async_get_clientsession(self.hass),
                )
                if (
                    not await controller.initialize()
                    or not await controller.async_get_status()
                ):
                    # fmt: off
                    _LOGGER.error('Failed to initialize with raw engine during discovery fallback.')  # pragma: no mutate
                    # fmt: on
                    return self.async_abort(reason="cannot_connect")
            except Exception as raw_exc:  # pylint: disable=broad-exception-caught
                _LOGGER.exception("Raw-engine fallback also failed: %s", raw_exc)  # pragma: no mutate
                return self.async_abort(reason="cannot_connect")
            return await self._create_entry()

        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.exception("Discovery failed: %s", e)  # pragma: no mutate
            return self.async_abort(reason="unknown_error")
        finally:
            if controller:
                await controller.async_shutdown()

    async def async_step_select_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow the user to select which indoor units to add."""
        discovered_devices = self.flow_data.get(CONF_DISCOVERED_DEVICES, [])
        device_options = {
            device["id"]: device.get("name", "Unknown Device")
            for device in discovered_devices
        }

        if user_input is not None:
            selected_devices_ids = user_input.get(CONF_SELECTED_DEVICES, [])
            if not selected_devices_ids:
                return self.async_show_form(
                    step_id="select_devices",
                    data_schema=vol.Schema(
                        {
                            vol.Required(
                                CONF_SELECTED_DEVICES,
                                default=list(device_options.keys()),
                            ): cv.multi_select(device_options)
                        }
                    ),
                    errors={"base": "no_devices_selected"},
                    description_placeholders={"device_count": len(discovered_devices)},
                )

            self.flow_data[CONF_DEVICES] = [
                d for d in discovered_devices if d["id"] in selected_devices_ids
            ]
            main_unique_id = (
                self.flow_data.get("unique_id")
                or self.flow_data.get(CONF_MAC)
                or self.flow_data.get(CONF_DEVICE_ID)
            )

            if main_unique_id:
                await self.async_set_unique_id(main_unique_id, raise_on_progress=False)
                if not self.reauth_entry:
                    self._abort_if_unique_id_configured(updates=self.flow_data)
                return await self._create_entry()
            return self.async_abort(reason="no_unique_id")

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SELECTED_DEVICES, default=list(device_options.keys())
                ): cv.multi_select(device_options)
            }
        )

        return self.async_show_form(
            step_id="select_devices",
            data_schema=schema,
            description_placeholders={"device_count": len(discovered_devices)},
        )

    # pylint: disable=unused-argument
    async def async_step_handle_error(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Handles the display of errors after a progress step fails."""
        error_key = self.flow_data.pop("error_key", "unknown_error")
        device_type = self.flow_data.get(CONF_DEVICE_TYPE)

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
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema_generator(),
            errors={"base": error_key},
        )

    # pylint: disable=unused-argument
    async def async_step_create_entry(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Final invisible step that creates the config entry."""
        return await self._create_entry()

    async def _create_entry(self) -> ConfigFlowResult:
        """Create the config entry and finish the flow."""
        device_type = self.flow_data.get(CONF_DEVICE_TYPE)
        final_unique_id = self.flow_data.get("unique_id") or self.flow_data.get(
            CONF_MAC
        )

        if not final_unique_id:
            return self.async_abort(reason="no_mac_address_found")

        await self.async_set_unique_id(final_unique_id)
        if not self.reauth_entry and self.source != "reconfigure":
            self._abort_if_unique_id_configured(updates=self.flow_data)
        self.flow_data["unique_id"] = final_unique_id

        title = self.flow_data.get(CONF_NAME)

        if not title or not title.strip():
            title = f"Samsung AC {final_unique_id}"
            self.flow_data[CONF_NAME] = title
        elif (
            device_type in [DEVICE_TYPE_SAMSUNG_8888, DEVICE_TYPE_MIM_H03]
            and final_unique_id not in title
        ):
            title = f"{title} ({final_unique_id})"

        # Strip transient flow keys that must not end up in the ConfigEntry storage.
        # CONF_DISCOVERED_DEVICES is the full candidate list shown in the UI selector.
        # CONF_SELECTED_DEVICES is the user's checkbox selection.
        # Only CONF_DEVICES (the filtered, confirmed list) is meaningful at runtime.
        transient_keys = (CONF_DISCOVERED_DEVICES, CONF_SELECTED_DEVICES)

        # Handle Reauthentication Update
        if self.reauth_entry:
            _LOGGER.debug("Re-auth successful. Updating config entry.")  # pragma: no mutate
            entry_data = {k: v for k, v in self.flow_data.items() if k not in transient_keys}
            self.hass.config_entries.async_update_entry(
                self.reauth_entry, data=entry_data
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.reauth_entry.entry_id)
            )
            return self.async_abort(reason="reauth_successful")

        # Handle Reconfigure Update
        if self.source == "reconfigure":
            # fmt: off
            _LOGGER.debug('Reconfigure successful via pairing flow. Updating config entry.')  # pragma: no mutate
            # fmt: on
            reconfigure_entry = self._get_reconfigure_entry()
            entry_data = {k: v for k, v in self.flow_data.items() if k not in transient_keys}
            updated_data = {**reconfigure_entry.data, **entry_data}
            self.hass.config_entries.async_update_entry(
                reconfigure_entry, data=updated_data
            )
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(reconfigure_entry.entry_id)
            )
            return self.async_abort(reason="reconfigure_successful")

        entry_data = {k: v for k, v in self.flow_data.items() if k not in transient_keys}
        return self.async_create_entry(title=title, data=entry_data)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication failure from the integration."""
        _LOGGER.debug("Entering async_step_reauth with data: %s", entry_data)  # pragma: no mutate
        self.reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )

        # Pre-fill flow_data with existing entry data
        if self.reauth_entry:
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
            # FORCE NEW PAIRING: Clear the old token so the process acquires a fresh one
            self.flow_data.pop(CONF_TOKEN, None)

            device_type = self.flow_data.get(CONF_DEVICE_TYPE)
            if device_type in [
                DEVICE_TYPE_SMARTTHINGS_HVAC,
                DEVICE_TYPE_SMARTTHINGS_DHW,
            ]:
                return await self.async_step_rest_api()

            return (
                await self.async_step_samsung_2878()
                if device_type == DEVICE_TYPE_SAMSUNG_2878
                else await self.async_step_samsung_8888()
            )

        name = self.reauth_entry.title if self.reauth_entry else "Unknown Device"
        return self.async_show_form(
            step_id="reauth_confirm",
            description_placeholders={"device_name": name},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

    # ------------------------------------------------------------------
    # Reconfiguration flow (HA 2024.11+ Gold requirement)
    # Allows changing IP, token, cert and MAC without deleting the entry.
    # ------------------------------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a reconfiguration flow initiated by the user.

        Pre-fills the form with the current entry values so only changed
        fields need to be re-entered.  After validation the config entry is
        updated in-place and the integration is reloaded.
        """
        reconfigure_entry = self._get_reconfigure_entry()
        # Seed flow_data from the existing entry so defaults are correct.
        if not self.flow_data:
            self.flow_data = dict(reconfigure_entry.data)

        return await self.async_step_reconfigure_confirm(user_input)

    async def async_step_reconfigure_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the reconfiguration form and process its submission."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        device_type = self.flow_data.get(
            CONF_DEVICE_TYPE
        ) or reconfigure_entry.data.get(CONF_DEVICE_TYPE)

        # Build a focused schema that only exposes identity/connectivity fields.
        is_8888 = (
            device_type in DEVICE_TYPE_8888_GROUP or device_type == DEVICE_TYPE_MIM_H03
        )
        raw_mac = self.flow_data.get(CONF_MAC, "")
        formatted_mac = (
            ":".join(raw_mac[i : i + 2] for i in range(0, len(raw_mac), 2))
            if raw_mac
            else ""
        )

        base_schema = vol.Schema(
            {
                vol.Required(CONF_IP_ADDRESS): str,
                vol.Optional(CONF_MAC): str,
                vol.Optional(CONF_TOKEN): str,
                vol.Optional(CONF_CERT): str,
            }
        )

        schema = self.add_suggested_values_to_schema(
            base_schema,
            {
                CONF_IP_ADDRESS: self.flow_data.get(CONF_IP_ADDRESS, ""),
                CONF_MAC: formatted_mac,
                CONF_TOKEN: self.flow_data.get(CONF_TOKEN, ""),
                CONF_CERT: self.flow_data.get(
                    CONF_CERT, "ac14k_m.pem" if is_8888 else ""
                ),
            },
        )

        if user_input is not None:
            self.flow_data[CONF_IP_ADDRESS] = user_input.get(CONF_IP_ADDRESS, "")
            self.flow_data[CONF_MAC] = user_input.get(CONF_MAC, "")
            self.flow_data[CONF_TOKEN] = user_input.get(CONF_TOKEN, "")
            self.flow_data[CONF_CERT] = user_input.get(CONF_CERT, "")

            # Validate/resolve MAC only if appropriate for device type
            if device_type not in [
                DEVICE_TYPE_SMARTTHINGS_HVAC,
                DEVICE_TYPE_SMARTTHINGS_DHW,
            ]:
                error_reason = await self._async_resolve_mac_and_set_unique_id(
                    self.flow_data[CONF_IP_ADDRESS],
                    self.flow_data.get(CONF_MAC),
                )
                if error_reason:
                    errors["base"] = error_reason
                    # Hallazgo 2: re-format MAC for display before re-rendering on error
                    raw_mac_err = self.flow_data.get(CONF_MAC, "")
                    formatted_mac_err = (
                        ":".join(
                            raw_mac_err[i : i + 2]
                            for i in range(0, len(raw_mac_err), 2)
                        )
                        if raw_mac_err and ":" not in raw_mac_err
                        else raw_mac_err
                    )
                    error_suggested = {
                        CONF_IP_ADDRESS: self.flow_data.get(CONF_IP_ADDRESS, ""),
                        CONF_MAC: formatted_mac_err,
                        CONF_TOKEN: self.flow_data.get(CONF_TOKEN, ""),
                        CONF_CERT: self.flow_data.get(CONF_CERT, ""),
                    }
                    return self.async_show_form(
                        step_id="reconfigure_confirm",
                        data_schema=self.add_suggested_values_to_schema(
                            base_schema, error_suggested
                        ),
                        errors=errors,
                    )

            # Hallazgo 8: Warn when cert is deliberately cleared during reconfigure
            cert_value = self.flow_data.get(CONF_CERT, "")
            if not cert_value:
                # fmt: off
                _LOGGER.warning("Reconfigure: certificate path was cleared for entry '%s'. The connection will operate without a client certificate.", reconfigure_entry.title)  # pragma: no mutate
                # fmt: on

            # Validate cert path if provided
            if not await self._async_validate_cert_path(cert_value):
                errors["base"] = "cert_not_found"
                return self.async_show_form(
                    step_id="reconfigure_confirm",
                    data_schema=schema,
                    errors=errors,
                )

            # If token is totally blanked out during reconfigure, run auto-discovery
            if not self.flow_data.get(CONF_TOKEN) and device_type not in [
                DEVICE_TYPE_SMARTTHINGS_HVAC,
                DEVICE_TYPE_SMARTTHINGS_DHW,
            ]:
                # fmt: off
                _LOGGER.info('Token absent during reconfigure. Setting up acquirer for discovery.')  # pragma: no mutate
                # fmt: on
                if (
                    device_type in DEVICE_TYPE_8888_GROUP
                    or device_type == DEVICE_TYPE_MIM_H03
                ):
                    self.acquirer = SamsungTokenAcquirer8888(
                        self.hass,
                        self.flow_data[CONF_IP_ADDRESS],
                        self.flow_data.get(CONF_CERT) or "ac14k_m.pem",
                    )
                else:
                    self.acquirer = SamsungTokenAcquirer(
                        self.hass,
                        self.flow_data[CONF_IP_ADDRESS],
                        self.flow_data.get(CONF_CERT) or "",
                    )
                return await self.async_step_initiate_pairing()

            # Merge updated identity fields into the existing entry data.
            updated_data = {**reconfigure_entry.data, **self.flow_data}
            self.hass.config_entries.async_update_entry(
                reconfigure_entry, data=updated_data
            )
            # fmt: off
            _LOGGER.info("Reconfigure: updated entry '%s' with new connectivity parameters.", reconfigure_entry.title)  # pragma: no mutate
            # fmt: on
            await self.hass.config_entries.async_reload(reconfigure_entry.entry_id)
            return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "device_name": reconfigure_entry.title,
                "ip_address": reconfigure_entry.data.get(CONF_IP_ADDRESS, ""),
            },
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
        if user_input is not None:
            # Polling Interval Validation
            if CONF_POLL_INTERVAL in user_input:
                try:
                    val = user_input[CONF_POLL_INTERVAL]
                    seconds = (
                        int(val)
                        if isinstance(val, (int, float))
                        else int(cv.time_period_str(str(val)).total_seconds())
                    )
                    if seconds < MIN_POLL_INTERVAL:
                        raise vol.Invalid(f"Min: {MIN_POLL_INTERVAL}s")  # pragma: no mutate
                    if seconds > MAX_POLL_INTERVAL:
                        raise vol.Invalid(f"Max: {MAX_POLL_INTERVAL}s")  # pragma: no mutate
                    user_input[CONF_POLL_INTERVAL] = seconds
                except (vol.Invalid, ValueError):
                    return self.async_show_form(
                        step_id="init",
                        data_schema=self._get_options_schema(),
                        errors={CONF_POLL_INTERVAL: "invalid_poll_interval"},
                    )

            if CONF_TARGET_TEMP_STEP in user_input:
                try:
                    user_input[CONF_TARGET_TEMP_STEP] = float(user_input[CONF_TARGET_TEMP_STEP])
                except (ValueError, TypeError):
                    user_input[CONF_TARGET_TEMP_STEP] = DEFAULT_TARGET_TEMP_STEP

            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init", data_schema=self._get_options_schema()
        )

    def _get_options_schema(self) -> vol.Schema:
        """Return the schema for the options flow."""
        schema_dict: dict[vol.Marker, Any] = {}

        if (
            self._config_entry.data.get(CONF_DEVICE_TYPE)
            in DEVICE_TYPE_AIOHTTP_SUPPORTED
        ):
            schema_dict[
                vol.Required(
                    CONF_CONN_METHOD,
                    default=self._config_entry.options.get(
                        CONF_CONN_METHOD,
                        self._config_entry.data.get(
                            CONF_CONN_METHOD, CONN_METHOD_AIOHTTP
                        ),
                    ),
                )
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        {"value": CONN_METHOD_REQUESTS, "label": "Legacy (Obsolete)"},
                        {"value": CONN_METHOD_AIOHTTP, "label": "Modern (aiohttp)"},
                        {"value": CONN_METHOD_RAW, "label": "Robust (raw socket)"},
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="connection_method",
                )
            )

        current_val = self._config_entry.options.get(
            CONF_POLL_INTERVAL,
            self._config_entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        )
        try:
            current_str = str(datetime.timedelta(seconds=int(current_val)))
        except (ValueError, TypeError):
            current_str = str(current_val)

        temp_selector = SelectSelector(
            SelectSelectorConfig(
                options=[UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )

        schema_dict |= {
            vol.Required(CONF_POLL_INTERVAL, default=current_str): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
            vol.Required(
                CONF_TEMP_NATIVE_CURRENT,
                default=self._config_entry.options.get(
                    CONF_TEMP_NATIVE_CURRENT, DEFAULT_CONF_TEMP_UNIT
                ),
            ): temp_selector,
            vol.Required(
                CONF_TEMP_NATIVE_TARGET,
                default=self._config_entry.options.get(
                    CONF_TEMP_NATIVE_TARGET, DEFAULT_CONF_TEMP_UNIT
                ),
            ): temp_selector,
            vol.Optional(
                CONF_ENABLE_POLLING,
                default=self._config_entry.options.get(
                    CONF_ENABLE_POLLING, DEFAULT_ENABLE_POLLING
                ),
            ): bool,
            vol.Required(
                CONF_TARGET_TEMP_STEP,
                default=str(self._config_entry.options.get(
                    CONF_TARGET_TEMP_STEP,
                    self._config_entry.data.get(
                        CONF_TARGET_TEMP_STEP, DEFAULT_TARGET_TEMP_STEP
                    ),
                )),
            ): SelectSelector(
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
