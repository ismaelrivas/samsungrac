# pylint: disable=broad-exception-caught,import-outside-toplevel,unused-argument
# custom_components/climate_ip/config_flow.py
"""Config flow for the Climate IP integration."""

import asyncio
import logging
from typing import Any, Self, override

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC
from homeassistant.core import callback

from . import const
from .config_flow_discovery import ConfigFlowDiscoveryMixin
from .config_flow_helpers import ConfigFlowHelpersMixin
from .config_flow_schemas import ConfigFlowSchemasMixin
from .const import CONF_DEVICE_TYPE, CONF_TOKEN, CONFIG_ENTRY_VERSION, DOMAIN
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
    """Config flow implementing a robust, multi-step pairing process."""

    VERSION = CONFIG_ENTRY_VERSION

    def __init__(self) -> None:
        """Initialize the config flow variables."""
        self.flow_data: dict[str, Any] = {}  # pragma: no mutate
        self.task: asyncio.Task[Any] | None = None
        self.acquirer: Any | None = None
        self.reauth_entry: ConfigEntry | None = None  # pragma: no mutate
        _LOGGER.debug(
            "Initializing new Climate IP config flow handler"
        )  # pragma: no mutate

    @override
    def is_matching(self, other_flow: Self) -> bool:
        """Return True if other_flow matches this flow (same physical device)."""
        s_mac = self.context.get(CONF_MAC) or self.flow_data.get(CONF_MAC)
        o_mac = other_flow.context.get(CONF_MAC) or other_flow.flow_data.get(CONF_MAC)
        if s_mac and o_mac:  # pragma: no mutate
            return str(s_mac).upper() == str(o_mac).upper()

        s_ip = self.context.get(CONF_IP_ADDRESS) or self.flow_data.get(CONF_IP_ADDRESS)
        o_ip = other_flow.context.get(CONF_IP_ADDRESS) or other_flow.flow_data.get(
            CONF_IP_ADDRESS
        )
        if s_ip and o_ip:  # pragma: no mutate
            return s_ip == o_ip

        return False

    async def async_step_import(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        """Handle the import of a YAML configuration (legacy platform)."""
        return await self._async_process_import(user_input)

    @override
    @callback
    def async_remove(self) -> None:
        """Clean up background tasks if the user cancels the flow."""
        _LOGGER.debug("Config flow cancelled. Cleaning up tasks")  # pragma: no mutate
        if self.task is not None:
            self.task.cancel()
        if self.acquirer is not None:
            self.hass.async_create_task(
                self.acquirer.async_close(),
                name="climate_ip_config_flow_acquirer_close",
                eager_start=True,
            )

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: The user chooses the device type."""
        if not user_input:
            return self.async_show_form(
                step_id="user", data_schema=self._get_user_schema()
            )

        dev_type = str(user_input[CONF_DEVICE_TYPE])
        self.flow_data[CONF_DEVICE_TYPE] = dev_type
        match dev_type:
            case const.DEVICE_TYPE_SAMSUNG_2878:
                return await self.async_step_samsung_2878()
            case const.DEVICE_TYPE_MIM_H03:
                return await self.async_step_mim_h03()
            case const.DEVICE_TYPE_SAMSUNG_8888:
                return await self.async_step_samsung_8888()
            case const.DEVICE_TYPE_SMARTTHINGS_HVAC | const.DEVICE_TYPE_SMARTTHINGS_DHW:
                return await self.async_step_rest_api()
            case const.DEVICE_TYPE_INTESISBOX:
                return await self.async_step_intesisbox()
            case _:
                return self.async_abort(reason="not_implemented")

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

    async def async_step_mim_h03(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Process step for MIM-H03 devices."""
        return await self._async_process_samsung_device_step(
            step_id="mim_h03", is_8888=True, user_input=user_input
        )

    async def async_step_intesisbox(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Process step for IntesisBox devices."""
        if user_input is not None:
            return await self._async_process_intesisbox_input(user_input)
        return self.async_show_form(
            step_id="intesisbox", data_schema=self._get_intesisbox_schema(), errors={}
        )

    async def async_step_rest_api(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle configuration for REST API devices with manual token."""
        if user_input:
            return await self._async_process_rest_api_input(user_input)
        return self.async_show_form(
            step_id="rest_api", data_schema=self._get_rest_api_schema(), errors={}
        )

    async def async_step_initiate_pairing(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Phase 1: Put the device in pairing mode using a safe wrapper."""
        return await self._async_step_initiate_pairing()

    async def async_step_await_button(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Phase 2: Wait for the user to press the required button."""
        return await self._async_step_await_button()

    async def async_step_test_connection(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Phase to validate the IP and token."""
        return await self._async_step_test_connection()

    async def async_step_handle_error(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Handles the display of errors after a progress step fails."""
        return self._async_build_error_step_result()

    async def async_step_create_entry(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Final invisible step that creates the config entry."""
        return await self._create_entry()

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication failure from the integration."""
        _LOGGER.debug(
            "Entering async_step_reauth with data: %s", entry_data
        )  # pragma: no mutate
        entry_id = self.context.get("entry_id")
        self.reauth_entry = (
            self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
        )
        if self.reauth_entry is None:
            return self.async_abort(reason="unknown_entry")

        self.flow_data = dict(self.reauth_entry.data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-authentication and route to the correct data acquisition step."""
        if user_input is not None and self.reauth_entry is not None:
            # fmt: off
            _LOGGER.debug('Reauth confirmed, clearing old token and routing to pairing step')  # pragma: no mutate
            # fmt: on
            self.flow_data.pop(CONF_TOKEN, None)

            dev_type = self.flow_data.get(CONF_DEVICE_TYPE)
            match dev_type:
                case (
                    const.DEVICE_TYPE_SMARTTHINGS_HVAC
                    | const.DEVICE_TYPE_SMARTTHINGS_DHW
                ):
                    return await self.async_step_rest_api()
                case const.DEVICE_TYPE_MIM_H03:
                    return await self.async_step_mim_h03()
                case const.DEVICE_TYPE_SAMSUNG_2878:
                    return await self.async_step_samsung_2878()
                case _:
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

    @override
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

        return await self.async_step_reconfigure_confirm(user_input)

    async def async_step_reconfigure_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the reconfiguration form and process its submission."""
        reconfigure_entry = self._get_reconfigure_entry()
        if user_input:
            return await self._async_process_reconfigure_input(
                reconfigure_entry, user_input
            )
        return self._async_show_reconfigure_form(
            {},
            self._get_initial_reconfigure_suggested(),
            {
                "device_name": reconfigure_entry.title,
                "ip_address": reconfigure_entry.data.get(CONF_IP_ADDRESS) or "",
            },
        )
