"""Data-driven token acquirer engine based on YAML configuration."""

import asyncio
from contextlib import suppress
import logging
from pathlib import Path
import re
import ssl
from typing import Any

from homeassistant.core import HomeAssistant

from .exceptions import AuthTurnedOffError, CannotConnect, TokenAcquisitionError
from .helpers import async_create_samsung_ssl_context

_LOGGER = logging.getLogger(__name__)

DEFAULT_CIPHER = "HIGH:!aNULL:!MD5:@SECLEVEL=0"
DEFAULT_BUFFER_SIZE = 4096


# ==========================================
# PURE PROTOCOL & PARSING HELPERS (Zero I/O)
# ==========================================
def _extract_token(
    text: str, regex: str | None, *, strip_quotes: bool = False
) -> str | None:
    """Extract token from decoded payload using regex safely."""
    if not text or not regex:
        return None
    match = re.search(regex, text)
    if not match:
        return None
    token = match.group(1)
    return token.strip('"') if strip_quotes else token


def _normalize_http_response(response: str) -> bytes:
    """Normalize HTTP line endings to CRLF and encode to UTF-8."""
    return response.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def _encode_stream_payload(raw_payload: str | bytes) -> bytes:
    """Convert YAML stream payload (with escaped CRLF) into raw bytes."""
    if isinstance(raw_payload, str):
        return raw_payload.replace("\\r", "\r").replace("\\n", "\n").encode("utf-8")
    return raw_payload


def _build_raw_http_post(
    path: str, host: str, headers: dict[str, Any], body: str | bytes
) -> bytes:
    """Construct a raw HTTP/1.1 POST request frame."""
    body_bytes = body.encode("utf-8") if isinstance(body, str) else body
    body_str = body if isinstance(body, str) else body.decode("utf-8")

    req_headers = dict(headers)
    if body and "Content-Length" not in req_headers:
        req_headers["Content-Length"] = str(len(body_bytes))

    req_lines = [f"POST {path} HTTP/1.1", f"Host: {host}"]
    req_lines.extend(f"{k}: {v}" for k, v in req_headers.items())
    req_lines.extend(["", body_str])
    return "\r\n".join(req_lines).encode("utf-8")


def _is_stream_pairing_accepted(
    decoded: str, match_str: str, fallback_str: str
) -> bool:
    """Verify whether the initial stream response matches expected templates."""
    if not match_str or match_str in decoded:
        return True
    return bool(fallback_str and fallback_str in decoded)


async def _safe_close_resource(resource_obj: Any) -> None:
    """Safely close an asyncio Server or StreamWriter without raising."""
    if resource_obj is None:
        return
    with suppress(Exception):
        resource_obj.close()
        await resource_obj.wait_closed()


