# pylint: disable=too-many-return-statements,too-many-branches
# custom_components/climate_ip/config_flow_helpers.py
"""Connectivity, pairing, and validation helpers for Climate IP config flow."""

import asyncio
from collections.abc import Callable, Coroutine
import logging
import os
from pathlib import Path
import ssl  # noqa: F401
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlowResult,
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_NAME, CONF_TOKEN
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import aiohttp_client, device_registry as dr
from homeassistant.util.yaml import load_yaml

from . import config_flow, controller_yaml, helpers
from .connection_aiohttp import ConnectionAiohttp8888
from .connection_intesisbox import ConnectionIntesisBox
from .const import (
    CONF_CERT,
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_DISCOVERED_DEVICES,
    CONF_POLL_INTERVAL,
    CONF_SELECTED_DEVICES,
    CONFIG_DEVICE_NAME,
    CONFIG_FILE_TO_DEVICE_TYPE,
    DEFAULT_CONF_CERT_FILE,
    DEVICE_TYPE_8888_GROUP,
    DEVICE_TYPE_INTESISBOX,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DEVICE_TYPE_TO_CONFIG_FILE,
)
from .exceptions import AuthError, CannotConnect, TokenAcquisitionError

_LOGGER = logging.getLogger(__name__)

_AUTH_FLOW_CACHE: dict[str, dict[str, Any]] = {}

if TYPE_CHECKING:
    import probatio

    from homeassistant.config_entries import ConfigFlow

    _FlowMixinBase = ConfigFlow
else:
    _FlowMixinBase = object


