# custom_components/climate_ip/config_flow.py
"""Config flow for the Climate IP integration."""
import asyncio
import logging
import re
from typing import Any, Dict, Optional

import voluptuous as vol
from getmac import get_mac_address
from homeassistant import config_entries
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_NAME,
    CONF_TOKEN,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_CERT,
    CONF_CONFIG_FILE,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_SMARTTHINGS_DHW,
    DEVICE_TYPE_SMARTTHINGS_HVAC,
    DOMAIN,
    DEVICE_TYPE_TO_CONFIG_FILE,
)
from .controller_yaml import YamlController
from .token_acquirer import (
    AuthTurnedOffError,
    SamsungTokenAcquirer,
    TokenAcquisitionError,
)

_LOGGER = logging.getLogger(__name__)


class ClimateIpConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow implementing a robust, multi-step pairing process with safe task wrappers."""

    VERSION = 2

    def __init__(self):
        """Initialize the config flow."""
        self.flow_data: Dict[str, Any] = {}
        self.task: Optional[asyncio.Task] = None
        self.acquirer: Optional[SamsungTokenAcquirer] = None
        _LOGGER.debug("Initializing new Climate IP config flow.")

    async def async_step_import(self, import_config: dict[str, Any]) -> FlowResult:
        """Handle configuration automatically imported from YAML."""
        _LOGGER.debug("Starting import from YAML configuration: %s", import_config)

        unique_id = None
        if mac := import_config.get(CONF_MAC):
            unique_id = mac
        elif device_id := import_config.get("device_id"):
            unique_id = device_id

        if unique_id:
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured(updates=import_config)

        if not import_config.get(CONF_DEVICE_TYPE) and (config_file := import_config.get(CONF_CONFIG_FILE)):
            from .const import CONFIG_FILE_TO_DEVICE_TYPE
            import_config[CONF_DEVICE_TYPE] = CONFIG_FILE_TO_DEVICE_TYPE.get(config_file)

        title = import_config.get(CONF_NAME) or f"Climate IP {import_config.get(CONF_IP_ADDRESS)}"

        _LOGGER.info("Creating new entry for '%s' from imported YAML.", title)
        return self.async_create_entry(title=title, data=import_config)

    @callback
    def async_remove(self) -> None:
        """Clean up the flow if the user cancels."""
        _LOGGER.debug("Config flow cancelled by user. Cleaning up task.")
        if self.task:
            self.task.cancel()
        if self.acquirer:
            self.hass.async_create_task(self.acquirer.async_close())

    async def _initiate_pairing_safe(self) -> Dict[str, Any]:
        """Safe wrapper for the initiate_pairing phase to prevent exceptions from escaping."""
        _LOGGER.debug("Executing safe wrapper: _initiate_pairing_safe")
        try:
            await self.acquirer.async_initiate_pairing()
            _LOGGER.debug("_initiate_pairing_safe successful.")
            return {"ok": True}
        except Exception as e:
            _LOGGER.error("Error during pairing initiation: %s", e, exc_info=True)
            return {"ok": False, "error": "pairing_init_failed"}

    async def _wait_token_safe(self) -> Dict[str, Any]:
        """Safe wrapper for the wait_for_token phase to prevent exceptions from escaping."""
        _LOGGER.debug("Executing safe wrapper: _wait_token_safe")
        try:
            token = await self.acquirer.async_wait_for_token()
            _LOGGER.debug("_wait_token_safe successful, token acquired.")
            return {"ok": True, "token": token}
        except AuthTurnedOffError as e:
            _LOGGER.warning("AuthTurnedOffError caught in safe wrapper: %s", e)
            return {"ok": False, "error": "auth_failed_turned_off"}
        except TokenAcquisitionError as e:
            _LOGGER.warning("TokenAcquisitionError caught in safe wrapper: %s", e)
            return {"ok": False, "error": "token_acquisition_failed"}
        except Exception as e:
            _LOGGER.error("Unknown error while waiting for token: %s", e, exc_info=True)
            return {"ok": False, "error": "unknown_error"}

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle the initial step where the user chooses the device type."""
        if user_input is not None:
            self.flow_data[CONF_DEVICE_TYPE] = user_input[CONF_DEVICE_TYPE]
            device_type = self.flow_data[CONF_DEVICE_TYPE]

            if device_type == DEVICE_TYPE_SAMSUNG_2878:
                return await self.async_step_samsung_2878()
            
            # Route all new REST API based devices to a single configuration step
            if device_type in [
                DEVICE_TYPE_SAMSUNG_8888,
                DEVICE_TYPE_MIM_H03,
                DEVICE_TYPE_SMARTTHINGS_HVAC,
                DEVICE_TYPE_SMARTTHINGS_DHW,
            ]:
                return await self.async_step_rest_api()

            return self.async_abort(reason="not_implemented")

        # Expanded list of device types for the user to choose from
        device_types = {
            DEVICE_TYPE_SAMSUNG_2878: "Dispositivo Antiguo (Puerto 2878, token automático)",
            DEVICE_TYPE_SAMSUNG_8888: "Dispositivo Moderno (Puerto 8888, token manual)",
            DEVICE_TYPE_MIM_H03: "Controlador MIM-H03 (Puerto 8888, token manual)",
            DEVICE_TYPE_SMARTTHINGS_HVAC: "Controlador SmartThings - Climatización (Nube)",
            DEVICE_TYPE_SMARTTHINGS_DHW: "Controlador SmartThings - Agua Caliente (Nube)",
        }
        schema = vol.Schema({vol.Required(CONF_DEVICE_TYPE): vol.In(device_types)})
        return self.async_show_form(step_id="user", data_schema=schema)

    def _get_samsung_2878_schema(self, mac_required: bool = False) -> vol.Schema:
        """Helper to dynamically generate the schema for the Samsung 2878 step."""
        raw_mac = self.flow_data.get(CONF_MAC, "")
        formatted_mac = ":".join(raw_mac[i:i+2] for i in range(0, len(raw_mac), 2)) if raw_mac else ""

        schema_dict = {
            vol.Required(CONF_IP_ADDRESS, default=self.flow_data.get(CONF_IP_ADDRESS, "")): str,
        }
        
        if mac_required:
            schema_dict[vol.Required(CONF_MAC, default=formatted_mac)] = str
        else:
            schema_dict[vol.Optional(CONF_MAC, default=formatted_mac)] = str

        schema_dict.update({
            vol.Optional(CONF_NAME, default=self.flow_data.get(CONF_NAME, "")): str,
            vol.Optional(CONF_TOKEN, default=self.flow_data.get(CONF_TOKEN, "")): str,
            vol.Optional(CONF_CERT, default=self.flow_data.get(CONF_CERT, "")): str,
        })
        return vol.Schema(schema_dict)

    async def async_step_samsung_2878(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle IP/MAC input and resolution for old Samsung devices."""
        errors: Dict[str, str] = {}
        if user_input is not None:
            self.flow_data.update(user_input)
            ip_address = self.flow_data[CONF_IP_ADDRESS]
            mac_address = self.flow_data.get(CONF_MAC)

            if mac_address:
                self.flow_data[CONF_MAC] = mac_address.replace(":", "")
            else:
                _LOGGER.info("MAC address not provided, attempting to resolve from IP %s", ip_address)
                try:
                    resolved_mac = await self.hass.async_add_executor_job(
                        lambda: get_mac_address(ip=ip_address)
                    )
                    if not resolved_mac:
                        raise OSError("MAC address not found for the given IP.")
                    
                    _LOGGER.info("Successfully resolved MAC %s", resolved_mac)
                    self.flow_data[CONF_MAC] = resolved_mac.replace(":", "")
                
                except (OSError, HomeAssistantError):
                    _LOGGER.warning("Could not resolve MAC address. Asking user to provide it.")
                    errors["base"] = "mac_resolve_failed"
                    return self.async_show_form(
                        step_id="samsung_2878",
                        data_schema=self._get_samsung_2878_schema(mac_required=True),
                        errors=errors,
                    )
                except Exception as e:
                    _LOGGER.exception("Unexpected error during MAC resolution: %s", e)
                    errors["base"] = "unknown"
                    return self.async_show_form(
                        step_id="samsung_2878",
                        data_schema=self._get_samsung_2878_schema(),
                        errors=errors,
                    )

            await self.async_set_unique_id(self.flow_data[CONF_MAC])
            self._abort_if_unique_id_configured()

            if self.flow_data.get(CONF_TOKEN):
                return await self._create_entry()

            self.acquirer = SamsungTokenAcquirer(
                self.hass, self.flow_data[CONF_IP_ADDRESS], self.flow_data.get(CONF_CERT)
            )
            return await self.async_step_initiate_pairing()

        return self.async_show_form(
            step_id="samsung_2878",
            data_schema=self._get_samsung_2878_schema(),
            errors=errors,
        )

    def _get_rest_api_schema(self) -> vol.Schema:
        """Generate the schema for REST API based devices that require manual token."""
        device_type = self.flow_data.get(CONF_DEVICE_TYPE)
        
        schema = {}

        # IP Address / Host
        if device_type in [DEVICE_TYPE_SMARTTHINGS_HVAC, DEVICE_TYPE_SMARTTHINGS_DHW]:
            schema[vol.Required(CONF_IP_ADDRESS, default="api.smartthings.com")] = str
        else:
            schema[vol.Required(CONF_IP_ADDRESS)] = str

        # Device ID (optional or not present)
        if device_type in [DEVICE_TYPE_MIM_H03, DEVICE_TYPE_SMARTTHINGS_HVAC, DEVICE_TYPE_SMARTTHINGS_DHW]:
             schema[vol.Optional(CONF_DEVICE_ID)] = str
        # Note: DEVICE_TYPE_SAMSUNG_8888 does not have a device_id field.
        
        # Token and Name are common to all
        schema[vol.Required(CONF_TOKEN)] = str
        schema[vol.Optional(CONF_NAME)] = str
        
        # Certificate is used by local REST API devices
        if device_type in [DEVICE_TYPE_SAMSUNG_8888, DEVICE_TYPE_MIM_H03]:
            schema[vol.Optional(CONF_CERT)] = str

        return vol.Schema(schema)

    async def async_step_rest_api(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle configuration for REST API devices with manual token."""
        errors: Dict[str, str] = {}
        if user_input is not None:
            # Combine data for the connection test
            test_data = {**self.flow_data, **user_input}
            device_type = test_data.get(CONF_DEVICE_TYPE)
            test_data[CONF_CONFIG_FILE] = DEVICE_TYPE_TO_CONFIG_FILE.get(device_type)

            try:
                # Test the connection by creating a controller instance directly
                _LOGGER.debug("Testing connection with data: %s", test_data)
                controller = YamlController(test_data, _LOGGER)
                if not await controller.initialize():
                    # The controller's initialize method should return False on connection error
                    raise CannotConnect

                # If connection is successful, proceed
                self.flow_data.update(user_input)
                unique_id = self.flow_data.get(CONF_DEVICE_ID) or self.flow_data.get(CONF_IP_ADDRESS)
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return await self._create_entry()

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during connection test")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="rest_api",
            data_schema=self._get_rest_api_schema(),
            errors=errors,
        )

    async def async_step_initiate_pairing(self, user_input=None) -> FlowResult:
        """Phase 1: Put the device in pairing mode using a safe wrapper."""
        _LOGGER.debug("Entering async_step_initiate_pairing.")
        if not self.task:
            _LOGGER.debug("Creating task for _initiate_pairing_safe.")
            self.task = self.hass.async_create_task(self._initiate_pairing_safe())

        if self.task.done():
            _LOGGER.debug("Task _initiate_pairing_safe is done.")
            result = self.task.result()
            self.task = None

            if result["ok"]:
                _LOGGER.debug("Pairing initiation successful, advancing to await_button.")
                return self.async_show_progress_done(next_step_id="await_button")
            
            _LOGGER.warning("Pairing initiation failed with error: %s", result['error'])
            self.flow_data["error_key"] = result["error"]
            return self.async_show_progress_done(next_step_id="handle_error")


        _LOGGER.debug("Showing progress for 'initiating_pairing'.")
        return self.async_show_progress(
            step_id="initiate_pairing",
            progress_action="initiating_pairing",
            progress_task=self.task,
        )

    async def async_step_await_button(self, user_input=None) -> FlowResult:
        """Phase 2: Wait for the user to press the power button using a safe wrapper."""
        _LOGGER.debug("Entering async_step_await_button.")
        if not self.task:
            _LOGGER.debug("Creating task for _wait_token_safe.")
            self.task = self.hass.async_create_task(self._wait_token_safe())

        if self.task.done():
            _LOGGER.debug("Task _wait_token_safe is done.")
            result = self.task.result()
            self.task = None

            if result["ok"]:
                _LOGGER.debug("Token acquisition successful, advancing to create_entry.")
                self.flow_data[CONF_TOKEN] = result["token"]
                return self.async_show_progress_done(next_step_id="create_entry")

            _LOGGER.warning("Token acquisition failed with error: %s", result['error'])
            self.flow_data["error_key"] = result["error"]
            return self.async_show_progress_done(next_step_id="handle_error")

        _LOGGER.debug("Showing progress for 'awaiting_button_press'.")
        return self.async_show_progress(
            step_id="await_button",
            progress_action="awaiting_button_press",
            progress_task=self.task,
            description_placeholders={"ip_address": self.flow_data.get(CONF_IP_ADDRESS)},
        )
        
    async def async_step_handle_error(self, user_input=None) -> FlowResult:
        """Handles the display of errors after a progress step fails."""
        error_key = self.flow_data.pop("error_key", "unknown_error")
        errors = {"base": error_key}
        _LOGGER.debug("Displaying form with error: %s", error_key)
        return self.async_show_form(
            step_id="samsung_2878",
            data_schema=self._get_samsung_2878_schema(mac_required=False),
            errors=errors,
        )

    async def async_step_create_entry(self, user_input=None) -> FlowResult:
        """Final invisible step that creates the config entry."""
        _LOGGER.debug("Entering async_step_create_entry.")
        return await self._create_entry()

    async def _create_entry(self) -> FlowResult:
        """Create the config entry and finish the flow."""
        _LOGGER.debug("Entering _create_entry to finalize configuration.")
        if not self.unique_id:
            # The unique ID should have been set in the specific device step, this is a fallback.
            unique_id = (
                self.flow_data.get(CONF_DEVICE_ID) 
                or self.flow_data.get(CONF_MAC) 
                or self.flow_data.get(CONF_IP_ADDRESS)
            )
            await self.async_set_unique_id(unique_id)
        
        self._abort_if_unique_id_configured(updates=self.flow_data)
        
        title = self.flow_data.get(CONF_NAME) or f"Samsung AC {self.unique_id}"
        _LOGGER.debug("Creating config entry with title: %s and unique_id: %s", title, self.unique_id)
        
        return self.async_create_entry(title=title, data=self.flow_data)

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
