# custom_components/climate_ip/config_flow_helpers.py
"""Connectivity, pairing, and validation helpers for Climate IP config flow."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
import ssl
from typing import Any

from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_TOKEN
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import aiohttp_client, device_registry as dr

from . import controller_yaml, helpers
from .const import (
    CONF_CERT,
    CONF_CONFIG_FILE,
    CONF_DEVICE_TYPE,
    DEVICE_TYPE_8888_GROUP,
    DEVICE_TYPE_SAMSUNG_2878,
    DEVICE_TYPE_TO_CONFIG_FILE,
    GLOBAL_HTTP_TIMEOUT,
    PORT_SAMSUNG_2878,
    PORT_SAMSUNG_8888,
)
from .exceptions import (
    AuthError,
    AuthTurnedOffError,
    CannotConnect,
    TokenAcquisitionError,
)

_LOGGER = logging.getLogger(__name__)


class ConfigFlowHelpersMixin:
    """Mixin containing connectivity and pairing helpers for Climate IP config flow."""

    flow_data: dict[str, Any]
    hass: Any
    acquirer: Any | None
    reauth_entry: Any | None

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
            except (TimeoutError, OSError):
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
                    "MAC auto-discovery failed. Requesting manual input."
                )  # pragma: no mutate
                return "mac_resolve_failed"

        await self.async_set_unique_id(str(self.flow_data[CONF_MAC]))  # type: ignore[attr-defined]
        if self.reauth_entry is None:
            if getattr(self, "source", None) != SOURCE_RECONFIGURE:
                self._abort_if_unique_id_configured()  # type: ignore[attr-defined]

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
            ip_address = str(
                self.flow_data.get(CONF_IP_ADDRESS, "Unknown")
            )  # pragma: no mutate
            _LOGGER.error(
                "Fatal pairing failure at %s. Details: %s", ip_address, err
            )  # pragma: no mutate
            return {
                "ok": False,
                "error": "pairing_connection_failed",
                "error_details": str(err),  # pragma: no mutate
            }
        except (AuthError, TokenAcquisitionError) as err:
            _LOGGER.warning(
                "Connection error during pairing initiation: %s", err
            )  # pragma: no mutate
            return {
                "ok": False,
                "error": "pairing_connection_failed",
                "error_details": str(err),  # pragma: no mutate
            }
        except TimeoutError as err:
            ip_address = str(
                self.flow_data.get(CONF_IP_ADDRESS, "Unknown")
            )  # pragma: no mutate
            _LOGGER.warning(
                "Timeout connecting to %s. Wrong IP?", ip_address
            )  # pragma: no mutate
            return {
                "ok": False,
                "error": "timeout_connect",
                "error_details": str(err),  # pragma: no mutate
            }
        except AbortFlow:
            raise  # Let Home Assistant handle its own flow control
        except Exception as e:
            _LOGGER.exception(
                "Unexpected error during pairing: %s", e
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
            ip_address = str(
                self.flow_data.get(CONF_IP_ADDRESS, "Unknown")
            )  # pragma: no mutate
            _LOGGER.warning(
                "Timeout connecting to %s. Wrong IP?", ip_address
            )  # pragma: no mutate
            return {
                "ok": False,
                "error": "timeout_connect",
                "error_details": str(err),  # pragma: no mutate
            }
        except (TokenAcquisitionError, AuthTurnedOffError) as e:
            _LOGGER.warning("Token acquisition failed: %s", e)  # pragma: no mutate
            return {"ok": False, "error": "token_acquisition_failed"}
        except AbortFlow:
            raise  # Let Home Assistant handle its own flow control
        except Exception as e:
            _LOGGER.exception(
                "Unknown error while waiting for token: %s", e
            )  # pragma: no mutate
            return {"ok": False, "error": "unknown_error"}

    @staticmethod
    def _build_ssl_context(cert_path: str) -> ssl.SSLContext:
        """Build an SSL context, loading certificate if provided (sync, executor-safe)."""
        ssl_context = ssl.create_default_context()
        if cert_path:
            # Protect os.path.dirname from receiving a None value
            full_path = helpers.resolve_cert_path(
                cert_path, os.path.dirname(__file__)
            )  # pragma: no mutate
            if full_path is not None and os.path.exists(full_path):
                # Protect the underlying SSL C library from receiving a None value
                ssl_context.load_verify_locations(cafile=full_path)  # pragma: no mutate
        else:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        return ssl_context

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
                session = aiohttp_client.async_get_clientsession(self.hass)
                url = f"https://{ip_address}:{PORT_SAMSUNG_8888}/devices"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }  # pragma: no mutate

                cert_path = str(self.flow_data.get(CONF_CERT) or "")
                ssl_context = await self.hass.async_add_executor_job(
                    self._build_ssl_context, cert_path
                )

                async with session.get(
                    url,
                    headers=headers,
                    ssl=ssl_context,
                    timeout=GLOBAL_HTTP_TIMEOUT,  # type: ignore[arg-type] # pragma: no mutate
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

                controller = controller_yaml.YamlController(
                    config=config_data, logger=_LOGGER
                )
                controller.hass = self.hass
                # pylint: disable=protected-access
                controller._session = aiohttp_client.async_get_clientsession(self.hass)

                initialized = await controller.initialize()
                if not initialized:
                    return {"ok": False, "error": "cannot_connect"}  # pragma: no mutate

                state_data = None
                if (
                    controller.loader is not None
                    and controller.loader.state_getter is not None  # pragma: no mutate
                ):
                    state_data = (
                        await controller.loader.state_getter.async_update_state(
                            None,
                            False,  # pragma: no mutate
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
            ip_address = str(
                self.flow_data.get(CONF_IP_ADDRESS, "Unknown")
            )  # pragma: no mutate
            _LOGGER.error(
                "Fatal pairing failure at %s. Details: %s", ip_address, err
            )  # pragma: no mutate
            return {
                "ok": False,
                "error": "pairing_connection_failed",
                "error_details": str(err),  # pragma: no mutate
            }
        except TimeoutError as err:
            ip_address = str(
                self.flow_data.get(CONF_IP_ADDRESS, "Unknown")
            )  # pragma: no mutate
            _LOGGER.warning(
                "Timeout connecting to %s. Wrong IP?", ip_address
            )  # pragma: no mutate
            return {
                "ok": False,
                "error": "timeout_connect",
                "error_details": str(err),  # pragma: no mutate
            }
        except AuthError as err:
            _LOGGER.warning("AC rejected token during pairing.")  # pragma: no mutate
            return {
                "ok": False,
                "error": "invalid_auth",
                "error_details": str(err),  # pragma: no mutate
            }
        except AbortFlow:
            raise  # Let Home Assistant handle its own flow control
        except Exception as e:  # pylint: disable=broad-exception-caught
            _LOGGER.exception(
                "Unknown error during connection test: %s", e
            )  # pragma: no mutate
            return {"ok": False, "error": "cannot_connect"}
