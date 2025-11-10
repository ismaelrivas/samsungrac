# custom_components/climate_ip/token_acquirer.py
"""Helper to acquire a token from older Samsung AC units in phases."""
import asyncio
import logging
import os
import re
import ssl
from typing import Optional, Tuple

_LOGGER = logging.getLogger(__name__)

class TokenAcquisitionError(Exception):
    """Base custom exception for token acquisition errors."""

class AuthTurnedOffError(TokenAcquisitionError):
    """Raised when authentication fails because the device was turned off (ErrorCode 301)."""

class SamsungTokenAcquirer:
    """Manages the phased token acquisition process."""

    def __init__(self, hass, ip_address: str, cert_path: Optional[str] = None):
        """Initialize the acquirer."""
        self._hass = hass
        self._ip_address = ip_address
        self._cert_path = cert_path
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def _connect(self) -> None:
        """Establish a connection to the device."""
        _LOGGER.debug("Step 1: Creating SSL context")
        ssl_context = None
        try:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
            ssl_context.set_ciphers("HIGH:!DH:!aNULL:@SECLEVEL=0")
            
            # For local IoT devices with self-signed certs, it's often necessary
            # to disable certificate verification to establish an SSL connection.
            # The connection will still be encrypted.
            ssl_context.verify_mode = ssl.CERT_NONE
            ssl_context.check_hostname = False

            # We still log if a cert is provided, as it might be useful for debugging,
            # but we won't use it for verification, which was causing the error.
            if self._cert_path:
                _LOGGER.debug(
                    "Certificate path provided but verification is disabled for compatibility."
                )

        except Exception as e:
            _LOGGER.error("An unexpected error occurred while creating SSL context: %s", e)
            raise TokenAcquisitionError(f"Failed to create SSL context: {e}")
        
        try:
            _LOGGER.debug("Step 2: Attempting connection to %s:2878", self._ip_address)
            conn_future = asyncio.open_connection(self._ip_address, 2878, ssl=ssl_context)
            self._reader, self._writer = await asyncio.wait_for(conn_future, timeout=15)
            _LOGGER.info("SSL connection successful.")
        except (ssl.SSLError, ConnectionResetError, OSError) as e:
            # This block might now be less likely to be hit for verification errors,
            # but we keep it for other SSL issues.
            _LOGGER.warning("SSL connection failed (%s). Retrying with a plain connection.", e)
            conn_future = asyncio.open_connection(self._ip_address, 2878)
            self._reader, self._writer = await asyncio.wait_for(conn_future, timeout=15)
            _LOGGER.info("Plain TCP connection successful.")
        
        try:
            initial_data = await asyncio.wait_for(self._reader.read(4096), timeout=15.0)
            _LOGGER.debug("Received initial handshake: %s", initial_data.decode('utf-8', 'ignore'))
        except asyncio.TimeoutError:
            _LOGGER.warning("Did not receive an initial handshake, continuing anyway.")

    async def async_initiate_pairing(self) -> None:
        """
        Phase 1: Connects and puts the device in pairing mode.
        """
        _LOGGER.info("Initiating pairing for %s", self._ip_address)
        await self._connect()
        
        if not self._writer:
            raise TokenAcquisitionError("Connection failed, writer not available.")

        self._writer.write(b'<Request Type="GetToken" />\r\n')
        await self._writer.drain()

        try:
            data = await asyncio.wait_for(self._reader.read(4096), timeout=15.0)
            decoded_data = data.decode('utf-8', 'ignore')
            if '<Response Type="GetToken" Status="Ready"/>' not in decoded_data:
                raise TokenAcquisitionError("Did not receive 'Ready' status from AC unit")
            _LOGGER.info("AC unit is 'Ready'. Pairing initiated successfully.")
        except asyncio.TimeoutError:
            raise TokenAcquisitionError("Timeout waiting for 'Ready' response")

    async def async_wait_for_token(self) -> str:
        """
        Phase 2: Waits for the user to press the power button and retrieves the token.
        """
        if not self._reader:
            raise TokenAcquisitionError("Connection not established. Run initiate_pairing first")
        
        _LOGGER.info("Now listening for the token...")
        try:
            data = await asyncio.wait_for(self._reader.read(4096), timeout=45.0)
            
            if not data:
                raise TokenAcquisitionError("Connection closed by device.")

            decoded_buffer = data.decode('utf-8', 'ignore')
            _LOGGER.debug("Received data after button press: %s", decoded_buffer)
            
            if 'Status="Fail"' in decoded_buffer and 'Type="Authenticate"' in decoded_buffer:
                error_code_match = re.search(r'ErrorCode="(\d+)"', decoded_buffer)
                error_code = error_code_match.group(1) if error_code_match else "Unknown"
                _LOGGER.error("Authentication failed with ErrorCode: %s", error_code)
                if error_code == "301":
                    raise AuthTurnedOffError("Authentication failed: The device was likely turned off instead of on (ErrorCode 301).")
                else:
                    raise TokenAcquisitionError(f"Authentication failed with ErrorCode {error_code}")

            token_match = re.search(r'Token="([a-fA-F0-9-]{36})"', decoded_buffer)
            if token_match:
                _LOGGER.info("Successfully acquired token.")
                return token_match.group(1)
            
            raise TokenAcquisitionError("Received unexpected data instead of a token")
        except asyncio.TimeoutError:
            raise TokenAcquisitionError("Token not received within the 45-second window")
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
