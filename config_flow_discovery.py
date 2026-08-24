# custom_components/climate_ip/config_flow_discovery.py
"""Discovery routines and indoor unit selection for Climate IP config flow."""

from __future__ import annotations

import logging
from typing import Any, cast

from homeassistant.config_entries import SOURCE_RECONFIGURE, ConfigFlowResult
from homeassistant.const import CONF_MAC
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import aiohttp_client, config_validation as cv
import voluptuous as vol

from . import controller_yaml
from .const import (
    CONF_CONFIG_FILE,
    CONF_CONN_METHOD,
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE,
    CONF_DEVICES,
    CONF_DISCOVERED_DEVICES,
    CONF_NAME,
    CONF_SELECTED_DEVICES,
    CONN_METHOD_RAW,
    DEVICE_TYPE_MIM_H03,
    DEVICE_TYPE_SAMSUNG_8888,
    DEVICE_TYPE_TO_CONFIG_FILE,
)
from .exceptions import InvalidHeaderError

_LOGGER = logging.getLogger(__name__)


class ConfigFlowDiscoveryMixin:
    """Mixin containing discovery routines and indoor unit selection for Climate IP config flow."""

    flow_data: dict[str, Any]
    hass: Any
    reauth_entry: Any | None

    async def _create_entry(self) -> ConfigFlowResult:
        """Stub for type checker, implemented in main config flow."""
        raise NotImplementedError  # pragma: no cover

    def async_abort(self, *args: Any, **kwargs: Any) -> Any:
        """Stub for type checker, implemented in FlowHandler."""
        raise NotImplementedError  # pragma: no cover

    def async_show_form(self, *args: Any, **kwargs: Any) -> Any:
        """Stub for type checker, implemented in FlowHandler."""
        raise NotImplementedError  # pragma: no cover

    async def async_set_unique_id(self, *args: Any, **kwargs: Any) -> Any:
        """Stub for type checker, implemented in FlowHandler."""
        raise NotImplementedError  # pragma: no cover

    def _abort_if_unique_id_configured(self, *args: Any, **kwargs: Any) -> Any:
        """Stub for type checker, implemented in FlowHandler."""
        raise NotImplementedError  # pragma: no cover

    async def _async_init_discovery_controller(
        self, config_data: dict[str, Any]
    ) -> controller_yaml.YamlController | None:
        """Instantiate and initialise a YamlController for device discovery.

        Returns the ready controller on success, or None if initialisation or
        the first status fetch fails. Callers are responsible for calling
        async_shutdown() on the returned controller.
        """
        controller = controller_yaml.YamlController(
            config=config_data,
            logger=_LOGGER,
            hass=self.hass,  # pragma: no mutate
            session=aiohttp_client.async_get_clientsession(
                self.hass
            ),  # pragma: no mutate
        )

        try:
            initialized: bool = await controller.initialize()
            status = await controller.async_get_status()
            status_ok: bool = bool(status)

            if not initialized or not status_ok:  # pragma: no mutate
                _LOGGER.error(
                    "Failed to initialize or get status during discovery."
                )  # pragma: no mutate
                await controller.async_shutdown()
                return None

            return controller

        except InvalidHeaderError:
            # CRITICAL: Shutdown before propagating the fallback signal
            await controller.async_shutdown()
            raise

        except Exception:
            # Failsafe shutdown on any other unforeseen error
            await controller.async_shutdown()
            raise

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
                if (
                    self.reauth_entry is None
                    and getattr(self, "source", None) != SOURCE_RECONFIGURE
                ):  # pragma: no mutate
                    self._abort_if_unique_id_configured(updates=self.flow_data)

                if ac_units_info:
                    self.flow_data[CONF_DISCOVERED_DEVICES] = ac_units_info
                    return await self.async_step_select_devices()
                return await self._create_entry()
            return cast(
                ConfigFlowResult, self.async_abort(reason="no_coordinator_uuid")
            )
        return cast(
            ConfigFlowResult, self.async_abort(reason="no_coordinator_found")
        )

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
        return cast(ConfigFlowResult, self.async_abort(reason="discovery_failed"))

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

        if not devices_info:  # pragma: no mutate
            return await self._create_entry()

        self.flow_data[CONF_DISCOVERED_DEVICES] = devices_info
        return await self.async_step_select_devices()

    async def _async_fallback_raw_discovery(
        self, config_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Helper to handle the fallback to raw socket connection if HTTP fails."""
        _LOGGER.warning(
            "[%s] Malformed HTTP headers detected during discovery. Automatically retrying with 'Robust (raw socket)' engine.",  # pragma: no mutate
            getattr(self, "unique_id", None) or "?",
        )  # pragma: no mutate
        self.flow_data[CONF_CONN_METHOD] = CONN_METHOD_RAW
        config_data[CONF_CONN_METHOD] = CONN_METHOD_RAW

        controller = None
        try:
            controller = controller_yaml.YamlController(
                config=config_data,
                logger=_LOGGER,
                hass=self.hass,  # pragma: no mutate
                session=aiohttp_client.async_get_clientsession(
                    self.hass
                ),  # pragma: no mutate
            )

            init_fb = await controller.initialize()
            status_fb = await controller.async_get_status()

            if not init_fb or not status_fb:
                _LOGGER.error(
                    "Failed to initialize with raw engine during discovery fallback."
                )  # pragma: no mutate
                return cast(ConfigFlowResult, self.async_abort(reason="cannot_connect"))

            return await self._create_entry()
        except Exception as raw_exc:  # pylint: disable=broad-exception-caught
            _LOGGER.exception(
                "Raw-engine fallback also failed: %s", raw_exc
            )  # pragma: no mutate
            return cast(ConfigFlowResult, self.async_abort(reason="cannot_connect"))
        finally:
            if controller is not None:
                await controller.async_shutdown()

    # pylint: disable=too-many-return-statements,too-many-branches,too-many-statements,unused-argument
    async def async_step_discover_uuid(
        self, user_input: Any | None = None
    ) -> ConfigFlowResult:
        """Step to discover indoor units from the device (Director)."""
        config_data = self.flow_data.copy()
        current_uid = getattr(self, "unique_id", None)
        if current_uid is not None:
            config_data["unique_id"] = current_uid

        device_type = config_data.get(CONF_DEVICE_TYPE)
        if CONF_CONFIG_FILE not in config_data and device_type is not None:
            cf = DEVICE_TYPE_TO_CONFIG_FILE.get(device_type)
            if cf is not None:
                config_data[CONF_CONFIG_FILE] = cf

        controller: controller_yaml.YamlController | None = None
        try:
            controller = await self._async_init_discovery_controller(config_data)
            if controller is None:
                return cast(ConfigFlowResult, self.async_abort(reason="cannot_connect"))

            discovered_devices = list(getattr(controller, "discovered_devices", []))

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
                    if (
                        self.reauth_entry is None
                        and getattr(self, "source", None) != SOURCE_RECONFIGURE
                    ):  # pragma: no mutate
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
                controller = None  # pragma: no mutate
            return await self._async_fallback_raw_discovery(config_data)

        except AbortFlow:
            raise  # Let Home Assistant handle its own flow control
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.exception("Discovery failed: %s", e)  # pragma: no mutate
            return cast(ConfigFlowResult, self.async_abort(reason="unknown_error"))
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

        def _build_select_schema() -> vol.Schema:
            def_keys = list(device_options.keys())
            req_key = vol.Required(
                CONF_SELECTED_DEVICES, default=def_keys
            )  # pragma: no mutate
            return vol.Schema(
                {req_key: cv.multi_select(device_options)}
            )  # pragma: no mutate

        if user_input:
            selected_devices_ids = (
                user_input.get(CONF_SELECTED_DEVICES) or []
            )  # pragma: no mutate
            if not selected_devices_ids:
                return cast(
                    ConfigFlowResult,
                    self.async_show_form(
                        step_id="select_devices",
                        data_schema=_build_select_schema(),
                        errors={"base": "no_devices_selected"},  # pragma: no mutate
                        description_placeholders={
                            "device_count": len(discovered_devices)
                        },
                    ),
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
                if (
                    self.reauth_entry is None
                    and getattr(self, "source", None) != SOURCE_RECONFIGURE
                ):  # pragma: no mutate
                    self._abort_if_unique_id_configured(updates=self.flow_data)
                return await self._create_entry()
            return cast(
                ConfigFlowResult, self.async_abort(reason="no_unique_id")
            )

        return cast(
            ConfigFlowResult,
            self.async_show_form(
                step_id="select_devices",
                data_schema=_build_select_schema(),
                description_placeholders={"device_count": len(discovered_devices)},
            ),
        )