class ConfigFlowHelpersMixin(_FlowMixinBase):
    """Mixin containing connectivity and pairing helpers for Climate IP config flow."""

    flow_data: dict[str, Any]
    acquirer: Any | None
    reauth_entry: ConfigEntry | None
    task: asyncio.Task[Any] | None

    if TYPE_CHECKING:

        def _get_samsung_2878_schema(
            self, mac_required: bool = False
        ) -> probatio.Schema: ...
        def _get_samsung_8888_schema(
            self, mac_required: bool = False
        ) -> probatio.Schema: ...
        def _get_intesisbox_schema(self) -> probatio.Schema: ...
        def _get_rest_api_schema(self) -> probatio.Schema: ...
        def _current_reconfigure_suggested(self) -> dict[str, Any]: ...
        def _async_show_reconfigure_form(
            self,
            errors: dict[str, str],
            suggested_values: dict[str, Any],
            description_placeholders: dict[str, str] | None = None,
        ) -> ConfigFlowResult: ...
        async def async_step_test_connection(
            self, user_input: Any | None = None
        ) -> ConfigFlowResult:
            """Stub for flow step to validate connection."""

        async def async_step_initiate_pairing(
            self, user_input: Any | None = None
        ) -> ConfigFlowResult:
            """Stub for flow step to initiate pairing."""

    async def _load_auth_flow_config(self, device_type: str) -> dict[str, Any]:
        """Dynamically load and cache the authentication YAML file according to device type."""
        if device_type in _AUTH_FLOW_CACHE:
            return _AUTH_FLOW_CACHE[device_type]

        main_yaml_name = DEVICE_TYPE_TO_CONFIG_FILE.get(device_type)
        if not main_yaml_name:
            raise ValueError(
                f"No configuration file mapping found for device_type: {device_type}"
            )
        main_yaml_path = str(Path(__file__).parent / main_yaml_name)
        main_config = await self.hass.async_add_executor_job(load_yaml, main_yaml_path)
        if not isinstance(main_config, dict):
            raise ValueError(f"Invalid YAML configuration loaded from {main_yaml_name}")  # noqa: TRY004

        device_config = main_config.get("device")
        auth_file = (
            device_config.get("auth_flow_file")
            if isinstance(device_config, dict)
            else None
        )
        if not auth_file:
            raise ValueError(f"No 'auth_flow_file' found in {main_yaml_name}")

        auth_yaml_path = str(Path(__file__).parent / auth_file)
        auth_config = await self.hass.async_add_executor_job(load_yaml, auth_yaml_path)
        if not isinstance(auth_config, dict):
            raise ValueError(f"Invalid YAML configuration loaded from {auth_file}")  # noqa: TRY004
        auth_flow = auth_config.get("auth_flow")
        result = auth_flow if isinstance(auth_flow, dict) else {}
        _AUTH_FLOW_CACHE[device_type] = result
        return result

    async def _async_force_arp_update(self, ip_address: str) -> None:
        """Send quick TCP SYN packets to force the OS to populate its ARP cache."""
        await helpers.async_force_arp_update(ip_address)

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

            discovered_mac = await helpers.async_get_mac_address(ip_address)

            if discovered_mac is None:
                await self._async_force_arp_update(ip_address)
                discovered_mac = await helpers.async_get_mac_address(ip_address)

            if discovered_mac is not None:
                formatted_mac = dr.format_mac(discovered_mac)
                _LOGGER.info(
                    "MAC discovered via ARP: %s", formatted_mac
                )  # pragma: no mutate
                self.flow_data[CONF_MAC] = formatted_mac.replace(":", "").upper()
            else:
                _LOGGER.info(
                    "MAC auto-discovery failed. Requesting manual input"
                )  # pragma: no mutate
                return "mac_resolve_failed"

        await self.async_set_unique_id(str(self.flow_data[CONF_MAC]))
        if self.reauth_entry is None:
            if getattr(self, "source", None) != SOURCE_RECONFIGURE:
                self._abort_if_unique_id_configured()

        return None

    async def _async_validate_cert_path(self, user_cert_path: str | None) -> bool:
        """Validate if the certificate file exists on disk."""
        if not user_cert_path:
            return True

        path_to_check = helpers.resolve_cert_path(
            user_cert_path,
            str(Path(__file__).parent),
            self.hass,  # pragma: no mutate
        )
        if path_to_check is None:
            return True

        exists: bool = await self.hass.async_add_executor_job(
            os.path.exists,
            path_to_check,  # pragma: no mutate
        )
        return exists

    def _map_exception_to_error(self, err: Exception, *, phase: str) -> dict[str, Any]:
        """Map domain and network exceptions to standardized flow error dictionaries."""
        ip_address = str(
            self.flow_data.get(CONF_IP_ADDRESS, "Unknown")
        )  # pragma: no mutate
        match err:
            case AbortFlow():
                raise err
            case CannotConnect():
                _LOGGER.error(
                    "Fatal pairing failure at %s. Details: %s", ip_address, err
                )
                return {
                    "ok": False,
                    "error": "pairing_connection_failed",
                    "error_details": str(err),
                }
            case TimeoutError():
                _LOGGER.warning("Timeout connecting to %s. Wrong IP?", ip_address)
                return {
                    "ok": False,
                    "error": "timeout_connect",
                    "error_details": str(err),
                }
            case AuthError() if phase == "test_connection":
                _LOGGER.warning("AC rejected token during pairing")
                return {
                    "ok": False,
                    "error": "invalid_auth",
                    "error_details": str(err),
                }
            case TokenAcquisitionError() if phase == "wait_token":
                _LOGGER.warning("Token acquisition failed: %s", err)
                return {"ok": False, "error": "token_acquisition_failed"}
            case AuthError() | TokenAcquisitionError():
                _LOGGER.warning("Connection error during pairing initiation: %s", err)
                return {
                    "ok": False,
                    "error": "pairing_connection_failed",
                    "error_details": str(err),
                }
            case _:
                _LOGGER.exception("Unexpected error during %s", phase)
                default_err = (
                    "cannot_connect" if phase == "test_connection" else "unknown_error"
                )
                return {"ok": False, "error": default_err}

    def _consume_completed_task(self) -> dict[str, Any]:
        """Extract the result of a completed background task safely and clear self.task."""
        assert self.task is not None  # pragma: no mutate
        try:
            result: dict[str, Any] = self.task.result()
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            _LOGGER.error("Task failed unexpectedly: %s", err)
            result = {"ok": False, "error": "unknown_error"}
        self.task = None
        return result

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
            return {"ok": True, "config": successful_config}  # noqa: TRY300
        except Exception as err:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            return self._map_exception_to_error(err, phase="initiate_pairing")

    async def _wait_token_safe(self) -> dict[str, Any]:
        """Async wrapper for the token acquisition phase with exception handling."""
        _LOGGER.debug("Executing safe wrapper: _wait_token_safe")  # pragma: no mutate
        try:
            if self.acquirer is None:
                return {"ok": False, "error": "unknown_error"}

            token = await self.acquirer.async_wait_for_token()
            _LOGGER.debug(
                "_wait_token_safe successful, token acquired"
            )  # pragma: no mutate
            return {"ok": True, "token": token}  # noqa: TRY300
        except Exception as err:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            return self._map_exception_to_error(err, phase="wait_token")

    _build_ssl_context = staticmethod(ConnectionAiohttp8888.build_8888_ssl_context)

    async def _test_connection_safe(self) -> dict[str, Any]:
        """Safe and lightweight wrapper for testing the connection."""
        _LOGGER.debug(
            "Executing lightweight connection test: _test_connection_safe"
        )  # pragma: no mutate
        try:
            device_type = self.flow_data[CONF_DEVICE_TYPE]
            ip_address = str(
                self.flow_data.get(CONF_IP_ADDRESS, "Unknown")
            )  # pragma: no mutate
            token = str(self.flow_data.get(CONF_TOKEN) or "")

            if device_type in DEVICE_TYPE_8888_GROUP:
                cert = str(self.flow_data.get(CONF_CERT) or "")
                success = await ConnectionAiohttp8888.async_test_8888_connection(
                    self.hass, ip_address, token, cert
                )
                if success:
                    _LOGGER.debug(
                        "Lightweight 8888 connection test successful"
                    )  # pragma: no mutate
                    return {"ok": True}

                # fmt: off
                _LOGGER.warning('8888 connection test failed')  # pragma: no mutate
                # fmt: on
                return {"ok": False, "error": "cannot_connect"}

            if device_type == DEVICE_TYPE_SAMSUNG_2878:
                config_data = self.flow_data.copy()
                if "unique_id" not in config_data:
                    config_data["unique_id"] = config_data.get(CONF_MAC, "")

                if CONF_CONFIG_FILE not in config_data:
                    if device_type in DEVICE_TYPE_TO_CONFIG_FILE:
                        config_data[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE[
                            device_type
                        ]

                controller = controller_yaml.YamlController(
                    config=config_data, logger=_LOGGER
                )
                controller.hass = self.hass
                # pylint: disable=protected-access
                controller._session = aiohttp_client.async_get_clientsession(self.hass)  # noqa: SLF001

                initialized = await controller.initialize()
                if not initialized:
                    return {"ok": False, "error": "cannot_connect"}  # pragma: no mutate

                loader: Any = controller.loader
                state_data = None
                if (
                    loader is not None
                    and loader.state_getter is not None  # pragma: no mutate
                ):
                    state_data = await loader.state_getter.async_update_state(
                        None,
                        False,  # pragma: no mutate
                    )
                await controller.async_shutdown()

                return {"ok": state_data is not None}

            # fmt: off
            _LOGGER.error('Unknown device type for connection test: %s', device_type)  # pragma: no mutate
            # fmt: on
            return {"ok": False, "error": "cannot_connect"}  # noqa: TRY300

        except Exception as err:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            return self._map_exception_to_error(err, phase="test_connection")

    async def _async_process_import(
        self, user_input: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle the import of a YAML configuration (legacy platform)."""
        payload = dict(user_input)
        _LOGGER.debug(
            "Starting YAML import for: %s", payload.get(CONF_IP_ADDRESS)
        )  # pragma: no mutate

        mac_address = payload.get(CONF_MAC)
        if mac_address is not None:
            payload[CONF_MAC] = dr.format_mac(mac_address).upper()

        unique_id = payload.get(CONF_MAC)
        if not unique_id:
            _LOGGER.error(
                "YAML import failed: No MAC address provided"
            )  # pragma: no mutate
            return self.async_abort(reason="no_mac_address_found")

        await self.async_set_unique_id(str(unique_id))
        self._abort_if_unique_id_configured()

        config_file = payload.get(CONF_CONFIG_FILE)
        if config_file is not None:
            if config_file in CONFIG_FILE_TO_DEVICE_TYPE:
                payload[CONF_DEVICE_TYPE] = CONFIG_FILE_TO_DEVICE_TYPE[config_file]
                # fmt: off
                _LOGGER.debug("Inferred device_type '%s' from config_file '%s'", payload[CONF_DEVICE_TYPE], config_file)  # pragma: no mutate
                # fmt: on

        device_name = str(payload.get(CONFIG_DEVICE_NAME, f"Climate {unique_id}"))

        self.flow_data.update(payload)
        if CONF_DEVICE_TYPE in self.flow_data:
            test_result = await self._test_connection_safe()
            if not test_result.get("ok"):
                _LOGGER.error(
                    "YAML import failed: Could not connect to device"
                )  # pragma: no mutate
                return self.async_abort(reason="cannot_connect")

        _LOGGER.info(
            "Creating new entry for '%s' from imported YAML", device_name
        )  # pragma: no mutate
        return self.async_create_entry(title=device_name, data=payload)

    def _extract_and_validate_poll_interval(
        self,
        user_input: dict[str, Any],
        errors: dict[str, str],
        *,
        store_when_empty: bool,
    ) -> None:
        """Validate CONF_POLL_INTERVAL from user_input and store in flow_data."""
        poll_str = user_input.get(CONF_POLL_INTERVAL)
        if poll_str is not None and str(poll_str).strip() != "":
            try:
                self.flow_data[CONF_POLL_INTERVAL] = helpers.validate_poll_interval(
                    poll_str
                )
            except ValueError:
                errors[CONF_POLL_INTERVAL] = "invalid_poll_interval"
        elif store_when_empty and CONF_POLL_INTERVAL in user_input:
            self.flow_data[CONF_POLL_INTERVAL] = None

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
            self._extract_and_validate_poll_interval(
                user_input, errors, store_when_empty=True
            )
            if errors:
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

            self.acquirer = config_flow.GenericYamlTokenAcquirer(
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

    async def _async_process_intesisbox_input(
        self, user_input: dict[str, Any]
    ) -> ConfigFlowResult:
        """Process submitted values in the IntesisBox flow."""
        errors: dict[str, str] = {}
        self.flow_data.update(user_input)
        ip_addr = str(self.flow_data[CONF_IP_ADDRESS])
        mac_val = self.flow_data.get(CONF_MAC)

        self._extract_and_validate_poll_interval(
            user_input, errors, store_when_empty=False
        )

        if not errors:
            try:
                probed_mac = await ConnectionIntesisBox.async_probe(ip_addr)
                if not mac_val and probed_mac:
                    mac_val = probed_mac
            except CannotConnect:
                errors["base"] = "cannot_connect"

        if not errors:
            error_reason = await self._async_resolve_mac_and_set_unique_id(
                ip_address=ip_addr, mac_address=mac_val
            )
            if error_reason is not None:
                errors["base"] = error_reason
            else:
                self._abort_if_unique_id_configured()

        if not errors:
            self.flow_data[CONF_NAME] = f"IntesisBox ({ip_addr})"
            self.flow_data[CONF_DEVICE_TYPE] = DEVICE_TYPE_INTESISBOX
            self.flow_data[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE[
                DEVICE_TYPE_INTESISBOX
            ]
            self.flow_data[CONF_TOKEN] = str(
                self.flow_data.get(
                    CONF_MAC, mac_val or "intesisbox"
                )  # pragma: no mutate
            )
            return self.async_create_entry(
                title=f"IntesisBox ({ip_addr})",
                data=self.flow_data,
            )

        return self.async_show_form(
            step_id="intesisbox",
            data_schema=self._get_intesisbox_schema(),
            errors=errors,
        )

    async def _async_process_rest_api_input(
        self, user_input: dict[str, Any]
    ) -> ConfigFlowResult:
        """Process submitted values in the REST API flow."""
        errors: dict[str, str] = {}
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

        self._extract_and_validate_poll_interval(
            user_input, errors, store_when_empty=True
        )
        if errors:
            step_id_err2 = "rest_api"  # pragma: no mutate
            schema_err2 = self._get_rest_api_schema()  # pragma: no mutate
            return self.async_show_form(
                step_id=step_id_err2, data_schema=schema_err2, errors=errors
            )

        is_st = device_type in (
            DEVICE_TYPE_SMARTTHINGS_HVAC,
            DEVICE_TYPE_SMARTTHINGS_DHW,
        )

        try:
            ip_addr = str(self.flow_data[CONF_IP_ADDRESS]).strip()
            need_dev_id = bool(is_st and not self.flow_data.get(CONF_DEVICE_ID))
            discovered_dev_id = await ConnectionAiohttp8888.async_validate_rest_device(
                self.hass,
                ip_addr,
                self.flow_data.get(CONF_TOKEN),
                fetch_device_id=need_dev_id,
            )
            if discovered_dev_id:
                self.flow_data[CONF_DEVICE_ID] = discovered_dev_id

            unique_id = str(
                self.flow_data.get(CONF_DEVICE_ID)
                or self.flow_data.get(CONF_MAC)
                or ""  # pragma: no mutate
            )
            if not unique_id:
                if is_st:
                    token_str = str(
                        self.flow_data.get(CONF_TOKEN, "")
                    )  # pragma: no mutate
                    suffix = token_str[-8:] if len(token_str) >= 8 else ip_addr
                    unique_id = f"{device_type}_{suffix}"
                else:
                    _LOGGER.error(
                        "REST API connection test failed"
                    )  # pragma: no mutate
                    return self.async_abort(reason="no_mac_address_found")

            self.flow_data["unique_id"] = unique_id
            await self.async_set_unique_id(unique_id)
            if self.reauth_entry is None:
                self._abort_if_unique_id_configured()
            return await self._create_entry()

        except AbortFlow:
            raise
        except CannotConnect:
            errors["base"] = "cannot_connect"

        step_id_def = "rest_api"
        schema_def = self._get_rest_api_schema()
        return self.async_show_form(
            step_id=step_id_def,
            data_schema=schema_def,
            errors=errors,
        )

    async def _async_run_progress_step(
        self,
        *,
        step_id: str,
        progress_action: str,
        coro_factory: Callable[[], Coroutine[Any, Any, Any]],
        on_complete: Callable[[Any], Coroutine[Any, Any, ConfigFlowResult]],
        description_placeholders: (
            dict[str, Any] | Callable[[], dict[str, Any]] | None
        ) = None,
    ) -> ConfigFlowResult:
        """Run or resume a background task for a progress flow step."""
        if not self.task:
            self.task = self.hass.async_create_task(coro_factory())

        if self.task.done():
            result = self._consume_completed_task()
            return await on_complete(result)

        kwargs: dict[str, Any] = {
            "step_id": step_id,
            "progress_action": progress_action,
            "progress_task": self.task,
        }
        if description_placeholders is not None:
            kwargs["description_placeholders"] = (
                description_placeholders()
                if callable(description_placeholders)
                else description_placeholders
            )
        return self.async_show_progress(**kwargs)

    async def _async_step_initiate_pairing(self) -> ConfigFlowResult:
        """Phase 1: Put the device in pairing mode using a safe wrapper."""
        _LOGGER.debug("Entering async_step_initiate_pairing")  # pragma: no mutate
        if self.acquirer is None:
            _LOGGER.warning("Flow state lost (acquirer is None). Aborting pairing")
            return self.async_abort(reason="flow_state_lost")

        return await self._async_run_progress_step(
            step_id="initiate_pairing",
            progress_action="initiating_pairing",
            coro_factory=self._initiate_pairing_safe,
            on_complete=self._async_handle_initiate_pairing_result,
        )

    async def _async_step_await_button(self) -> ConfigFlowResult:
        """Phase 2: Wait for the user to press the required button."""
        _LOGGER.debug("Entering async_step_await_button")  # pragma: no mutate
        if self.acquirer is None:
            _LOGGER.warning("Flow state lost (acquirer is None). Aborting pairing")
            return self.async_abort(reason="flow_state_lost")

        return await self._async_run_progress_step(
            step_id="await_button",
            progress_action="awaiting_button_press",
            coro_factory=self._wait_token_safe,
            on_complete=self._async_handle_acquired_token,
            description_placeholders=lambda: {
                "ip_address": self.flow_data.get(CONF_IP_ADDRESS, "")
            },  # pragma: no mutate
        )

    async def _async_step_test_connection(self) -> ConfigFlowResult:
        """Phase to validate the IP and token."""
        _LOGGER.debug("Entering async_step_test_connection")  # pragma: no mutate
        return await self._async_run_progress_step(
            step_id="test_connection",
            progress_action="testing_connection",
            coro_factory=self._test_connection_safe,
            on_complete=self._async_handle_test_connection_result,
            description_placeholders=lambda: {
                "ip_address": str(self.flow_data.get(CONF_IP_ADDRESS, ""))
            },
        )

    async def _async_handle_initiate_pairing_result(
        self, result: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle initiate pairing task result and advance flow or attempt fallback."""
        if result.get("ok"):
            # fmt: off
            _LOGGER.debug('Pairing initiation successful, advancing to await_button')  # pragma: no mutate
            # fmt: on
            successful_config = result.get("config")
            if successful_config is not None:
                self.flow_data["preferred_connection"] = successful_config
                # fmt: off
                _LOGGER.info('Successfully found working connection config, will save: %s', successful_config)  # pragma: no mutate
                # fmt: on
            return self.async_show_progress_done(next_step_id="await_button")

        return await self._async_attempt_pairing_fallback(result)

    async def _async_attempt_pairing_fallback(
        self, result: dict[str, Any]
    ) -> ConfigFlowResult:
        """Attempt port fallback or advance to error handling on initiate pairing failure."""
        fallback_attempted = self.flow_data.get("_fallback_attempted")
        if fallback_attempted is not True:
            self.flow_data["_fallback_attempted"] = True
            # fmt: off
            _LOGGER.info('Pairing initiation failed. Attempting automatic port fallback')  # pragma: no mutate
            # fmt: on

            device_type = self.flow_data[CONF_DEVICE_TYPE]
            ip_address = str(self.flow_data[CONF_IP_ADDRESS])
            cert_path = str(self.flow_data.get(CONF_CERT, ""))  # pragma: no mutate

            if device_type == DEVICE_TYPE_SAMSUNG_2878:
                # fmt: off
                _LOGGER.info('Falling back from port %s to port %s topology', 2878, 8888)  # pragma: no mutate
                # fmt: on
                self.flow_data[CONF_DEVICE_TYPE] = DEVICE_TYPE_SAMSUNG_8888
                target_cert = cert_path or DEFAULT_CONF_CERT_FILE
                self.flow_data[CONF_CERT] = target_cert
            elif device_type == DEVICE_TYPE_SAMSUNG_8888:
                # fmt: off
                _LOGGER.info('Falling back from port %s to port %s topology', 8888, 2878)  # pragma: no mutate
                # fmt: on
                self.flow_data[CONF_DEVICE_TYPE] = DEVICE_TYPE_SAMSUNG_2878

            new_device_type = self.flow_data[CONF_DEVICE_TYPE]
            auth_flow_dict = await self._load_auth_flow_config(new_device_type)
            target_cert_val = cert_path or None

            # Close the previous acquirer's listener before rebinding
            if self.acquirer is not None:
                await self.acquirer.async_close()

            self.acquirer = config_flow.GenericYamlTokenAcquirer(
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

    async def _async_handle_acquired_token(
        self, result: dict[str, Any]
    ) -> ConfigFlowResult:
        """Process acquired token and advance flow or route to error handling."""
        if result.get("ok"):
            raw_token = str(result.get("token", ""))
            safe_token = helpers.sanitize_token(raw_token)

            if not safe_token:
                # fmt: off
                _LOGGER.error('Acquired token was rejected by sanitizer - aborting pairing. This may indicate a compromised or malformed AC response')  # pragma: no mutate
                # fmt: on
                self.flow_data["error_key"] = "token_acquisition_failed"
                return self.async_show_progress_done(next_step_id="handle_error")

            self.flow_data[CONF_TOKEN] = safe_token

            if self.flow_data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_SAMSUNG_2878:
                # fmt: off
                _LOGGER.debug('Token for 2878 device acquired. Routing to test connection')  # pragma: no mutate
                # fmt: on
                return self.async_show_progress_done(next_step_id="test_connection")

            # fmt: off
            _LOGGER.debug('Token acquisition successful, advancing to discover_uuid')  # pragma: no mutate
            # fmt: on
            return self.async_show_progress_done(next_step_id="discover_uuid")

        self.flow_data["error_key"] = result.get(
            "error", "unknown_error"
        )  # pragma: no mutate
        if "error_details" in result:
            self.flow_data["error_details"] = result["error_details"]
        return self.async_show_progress_done(next_step_id="handle_error")

    async def _async_handle_test_connection_result(
        self, result: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle test connection task result and advance flow or route to error."""
        if result.get("ok"):
            _LOGGER.debug(
                "Connection test successful, advancing to discovery"
            )  # pragma: no mutate
            dev_type = self.flow_data[CONF_DEVICE_TYPE]
            dev_id = self.flow_data.get("device_id")
            if dev_type != DEVICE_TYPE_SAMSUNG_2878 and not dev_id:
                return self.async_show_progress_done(next_step_id="discover_uuid")
            return self.async_show_progress_done(next_step_id="create_entry")

        self.flow_data.pop(CONF_TOKEN, None)
        err_raw = result.get("error")
        self.flow_data["error_key"] = str(err_raw) if err_raw else "cannot_connect"
        return self.async_show_progress_done(next_step_id="handle_error")

    def _async_build_error_step_result(self) -> ConfigFlowResult:
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
        match error_key:
            case "mac_resolve_failed":
                req_mac = True
                errors["base"] = "mac_resolve_failed"
            case "timeout_connect":
                _LOGGER.warning(
                    "Timeout connecting to %s. Wrong IP?", ip_address
                )  # pragma: no mutate
                errors[CONF_IP_ADDRESS] = "timeout_connect"
            case "invalid_auth":
                _LOGGER.warning("AC rejected token during pairing")  # pragma: no mutate
                errors["base"] = "invalid_auth"
            case _:
                errors["base"] = error_key

        return self.async_show_form(
            step_id=step_id,
            data_schema=schema_generator(mac_required=req_mac),
            errors=errors,
        )

    async def _create_entry(self) -> ConfigFlowResult:
        """Create the config entry and finish the flow."""
        device_type = self.flow_data[CONF_DEVICE_TYPE]

        uid_data = str(self.flow_data.get("unique_id", ""))
        mac_data = str(self.flow_data.get(CONF_MAC, ""))
        final_unique_id = uid_data or mac_data

        if not final_unique_id:
            if device_type in (
                DEVICE_TYPE_SMARTTHINGS_HVAC,
                DEVICE_TYPE_SMARTTHINGS_DHW,
            ):
                dev_id = str(self.flow_data.get(CONF_DEVICE_ID) or "")
                token_val = str(self.flow_data.get(CONF_TOKEN) or "")
                ip_val = str(self.flow_data.get(CONF_IP_ADDRESS) or "")
                suffix = dev_id or (
                    token_val[-8:] if len(token_val) >= 8 else ip_val or "default"
                )
                final_unique_id = f"{device_type}_{suffix}"
            else:
                return self.async_abort(reason="no_mac_address_found")

        await self.async_set_unique_id(final_unique_id)
        if (
            self.reauth_entry is None
            and getattr(self, "source", None) != SOURCE_RECONFIGURE
        ):  # pragma: no mutate
            self._abort_if_unique_id_configured(updates=self.flow_data)
        self.flow_data["unique_id"] = final_unique_id

        title = str(self.flow_data.get("name", "")).strip() or (
            f"Samsung {device_type.replace('_', ' ').title()}"
            if device_type
            in (DEVICE_TYPE_SMARTTHINGS_HVAC, DEVICE_TYPE_SMARTTHINGS_DHW)
            else f"Samsung AC {final_unique_id}"
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
                "Re-auth successful. Updating config entry"
            )  # pragma: no mutate
            entry_data = {
                k: v for k, v in self.flow_data.items() if k not in transient_keys
            }
            return self.async_update_reload_and_abort(
                self.reauth_entry, data=entry_data, reason="reauth_successful"
            )

        if getattr(self, "source", None) == SOURCE_RECONFIGURE:
            # fmt: off
            _LOGGER.debug('Reconfigure successful via pairing flow. Updating config entry')  # pragma: no mutate
            # fmt: on
            reconfigure_entry = self._get_reconfigure_entry()
            entry_data = {
                k: v for k, v in self.flow_data.items() if k not in transient_keys
            }
            updated_data = {**reconfigure_entry.data, **entry_data}
            return self.async_update_reload_and_abort(
                reconfigure_entry,
                data=updated_data,
                reason="reconfigure_successful",
            )

        entry_data = {
            k: v for k, v in self.flow_data.items() if k not in transient_keys
        }

        if CONF_DEVICE_ID in entry_data:
            dev_id = str(entry_data[CONF_DEVICE_ID]).strip()
            if dev_id in ("0", "main", "", "None"):
                del entry_data[CONF_DEVICE_ID]

        return self.async_create_entry(title=title, data=entry_data)

    async def _async_process_reconfigure_input(
        self, reconfigure_entry: ConfigEntry, user_input: dict[str, Any]
    ) -> ConfigFlowResult:
        """Process submitted values in the reconfigure flow."""
        errors: dict[str, str] = {}
        device_type = self.flow_data[CONF_DEVICE_TYPE]

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
                    errors,
                    self._current_reconfigure_suggested(),
                )

            current_mac = self.flow_data.get(CONF_MAC)
            if current_mac and reconfigure_entry.unique_id:
                safe_mac = str(current_mac).replace(":", "").upper()
                safe_uid = str(reconfigure_entry.unique_id).replace(":", "").upper()
                if safe_mac != safe_uid:
                    _LOGGER.error(
                        "Reconfigure failed: Device MAC %s does not match existing unique_id %s",
                        safe_mac,
                        safe_uid,
                    )
                    return self.async_abort(reason="unique_id_mismatch")

        cert_value = str(self.flow_data.get(CONF_CERT) or "")
        if not cert_value:
            logging.getLogger("custom_components.climate_ip.config_flow").warning(
                "Reconfigure: certificate path was cleared"
            )  # pragma: no mutate

        if not await self._async_validate_cert_path(cert_value):
            errors["base"] = "cert_not_found"
            return self._async_show_reconfigure_form(
                errors,
                self._current_reconfigure_suggested(),
            )

        token_raw = self.flow_data.get(CONF_TOKEN)
        token_val = str(token_raw) if token_raw is not None else ""  # pragma: no mutate
        if not token_val and device_type not in (
            DEVICE_TYPE_SMARTTHINGS_HVAC,
            DEVICE_TYPE_SMARTTHINGS_DHW,
        ):
            _LOGGER.info(
                "Token absent during reconfigure. Setting up acquirer for discovery"
            )  # pragma: no mutate
            target_cert = cert_value or None

            # FAIL FAST APPLIED: Direct dictionary access
            ip_val = str(self.flow_data[CONF_IP_ADDRESS])

            auth_flow_dict = await self._load_auth_flow_config(device_type)
            self.acquirer = config_flow.GenericYamlTokenAcquirer(
                self.hass, ip_val, auth_flow_dict, target_cert
            )
            return await self.async_step_initiate_pairing()

        updated_data = {**reconfigure_entry.data, **self.flow_data}
        _LOGGER.info(
            "Reconfigure: updated entry '%s' with new connectivity parameters",
            reconfigure_entry.title,
        )  # pragma: no mutate
        return self.async_update_reload_and_abort(
            reconfigure_entry, data=updated_data, reason="reconfigure_successful"
        )