class GenericYamlTokenAcquirer:
    """100% Data-Driven token acquirer engine based on YAML configuration."""

    MAX_PORT_RETRIES = 5

    def __init__(
        self,
        hass: HomeAssistant,
        ip_address: str,
        auth_config: dict[str, Any],
        cert_path: str | None = None,
    ) -> None:
        """Initialize the generic YAML token acquirer."""
        self.hass = hass
        self.ip_address = ip_address
        self.auth_config = auth_config
        self.user_cert_path = cert_path

        # Listener State
        self._token_received_event = asyncio.Event()
        self._received_token: str | None = None
        self._server: asyncio.AbstractServer | None = None
        self._bound_port: int | None = None

        # Stream State
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._initial_stream_data: str | None = None

    @property
    def _buffer_size(self) -> int:
        return int(self.auth_config.get("buffer_size", DEFAULT_BUFFER_SIZE))

    @property
    def _extract_regex(self) -> str | None:
        val = self.auth_config.get("extract_template", {}).get("regex")
        return str(val) if val is not None else None

    @property
    def _local_ip(self) -> str:
        return (
            getattr(getattr(self.hass, "config", None), "api", None)
            and getattr(self.hass.config.api, "local_ip", None)
        ) or "0.0.0.0"

    def _resolve_cert_path(self, cert_sentinel: str | None) -> str | None:
        """Resolve the YAML sentinel to an absolute file path."""
        if cert_sentinel == "__user_cert__":
            path = self.user_cert_path
        elif cert_sentinel == "__default_cert__":
            path = self.auth_config.get("tls_config", {}).get("default_cert")
        else:
            path = cert_sentinel

        if path and not ("/" in path or "\\" in path):
            return str(Path(__file__).parent / path)
        return path

    # ==========================================
    # LISTENER MODE LOGIC (Port 8888 / 8889)
    # ==========================================
    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle incoming client connection on the local listener server."""
        try:
            buffer_size = self._buffer_size
            extract_regex = self._extract_regex
            data = b""
            token = None

            with suppress(TimeoutError):
                async with asyncio.timeout(10.0):
                    while True:
                        chunk = await reader.read(buffer_size)
                        if not chunk:
                            break
                        data += chunk
                        decoded_check = data.decode(
                            "utf-8", errors="ignore"
                        )  # pragma: no mutate
                        token = _extract_token(
                            decoded_check, extract_regex, strip_quotes=True
                        )
                        if token:
                            break

            if not token and data:
                decoded_data = data.decode(
                    "utf-8", errors="ignore"
                )  # pragma: no mutate
                token = _extract_token(decoded_data, extract_regex, strip_quotes=True)

            listener_cfg = self.auth_config.get("listener", {})
            if token:
                _LOGGER.info("Token successfully received by listener")
                self._received_token = token
                self._token_received_event.set()
                response = listener_cfg.get(
                    "success_response", "HTTP/1.1 200 OK\r\n\r\n"
                )
            else:
                _LOGGER.warning(
                    "Connection received by listener, but no token could be extracted"
                )
                response = listener_cfg.get(
                    "error_response", "HTTP/1.1 400 Bad Request\r\n\r\n"
                )

            writer.write(_normalize_http_response(response))
            await writer.drain()

        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Error in listener: %s", e)  # pragma: no mutate
        finally:
            await _safe_close_resource(writer)

    async def _start_listener_server(self) -> None:
        """Start the local TLS listener server with automatic EADDRINUSE port fallback."""
        await _safe_close_resource(self._server)
        self._server = None

        listener_cfg = self.auth_config.get("listener", {})
        base_port = listener_cfg.get("port", 8889)
        tls_cfg = self.auth_config.get("tls_config", {})

        cert_path = self._resolve_cert_path(tls_cfg.get("default_cert"))
        ciphers_list = tls_cfg.get("ciphers") or [DEFAULT_CIPHER]
        ciphers = ciphers_list[0]

        ssl_context = await async_create_samsung_ssl_context(
            cert_path=cert_path, ciphers=ciphers, is_server=True
        )

        bind_ip = self._local_ip
        last_error: OSError | None = None

        for offset in range(self.MAX_PORT_RETRIES):
            port = base_port + offset
            try:
                self._server = await asyncio.start_server(
                    self._handle_client, bind_ip, port, ssl=ssl_context
                )
            except OSError as err:
                if err.errno == 98:  # EADDRINUSE
                    _LOGGER.debug("Port %s already in use, trying next port", port)
                    last_error = err
                    continue
                raise
            else:
                if offset > 0:
                    _LOGGER.info(
                        "Listener port %s was busy, successfully bound to fallback port %s",
                        base_port,
                        port,
                    )
                self._bound_port = port
                listener_cfg["port"] = port
                return

        if last_error is not None:
            raise last_error

    async def _initiate_listener_pairing(
        self, req_cfg: dict[str, Any]
    ) -> dict[str, Any]:
        """Start local listener and send initial HTTP POST trigger to device."""
        await self._start_listener_server()

        tls_cfg = self.auth_config.get("tls_config", {})
        cert_path = self._resolve_cert_path(tls_cfg.get("default_cert"))
        ciphers_list = tls_cfg.get("ciphers") or ["HIGH"]
        verify_mode = getattr(
            ssl, tls_cfg.get("verify_mode", "CERT_NONE"), ssl.CERT_NONE
        )

        ssl_ctx = await async_create_samsung_ssl_context(
            cert_path=cert_path, ciphers=ciphers_list[0], verify_mode=verify_mode
        )

        target_port = req_cfg.get("port", 8888)
        listener_port = (
            self._bound_port
            if self._bound_port is not None
            else self.auth_config["listener"]["port"]
        )
        host = f"{self._local_ip}:{listener_port}"
        path = req_cfg.get("path", "/devicetoken/request")
        raw_request = _build_raw_http_post(
            path=path,
            host=host,
            headers=req_cfg.get("headers", {}),
            body=req_cfg.get("payload", ""),
        )

        writer: asyncio.StreamWriter | None = None
        try:
            reader, writer = await asyncio.open_connection(
                self.ip_address, target_port, ssl=ssl_ctx
            )
            writer.write(raw_request)
            await writer.drain()
        except (TimeoutError, ConnectionError, OSError) as err:
            await _safe_close_resource(writer)
            await self.async_close()
            raise CannotConnect(
                f"Failed to connect to device via raw socket ({self.ip_address}:{target_port}): {err}"
            ) from err

        with suppress(Exception):
            await asyncio.wait_for(reader.read(DEFAULT_BUFFER_SIZE), timeout=5.0)

        await _safe_close_resource(writer)
        return {"ok": True, "config": "listener_started"}

    async def _wait_listener_token(self) -> str:
        """Wait for the local listener server to capture the token."""
        timeout = self.auth_config.get("listener", {}).get("timeout_seconds", 60)
        async with asyncio.timeout(timeout):
            await self._token_received_event.wait()
        if self._received_token is None:
            raise TokenAcquisitionError("Token was not received.")
        return self._received_token

    # ==========================================
    # STREAM MODE LOGIC (Port 2878)
    # ==========================================
    async def _connect_plain_tcp(self, port: int) -> dict[str, Any]:
        """Establish a plain TCP connection and consume optional initial banner."""
        try:
            async with asyncio.timeout(15.0):
                self._reader, self._writer = await asyncio.open_connection(
                    self.ip_address, port, ssl=None
                )
                with suppress(TimeoutError):
                    async with asyncio.timeout(1.0):
                        await self._reader.read(self._buffer_size)
                return {"plain_tcp": True}
        except Exception as err:
            await self.async_close()
            raise CannotConnect(
                f"Failed to connect via plain TCP to {self.ip_address}:{port}: {err}"
            ) from err

    async def _connect_stream(self) -> dict[str, Any]:
        """Establish a stream socket connection across configured strategies or plain TCP."""
        tls_cfg = self.auth_config.get("tls_config", {})
        req_cfg = self.auth_config.get("request_pairing", {})
        port = req_cfg.get("port", 2878)

        if tls_cfg.get("enabled") is False or req_cfg.get("method") == "tcp":
            return await self._connect_plain_tcp(port)

        strategies = tls_cfg.get("strategies", [])
        ciphers = tls_cfg.get("ciphers", [])
        delay = self.auth_config.get("reconnect_delay", 1.5)
        default_cert_name = tls_cfg.get("default_cert")

        for strategy in strategies:
            cert_sentinel = strategy.get("cert")
            if cert_sentinel == "__user_cert__" and not self.user_cert_path:
                continue

            cert_path = self._resolve_cert_path(cert_sentinel)
            verify_mode = getattr(
                ssl, strategy.get("verify_mode", "CERT_NONE"), ssl.CERT_NONE
            )

            for cipher in ciphers:
                try:
                    ssl_context = await async_create_samsung_ssl_context(
                        cert_path=cert_path, ciphers=cipher, verify_mode=verify_mode
                    )
                    async with asyncio.timeout(15.0):
                        self._reader, self._writer = await asyncio.open_connection(
                            self.ip_address, port, ssl=ssl_context
                        )
                        with suppress(TimeoutError):
                            async with asyncio.timeout(5.0):
                                await self._reader.read(self._buffer_size)

                        saved_cert = cert_path
                        if (
                            default_cert_name
                            and cert_path
                            and Path(cert_path).name == default_cert_name
                        ):
                            saved_cert = default_cert_name
                        elif cert_sentinel == "__user_cert__":
                            saved_cert = self.user_cert_path

                        return {"cert": saved_cert, "verify_mode": verify_mode}
                except Exception:  # noqa: BLE001
                    await self.async_close()
                    await asyncio.sleep(delay)

        raise CannotConnect("All YAML TLS strategies failed.")

    async def _initiate_stream_pairing(self, req_cfg: dict[str, Any]) -> dict[str, Any]:
        """Connect stream socket, send pairing payload, and validate Ready state."""
        successful_config = await self._connect_stream()
        payload_bytes = _encode_stream_payload(req_cfg.get("payload", ""))

        if self._writer is None or self._reader is None:
            raise TokenAcquisitionError("Connection stream not established.")

        self._writer.write(payload_bytes)
        await self._writer.drain()

        try:
            async with asyncio.timeout(15.0):
                data = await self._reader.read(self._buffer_size)
        except TimeoutError as exc:
            raise TokenAcquisitionError("Timeout waiting for 'Ready' response") from exc

        decoded = data.decode("utf-8", errors="ignore")
        self._initial_stream_data = decoded

        succ_cfg = req_cfg.get("success_template", {})
        if not _is_stream_pairing_accepted(
            decoded,
            succ_cfg.get("match", ""),
            succ_cfg.get("fallback_match", ""),
        ):
            raise TokenAcquisitionError("Device did not accept pairing.")

        return successful_config

    async def _wait_stream_token(self) -> str:
        """Read token from initial stream buffer or wait for device push."""
        if not self._reader:
            raise TokenAcquisitionError("Connection not established.")

        extract_regex = self._extract_regex
        if self._initial_stream_data:
            initial_token = _extract_token(self._initial_stream_data, extract_regex)
            if initial_token:
                return initial_token

        timeout = self.auth_config.get("wait_token", {}).get("timeout_seconds", 45)
        try:
            async with asyncio.timeout(timeout):
                data = await self._reader.read(self._buffer_size)
        except TimeoutError as exc:
            raise TokenAcquisitionError(
                "Token not received within timeout window."
            ) from exc

        if not data:
            raise TokenAcquisitionError("Connection closed by device.")

        decoded = data.decode("utf-8", errors="ignore")

        error_match = self.auth_config.get("error_template", {}).get("match")
        if error_match and error_match in decoded:
            raise AuthTurnedOffError(
                "Authentication failed: device is turned off or busy."
            )

        token = _extract_token(decoded, extract_regex)
        if token:
            return token

        raise TokenAcquisitionError("Regex failed to extract token from stream.")

    # ==========================================
    # PUBLIC ACQUISITION PHASES
    # ==========================================
    async def async_initiate_pairing(self) -> dict[str, Any]:
        """Phase 1: Initiate pairing by connecting or sending initial pairing request."""
        mode = self.auth_config.get("mode")
        req_cfg = self.auth_config.get("request_pairing", {})

        if mode == "listener":
            return await self._initiate_listener_pairing(req_cfg)
        if mode == "stream":
            return await self._initiate_stream_pairing(req_cfg)
        raise TokenAcquisitionError(f"Unsupported authentication mode: {mode}")

    async def async_wait_for_token(self) -> str:
        """Phase 2: Wait for user confirmation / incoming token notification."""
        mode = self.auth_config.get("mode")
        try:
            if mode == "listener":
                return await self._wait_listener_token()
            if mode == "stream":
                return await self._wait_stream_token()
            raise TokenAcquisitionError(f"Unsupported authentication mode: {mode}")
        finally:
            await self.async_close()

    async def async_close(self) -> None:
        """Deterministically close network connections and active server listeners."""
        await _safe_close_resource(self._server)
        self._server = None
        await _safe_close_resource(self._writer)
        self._writer = None
        self._reader = None
