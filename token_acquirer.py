# pylint: disable=no-else-raise,too-many-branches,too-many-locals,too-many-statements
"""Helper to acquire a token from older Samsung AC units in phases."""

import asyncio
import logging
import os
import re
import ssl
from typing import Any

from .exceptions import (
    AuthTurnedOffError,
    CannotConnect,
    CertNotFound,
    TokenAcquisitionError,
)
from .helpers import mask_sensitive_data

_LOGGER = logging.getLogger(__name__)

# Precompiled regex for status and token extraction
ERROR_CODE_RE = re.compile(r'ErrorCode="(\d+)"')
TOKEN_RE = re.compile(r'Token="([a-fA-F0-9-]{36})"')


class SamsungTokenAcquirer:
    """Manages the phased token acquisition process."""
# pylint: disable=no-else-raise,too-many-branches,too-many-locals,too-many-statements

    def __init__(self, hass: Any, ip_address: str, cert_path: str | None = None) -> None:
        """Initialize the acquirer."""
        self._hass = hass
        self._ip_address = ip_address
        self._user_cert_path = cert_path  # Store the original user-provided path
        self._resolved_cert_path: str | None = None

        # Resolve the certificate path. If a path without a directory is provided,
        # assume it is relative to the integration's directory.
        if cert_path:
            if not os.path.dirname(cert_path):
                self._resolved_cert_path = os.path.join(
                    os.path.dirname(__file__), cert_path
                )
            else:
                # The path is absolute or contains directory components, use it as is.
                self._resolved_cert_path = cert_path
        else:
            self._resolved_cert_path = None

        _LOGGER.debug(
            "Final resolved certificate path to be used for connection: %s",
            self._resolved_cert_path,
        )

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def _connect(self) -> dict[str, Any] | None:
        """
        Establish a connection to the device by trying different certificate
        and cipher strategies. Returns a dictionary with the successful
        certificate path and verify mode.
        """
        last_error: Exception | None = None

        # Define cipher suites to try
        cipher_configs = [
            ("HIGH:!DH:!aNULL:@SECLEVEL=0", "Cipher Suite A"),
            ("HIGH:!aNULL:!MD5:@SECLEVEL=0", "Cipher Suite B"),
            ("ALL:@SECLEVEL=0", "Cipher Suite C"),
        ]

        # Define certificate strategies based on user input
        resolved_user_cert = self._resolved_cert_path
        default_cert_path = os.path.join(os.path.dirname(__file__), "ac14k_m.pem")

        strategies: list[dict[str, Any]] = []
        if resolved_user_cert:
            # If a user certificate is provided, try strict verification first.
            strategies.append(
                {
                    "cert": resolved_user_cert,
                    "name": "User Cert (Strict Verify)",
                    "verify_mode": ssl.CERT_REQUIRED,
                }
            )
            strategies.append(
                {
                    "cert": resolved_user_cert,
                    "name": "User Cert (No Verify)",
                    "verify_mode": ssl.CERT_NONE,
                }
            )
            # As a fallback, try with no certificate at all.
            strategies.append({"cert": None, "name": "No Certificate (Fallback)"})
        else:
            # If no user certificate, the only possible verification mode is CERT_NONE.
            strategies.append({"cert": None, "name": "No Certificate (Default)"})
            # As a fallback, try with the integration's default certificate.
            strategies.append({"cert": default_cert_path, "name": "Default Certificate (Fallback)"})

        # Build a list of all possible connection attempts
        all_attempts = [
            {
                "cert": strategy["cert"],
                "verify_mode": strategy.get("verify_mode", ssl.CERT_NONE),
                "cipher_config": cipher_config,
                "strategy_name": strategy["name"],
            }
            for strategy in strategies
            for cipher_config in cipher_configs
        ]

        failed_attempts_log = []

        for attempt in all_attempts:
            cert_path = attempt["cert"]
            ciphers, cipher_name = attempt["cipher_config"]
            strategy_name = attempt["strategy_name"]
            verify_mode = attempt["verify_mode"]

            try:
                # pylint: disable=import-outside-toplevel
                from .helpers import async_create_samsung_ssl_context

                try:
                    ssl_context = await async_create_samsung_ssl_context(
                        cert_path=cert_path, ciphers=ciphers, verify_mode=verify_mode
                    )
                except (ssl.SSLError, FileNotFoundError) as e:
                    failed_attempts_log.append(f"CertError({strategy_name}): {e}")
                    raise CertNotFound(f"Failed to load certificate file: {e}") from e

                # Modern python 3.11+ timeout usage
                async with asyncio.timeout(15.0):
                    # FIXED C0301: Split long open_connection call
                    self._reader, self._writer = await asyncio.open_connection(
                        self._ip_address, 2878, ssl=ssl_context
                    )

                _LOGGER.info(
                    "SSL connection successful with Strategy: '%s', Cipher: '%s'",
                    strategy_name,
                    cipher_name,
                )

                # Attempt to log the negotiated TLS version
                try:
                    ssl_obj = self._writer.get_extra_info("ssl_object")
                    negotiated_tls = ssl_obj.version() if ssl_obj else "Unknown"
                    _LOGGER.debug(
                        "[SamsungTokenAcquirer] Negotiated TLS Version: %s",
                        negotiated_tls,
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    pass

                # Connection successful, read initial handshake and return working config
                try:
                    async with asyncio.timeout(15.0):
                        if self._reader:
                            initial_data = await self._reader.read(4096)
                            _LOGGER.debug(
                                "Received initial handshake: %s",
                                initial_data.decode("utf-8", "ignore"),
                            )
                except TimeoutError:
                    _LOGGER.warning(
                        "Did not receive initial handshake, but connection is open. Continuing."
                    )

                # --- Return Logic ---
                successful_config: dict[str, Any] = {"cert": None, "verify_mode": verify_mode}
                if cert_path == resolved_user_cert:
                    successful_config["cert"] = self._user_cert_path
                elif cert_path == default_cert_path:
                    successful_config["cert"] = os.path.basename(default_cert_path)

                if failed_attempts_log:
                    _LOGGER.debug("Previous failed connection attempts: %s", failed_attempts_log)

                _LOGGER.info(
                    "Successful connection config found: cert='%s', verify_mode=%s",
                    successful_config.get("cert"),
                    successful_config.get("verify_mode"),
                )
                return successful_config

            except TimeoutError as e:
                failed_attempts_log.append(f"{strategy_name}/{cipher_name}: Timeout")
                last_error = e
            except (ConnectionRefusedError, OSError) as e:
                failed_attempts_log.append(f"{strategy_name}/{cipher_name}: {e}")
                last_error = e
            except CertNotFound as e:
                failed_attempts_log.append(f"CertNotFound({strategy_name}): {e}")
                continue
            except Exception as e:  # pylint: disable=broad-exception-caught
                failed_attempts_log.append(f"{strategy_name}/{cipher_name} unexpected error: {e}")
                last_error = e

            # If an attempt fails, close the connection and wait before the next try.
            await self.async_close()
            await asyncio.sleep(1.5)

        # If all attempts failed
        _LOGGER.warning(
            "All connection attempts failed. Summary of errors: %s",
            failed_attempts_log,
        )
        raise CannotConnect(
            f"All connection attempts failed. Last error: {last_error}"
        ) from last_error

    async def async_initiate_pairing(self) -> dict[str, Any] | None:
        """
        Phase 1: Connects, puts the device in pairing mode,
        and returns the successful connection config.
        """
        _LOGGER.info("Initiating pairing for %s", self._ip_address)
        successful_config = await self._connect()

        if not self._writer:
            raise TokenAcquisitionError("Connection failed, writer not available.")

        request_msg = b'<Request Type="GetToken" />\r\n'
        _LOGGER.debug("Sending GetToken request: %s", request_msg.decode("utf-8").strip())
        self._writer.write(request_msg)
        await self._writer.drain()

        try:
            if not self._reader:
                raise TokenAcquisitionError("Connection failed, reader not available.")

            async with asyncio.timeout(15.0):
                data = await self._reader.read(4096)

            decoded_data = data.decode("utf-8", "ignore")
            _LOGGER.debug("Received response for GetToken: %s", decoded_data.strip())

            # FIXED C0301: Split long condition for readability
            is_valid_resp = (
                '<Response Type="GetToken" Status="Ready"/>' in decoded_data
                or "InvalidateAccount" in decoded_data
            )
            if not is_valid_resp:
                raise TokenAcquisitionError("Did not receive 'Ready' status from AC unit")

            _LOGGER.info("AC unit is 'Ready'. Pairing initiated successfully.")
            return successful_config  # Return the successful config dict

        except TimeoutError as exc:
            raise TokenAcquisitionError("Timeout waiting for 'Ready' response") from exc

    async def async_wait_for_token(self) -> str:
        """
        Phase 2: Waits for the user to press the power button and retrieves the token.
        """
        if not self._reader:
            raise TokenAcquisitionError("Connection not established. Run initiate_pairing first")

        _LOGGER.info("Now listening for the token...")
        try:
            async with asyncio.timeout(45.0):
                data = await self._reader.read(4096)

            if not data:
                raise TokenAcquisitionError("Connection closed by device.")

            decoded_buffer = data.decode("utf-8", "ignore")
            _LOGGER.debug(
                "Received data after button press: %s",
                mask_sensitive_data(decoded_buffer),
            )

            if 'Status="Fail"' in decoded_buffer and 'Type="Authenticate"' in decoded_buffer:
                error_code_match = ERROR_CODE_RE.search(decoded_buffer)
                error_code = error_code_match.group(1) if error_code_match else "Unknown"
                _LOGGER.error("Authentication failed with ErrorCode: %s", error_code)
                if error_code == "301":
                    raise AuthTurnedOffError(
                        "Authentication failed: The device was likely turned off "
                        "instead of on (ErrorCode 301)."
                    )
                else:
                    raise TokenAcquisitionError(
                        f"Authentication failed with ErrorCode {error_code}"
                    )

            token_match = TOKEN_RE.search(decoded_buffer)
            if token_match:
                _LOGGER.info("Successfully acquired token.")
                return token_match.group(1)

            raise TokenAcquisitionError("Received unexpected data instead of a token")
        except TimeoutError as exc:
            raise TokenAcquisitionError("Token not received within the 45-second window") from exc
        finally:
            await self.async_close()

    async def async_close(self) -> None:
        """Closes the connection."""
        if self._writer:
            _LOGGER.info("Closing connection.")
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except (ssl.SSLError, ConnectionResetError, asyncio.CancelledError):
                _LOGGER.debug("Ignoring non-critical error during connection close.")
