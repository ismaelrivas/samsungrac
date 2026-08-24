# pylint: disable=broad-exception-caught,import-outside-toplevel,unused-argument
# custom_components/climate_ip/config_flow.py
"""Config flow for the Climate IP integration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Self

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import aiohttp_client, device_registry as dr
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util.yaml import load_yaml
import voluptuous as vol

from . import helpers
from .config_flow_discovery import ConfigFlowDiscoveryMixin
from .config_flow_helpers import ConfigFlowHelpersMixin
from .config_flow_schemas import ConfigFlowSchemasMixin
from .const import (
    CONF_CERT,
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_DISCOVERED_DEVICES,
    CONF_POLL_INTERVAL,
    CONF_SELECTED_DEVICES,
    CONFIG_DEVICE_NAME,
    CONFIG_ENTRY_VERSION,
    CONFIG_FILE_TO_DEVICE_TYPE,
    DEFAULT_CONF_CERT_FILE,
    DEVICE_TYPE_8888_GROUP,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DEVICE_TYPE_TO_CONFIG_FILE,
    DOMAIN,
    GLOBAL_HTTP_TIMEOUT,
)
from .exceptions import CannotConnect
from .options_flow import OptionsFlowHandler
from .token_acquirer_yaml import GenericYamlTokenAcquirer

# Backward compatibility aliases for unit tests
SamsungTokenAcquirer = GenericYamlTokenAcquirer
SamsungTokenAcquirer8888 = GenericYamlTokenAcquirer

_LOGGER = logging.getLogger(__name__)


class ClimateIpConfigFlow(
    ConfigFlowSchemasMixin,
    ConfigFlowHelpersMixin,
    ConfigFlowDiscoveryMixin,
    ConfigFlow,
    domain=DOMAIN,
):
    """Config flow implementing a robust, multi-step pairing process.

    Supports legacy Samsung ACs (2878), modern units (8888),
    MIM-H03 heatpumps and SmartThings cloud devices.
    """

    VERSION = CONFIG_ENTRY_VERSION

    def __init__(self) -> None:
        """Initialize the config flow variables."""
        self.flow_data: dict[str, Any] = {}  # pragma: no mutate
        self.task: asyncio.Task[Any] | None = None
        self.acquirer: Any | None = None
        self.reauth_entry: ConfigEntry | None = None  # pragma: no mutate

        _LOGGER.debug(
            "Initializing new Climate IP config flow handler."
        )  # pragma: no mutate

    async def _load_auth_flow_config(self, device_type: str) -> dict[str, Any]:
        """Dynamically load the authentication YAML file according to device type."""
        main_yaml_name = DEVICE_TYPE_TO_CONFIG_FILE.get(device_type)
        if not main_yaml_name:
            raise ValueError(
                f"No configuration file mapping found for device_type: {device_type}"
            )
        main_yaml_path = str(Path(__file__).parent / main_yaml_name)
        main_config = await self.hass.async_add_executor_job(load_yaml, main_yaml_path)
        if not isinstance(main_config, dict):
            raise ValueError(f"Invalid YAML configuration loaded from {main_yaml_name}")

        auth_file = (
            main_config.get("device", {}).get("auth_flow_file")
            if isinstance(main_config.get("device"), dict)
            else None
        )
        if not auth_file:
            raise ValueError(f"No 'auth_flow_file' found in {main_yaml_name}")

        auth_yaml_path = str(Path(__file__).parent / auth_file)
        auth_config = await self.hass.async_add_executor_job(load_yaml, auth_yaml_path)
        if not isinstance(auth_config, dict):
            raise ValueError(f"Invalid YAML configuration loaded from {auth_file}")
        auth_flow = auth_config.get("auth_flow", {})
        return auth_flow if isinstance(auth_flow, dict) else {}

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

        if self_mac and other_mac and str(self_mac).upper() == str(other_mac).upper():
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
                    seconds = helpers.validate_poll_interval(
                        user_input[CONF_POLL_INTERVAL]
                    )
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

            # 5. Initialize the generic token acquirer dynamically
            device_type = self.flow_data.get(
                CONF_DEVICE_TYPE,
                DEVICE_TYPE_SAMSUNG_8888 if is_8888 else DEVICE_TYPE_SAMSUNG_2878,
            )
            target_cert = str(cert_val) if cert_val else None  # pragma: no mutate

            auth_flow_dict = await self._load_auth_flow_config(device_type)

            self.acquirer = GenericYamlTokenAcquirer(
                self.hass,
                ip_address=ip_addr,
                auth_config=auth_flow_dict,
                cert_path=target_cert,
            )

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

    async def async_step_rest_api(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle configuration for REST API devices with manual token."""
        errors: dict[str, str] = {}
        if user_input:
            self.flow_data.update(user_input)

            raw_token = self.flow_data.get(CONF_TOKEN)
            if raw_token:
                safe_token = helpers.sanitize_token(str(raw_token))
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
                    seconds = helpers.validate_poll_interval(
                        user_input[CONF_POLL_INTERVAL]
                    )
                    self.flow_data[CONF_POLL_INTERVAL] = seconds
                except ValueError:
                    errors[CONF_POLL_INTERVAL] = (
                        "invalid_poll_interval"  # pragma: no mutate
                    )
                    step_id_err2 = "rest_api"  # pragma: no mutate
                    schema_err2 = self._get_rest_api_schema()  # pragma: no mutate
                    return self.async_show_form(
                        step_id=step_id_err2, data_schema=schema_err2, errors=errors
                    )

            try:
                _LOGGER.debug(
                    "Testing lightweight REST API connection..."
                )  # pragma: no mutate
                session = aiohttp_client.async_get_clientsession(self.hass)
                ip_addr = str(self.flow_data[CONF_IP_ADDRESS])
                host_str = (
                    f"[{ip_addr}]" if ":" in ip_addr else ip_addr
                )  # pragma: no mutate
                url = f"https://{host_str}/v1/devices"
                headers = {
                    "Authorization": f"Bearer {self.flow_data.get(CONF_TOKEN)}"
                }  # pragma: no mutate

                async with session.get(
                    url,
                    headers=headers,
                    timeout=GLOBAL_HTTP_TIMEOUT,  # type: ignore[arg-type] # pragma: no mutate
                ) as response:  # pragma: no mutate
                    if response.status != 200:
                        _LOGGER.warning(
                            "REST API connection test failed..."
                        )  # pragma: no mutate
                        raise CannotConnect("HTTP Status Error")  # pragma: no mutate

                unique_id = str(
                    self.flow_data.get(CONF_DEVICE_ID)
                    or self.flow_data.get(CONF_MAC)
                    or ""  # pragma: no mutate
                )
                if not unique_id:
                    _LOGGER.error(
                        "REST API connection test failed..."
                    )  # pragma: no mutate
                    return self.async_abort(reason="no_mac_address_found")

                await self.async_set_unique_id(unique_id)
                if self.reauth_entry is None:
                    self._abort_if_unique_id_configured()
                return await self._create_entry()

            except AbortFlow:
                raise
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
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
                cert_path = str(self.flow_data.get(CONF_CERT, ""))  # pragma: no mutate

                if device_type == DEVICE_TYPE_SAMSUNG_2878:
                    # fmt: off
                    _LOGGER.info('Falling back from port %s to port %s topology.', 2878, 8888)  # pragma: no mutate
                    # fmt: on
                    self.flow_data[CONF_DEVICE_TYPE] = DEVICE_TYPE_SAMSUNG_8888
                    target_cert = cert_path if cert_path else DEFAULT_CONF_CERT_FILE
                    self.flow_data[CONF_CERT] = target_cert
                elif device_type == DEVICE_TYPE_SAMSUNG_8888:
                    # fmt: off
                    _LOGGER.info('Falling back from port %s to port %s topology.', 8888, 2878)  # pragma: no mutate
                    # fmt: on
                    self.flow_data[CONF_DEVICE_TYPE] = DEVICE_TYPE_SAMSUNG_2878

                new_device_type = self.flow_data[CONF_DEVICE_TYPE]
                auth_flow_dict = await self._load_auth_flow_config(new_device_type)
                target_cert_val = cert_path if cert_path else None

                self.acquirer = GenericYamlTokenAcquirer(
                    self.hass, ip_address, auth_flow_dict, target_cert_val
                )

                self.task = self.hass.async_create_task(
                    self._initiate_pairing_safe()
                )  # pragma: no mutate
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
            step_id="initiate_pairing",  # pragma: no mutate
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
                safe_token = helpers.sanitize_token(raw_token)

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
                "ip_address": self.flow_data.get(
                    CONF_IP_ADDRESS, ""
                )  # pragma: no mutate
            },
        )

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
                dev_id = self.flow_data.get("device_id")

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
        ip_address = str(
            self.flow_data.get(CONF_IP_ADDRESS, "Unknown")
        )  # pragma: no mutate

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
            _LOGGER.warning("AC rejected token during pairing.")  # pragma: no mutate
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
        if (
            self.reauth_entry is None and self.source != SOURCE_RECONFIGURE
        ):  # pragma: no mutate
            self._abort_if_unique_id_configured(updates=self.flow_data)
        self.flow_data["unique_id"] = final_unique_id

        title = (
            str(self.flow_data.get("name", "")).strip()
            or f"Samsung AC {final_unique_id}"
        )
        self.flow_data["name"] = title

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

        if CONF_DEVICE_ID in entry_data:
            dev_id = str(entry_data[CONF_DEVICE_ID]).strip()
            if dev_id in ("0", "main", "", "None"):
                del entry_data[CONF_DEVICE_ID]

        return self.async_create_entry(title=title, data=entry_data)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication failure from the integration."""
        _LOGGER.debug(
            "Entering async_step_reauth with data: %s", entry_data
        )  # pragma: no mutate
        entry_id = self.context.get("entry_id")
        self.reauth_entry = (
            self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
        )

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
            if device_type in (
                DEVICE_TYPE_SMARTTHINGS_HVAC,
                DEVICE_TYPE_SMARTTHINGS_DHW,
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

    def _async_show_reconfigure_form(
        self,
        errors: dict[str, str],
        suggested_values: dict[str, Any],
        description_placeholders: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Build and return the reconfigure_confirm form with the given suggested values."""
        base_schema = vol.Schema(
            {
                vol.Required(CONF_IP_ADDRESS): str,
                vol.Optional(CONF_MAC): str,
                vol.Optional(CONF_TOKEN): str,
                vol.Optional(CONF_CERT): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure_confirm",
            data_schema=self.add_suggested_values_to_schema(
                base_schema, suggested_values
            ),
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
        }  # pragma: no mutate

    async def async_step_reconfigure_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the reconfiguration form and process its submission."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        device_type = self.flow_data[CONF_DEVICE_TYPE]
        is_8888 = (
            device_type in DEVICE_TYPE_8888_GROUP or device_type == DEVICE_TYPE_MIM_H03
        )

        raw_mac_def = str(self.flow_data.get(CONF_MAC) or "")
        mac_def = dr.format_mac(raw_mac_def).upper() if raw_mac_def else ""
        is_samsung = is_8888 or device_type == DEVICE_TYPE_SAMSUNG_2878

        # CERTIFICATE HARDENING
        cert_def = str(self.flow_data.get(CONF_CERT, "")).strip()
        if not cert_def:
            cert_def = "ac14k_m.pem" if is_samsung else ""

        initial_suggested = {
            CONF_IP_ADDRESS: self.flow_data.get(CONF_IP_ADDRESS) or "",
            CONF_MAC: mac_def,
            CONF_TOKEN: str(self.flow_data.get(CONF_TOKEN) or ""),
            CONF_CERT: cert_def,
        }

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
                error_reason = await self._async_resolve_mac_and_set_unique_id(
                    ip_address=str(self.flow_data[CONF_IP_ADDRESS]),
                    mac_address=self.flow_data.get(CONF_MAC),
                )

                if error_reason:
                    errors["base"] = error_reason
                    return self._async_show_reconfigure_form(
                        errors, self._current_reconfigure_suggested()
                    )

            cert_value = str(self.flow_data.get(CONF_CERT) or "")
            if not cert_value:
                _LOGGER.warning(
                    "Reconfigure: certificate path was cleared..."
                )  # pragma: no mutate

            if not await self._async_validate_cert_path(cert_value):
                errors["base"] = "cert_not_found"
                return self._async_show_reconfigure_form(
                    errors, self._current_reconfigure_suggested()
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
                target_cert = cert_value if cert_value else None

                # FAIL FAST APPLIED: Direct dictionary access
                ip_val = str(self.flow_data[CONF_IP_ADDRESS])

                auth_flow_dict = await self._load_auth_flow_config(device_type)
                self.acquirer = GenericYamlTokenAcquirer(
                    self.hass, ip_val, auth_flow_dict, target_cert
                )
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
        desc_placeholders = {
            "device_name": reconfigure_entry.title,
            "ip_address": r_ip or "",
        }
        return self._async_show_reconfigure_form(
            errors, initial_suggested, desc_placeholders
        )
