# pylint: disable=duplicate-code,implicit-str-concat,line-too-long,too-many-branches,too-many-instance-attributes,too-many-locals,too-many-statements
"""
Pure Python library for Samsung AC (Port 8888).
Supports Raw Sockets and SSL auto-negotiation (Legacy vs Modern).
"""

import asyncio
import json
import logging
import re
import ssl
from typing import Any, Final

from homeassistant.helpers.json import json_dumps
from homeassistant.util.json import json_loads

from .const import GLOBAL_HTTP_TIMEOUT
from .exceptions import AuthError, CannotConnect
from .helpers import (
    async_create_samsung_ssl_context,
    get_tls_version_name,
    mask_sensitive_data,
)

_LOGGER = logging.getLogger(__name__)

SSL_OPTIMIZATIONS: Final = {
    "OP_NO_TICKET": getattr(ssl, "OP_NO_TICKET", 0),
    "OP_NO_COMPRESSION": getattr(ssl, "OP_NO_COMPRESSION", 0),
}

HEADER_PATTERN = re.compile(r"^(?P<key>[^:]+):\s*(?P<value>.+)$", re.IGNORECASE)
STATUS_PATTERN = re.compile(r"^HTTP/\d\.\d\s+(?P<code>\d+)", re.IGNORECASE)

READ_CHUNK_SIZE: Final = 8192
FALLBACK_READ_TIMEOUT: Final = 5.0
SOCKET_CLOSE_TIMEOUT: Final = 2.0


# AuthError and CannotConnect are imported from exceptions.py — do not redefine here.


class Samsung8888Client:
    """Low-level asynchronous HTTP/1.1 client for Samsung AC devices on port 8888.

    WHY NOT aiohttp?
    ~~~~~~~~~~~~~~~~
    Samsung HVAC devices exposed on port 8888 implement a **non-standard HTTP/1.1
    dialect** that is fundamentally incompatible with ``aiohttp.ClientSession``:

    1. **Header normalisation rejection**: aiohttp normalises header names to
       lowercase (RFC 7230 §3.2). Samsung firmware on these generations rejects
       requests whose headers do not preserve the original casing (e.g. it
       demands ``Content-Length``, not ``content-length``).
    2. **Non-standard streaming bodies**: The device frequently omits
       ``Transfer-Encoding: chunked`` and ``Content-Length`` simultaneously,
       streaming raw JSON over a keep-alive socket with no framing. aiohttp's
       ``response.read()`` hangs indefinitely waiting for EOF or a content
       boundary that never arrives.
    3. **Legacy TLS negotiation**: Some device firmware requires TLS 1.0 / 1.1
       with ``ALL:@SECLEVEL=0`` ciphers and ``CERT_NONE``. aiohttp delegates
       to ``ssl.create_default_context()`` which enforces minimum TLS 1.2,
       making connection impossible without monkey-patching the connector.
    4. **Single-socket keep-alive mandate**: The device accepts exactly one
       concurrent TCP connection and expects HTTP keep-alive for the session
       lifetime. aiohttp's connection pooling creates and tears down sockets
       per request, triggering device-side RSTs.

    For these reasons we implement a manual HTTP engine over raw
    ``asyncio.open_connection`` with precise control over header serialisation,
    body framing, and SSL context configuration.
    """

    def __init__(
        self,
        host: str,
        port: int = 8888,
        cert_path: str | None = None,
        log_prefix: str | None = None,
    ) -> None:
        """Initialise the client."""
        self.host = host
        self.port = port
        self.cert_path = cert_path
        self.log_prefix = log_prefix or f"[{host}]"
        self._ssl_context: ssl.SSLContext | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def _create_ssl_context(self) -> ssl.SSLContext:
        """Configure SSL, replicating the logic from connection_request.py."""
        ctx = await async_create_samsung_ssl_context(
            ciphers="ALL:@SECLEVEL=0",
            verify_mode=ssl.CERT_NONE,
        )

        # Optimise SSL for low-memory devices — disable session tickets and compression.
        try:
            applied_opts = []
            # Transactional loop: iterate through static contract definition.
            for opt_name, opt_val in SSL_OPTIMIZATIONS.items():
                if opt_val:
                    ctx.options |= opt_val
                    if ctx.options & opt_val:
                        applied_opts.append(opt_name)

            if applied_opts:
                _LOGGER.debug(
                    "%s SSL Optimizations enabled: %s",
                    self.log_prefix,
                    ", ".join(applied_opts),
                )
        except Exception:  # pylint: disable=broad-exception-caught
            pass  # Ignore if options not supported on this platform.

        if self.cert_path:
            try:
                # Modern Python 3.9+ idiom for offloading blocking calls to a thread
                await asyncio.to_thread(ctx.load_cert_chain, self.cert_path)
            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.warning(
                    "%s Error loading certificate %s: %s",
                    self.log_prefix,
                    self.cert_path,
                    e,
                )

        max_ver = get_tls_version_name(getattr(ctx, "maximum_version", 0))
        min_ver = get_tls_version_name(getattr(ctx, "minimum_version", 0))
        _LOGGER.debug(
            "%s [protocol_8888] SSLContext configured. Min: %s, Max: %s",
            self.log_prefix,
            min_ver,
            max_ver,
        )

        return ctx

    async def connect(self) -> None:
        """Open the SSL connection to the device if not already connected."""
        if self._writer:
            return
        if not self._ssl_context:
            self._ssl_context = await self._create_ssl_context()
        try:
            # Modern Python 3.11+ timeout context manager
            async with asyncio.timeout(GLOBAL_HTTP_TIMEOUT):
                (
                    self._reader,
                    self._writer,
                ) = await asyncio.open_connection(
                    self.host,
                    self.port,
                    ssl=self._ssl_context,
                )
            try:
                ssl_obj = self._writer.get_extra_info("ssl_object")
                negotiated_tls = ssl_obj.version() if ssl_obj else "Unknown"
                _LOGGER.debug(
                    "%s [Samsung8888Client] Connected successfully. Negotiated TLS: %s",
                    self.log_prefix,
                    negotiated_tls,
                )
            except Exception:  # pylint: disable=broad-exception-caught
                pass
        except TimeoutError as exc:
            raise CannotConnect(
                f"Connection timed out to {self.host}:{self.port}"
            ) from exc
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise CannotConnect(f"Connection error: {exc}") from exc

    async def close(self) -> None:
        """Close and clean up the socket writer and reader."""
        _LOGGER.debug(
            "%s [Samsung8888Client] Closing and cleaning up resources...",
            self.log_prefix,
        )

        if self._writer:
            try:
                self._writer.close()
                try:
                    async with asyncio.timeout(SOCKET_CLOSE_TIMEOUT):
                        await self._writer.wait_closed()
                except TimeoutError:
                    _LOGGER.warning(
                        "%s [Samsung8888Client] Timeout waiting for socket close, "
                        "forcing abort (RST)",
                        self.log_prefix,
                    )
                    if self._writer.transport:
                        self._writer.transport.abort()
                except Exception as e:  # pylint: disable=broad-exception-caught
                    _LOGGER.warning(
                        "%s [Samsung8888Client] Error during wait_closed, "
                        "forcing abort: %s",
                        self.log_prefix,
                        e,
                    )
                    if self._writer.transport:
                        self._writer.transport.abort()

            except Exception as e:  # pylint: disable=broad-exception-caught
                _LOGGER.debug(
                    "%s [Samsung8888Client] Error closing writer: %s",
                    self.log_prefix,
                    e,
                )
            finally:
                self._writer = None
                self._reader = None
        else:
            self._reader = None

    def _build_request_bytes(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> bytes:
        """Build HTTP request bytes preserving exact header casing and UTF-8 body length."""
        req = [
            f"{method} {path} HTTP/1.1",
            f"Host: {self.host}:{self.port}",
            "Connection: keep-alive",
        ]
        if headers:
            for k, v in headers.items():
                req.append(f"{k}: {v}")

        payload_bytes = json_dumps(body).encode("utf-8") if body is not None else b""
        req.append(f"Content-Length: {len(payload_bytes)}")

        request_str = "\r\n".join(req) + "\r\n\r\n"
        return request_str.encode("utf-8") + payload_bytes

    async def _read_response_headers(
        self, reader: asyncio.StreamReader
    ) -> tuple[int, int, bool, str, list[str]]:
        """Read status line and HTTP headers from reader.

        Returns tuple: (status_code, content_length, has_content_length_header, content_type, headers_received).
        """
        try:
            async with asyncio.timeout(GLOBAL_HTTP_TIMEOUT):
                status_line = await reader.readline()
        except TimeoutError as exc:
            await self.close()
            raise CannotConnect(
                "Timeout sending request or reading status line"
            ) from exc

        if not status_line:
            raise ConnectionResetError("Remote closure")

        # --- Hardened HTTP Status Line parser ---
        decoded_status = status_line.decode("utf-8", "ignore").strip()
        status_match = STATUS_PATTERN.match(decoded_status)
        if not status_match:
            raise CannotConnect(f"Invalid status format: {decoded_status!r}")

        status_code = int(status_match.group("code"))

        headers_received = []
        has_content_length_header = False
        content_length = 0
        content_type = ""
        while True:
            try:
                async with asyncio.timeout(GLOBAL_HTTP_TIMEOUT // 2):
                    line = await reader.readline()
            except TimeoutError as exc:
                await self.close()
                raise CannotConnect("Timeout reading headers") from exc

            if not line or line == b"\r\n":
                break

            line_str = line.decode("utf-8", "ignore").strip()
            headers_received.append(line_str)

            # --- Hardened HTTP Header parser ---
            match = HEADER_PATTERN.match(line_str)
            if match:
                key = match.group("key").lower()
                val = match.group("value")

                if key == "content-length":
                    has_content_length_header = True
                    try:
                        content_length = int(val)
                    except ValueError:
                        pass  # Ignore invalid non-numeric Content-Length header values from device
                elif key == "content-type":
                    content_type = val

        return (
            status_code,
            content_length,
            has_content_length_header,
            content_type,
            headers_received,
        )

    async def _read_response_body(
        self,
        reader: asyncio.StreamReader,
        content_length: int,
        has_cl_header: bool,
    ) -> str:
        """Read response body from reader according to Content-Length or fallback streaming parser."""
        resp_body = ""
        if content_length > 0:
            try:
                async with asyncio.timeout(GLOBAL_HTTP_TIMEOUT):
                    chunk = await reader.readexactly(content_length)
                resp_body = chunk.decode("utf-8", "ignore")
            except TimeoutError as exc:
                await self.close()
                raise CannotConnect("Timeout reading response body") from exc
            except Exception:  # pylint: disable=broad-exception-caught
                resp_body = ""
        elif content_length == 0 and has_cl_header:
            resp_body = ""  # Explicitly 0 — do not read.
        else:
            # Fallback: read until closed or timeout; extract first valid JSON object.
            # Architectural Note: We intentionally use Python stdlib json.JSONDecoder().raw_decode
            # here instead of homeassistant.util.json (orjson) because orjson does not support
            # incremental stream parsing or raw_decode on un-framed raw TCP sockets.
            buffer = b""
            decoder = json.JSONDecoder()

            try:
                # Use a single timeout context for the entire loop
                async with asyncio.timeout(FALLBACK_READ_TIMEOUT):
                    while True:
                        chunk = await reader.read(READ_CHUNK_SIZE)
                        if not chunk:
                            break  # Connection closed.

                        buffer += chunk
                        resp_body_candidate = buffer.decode("utf-8", "ignore").lstrip()

                        if not resp_body_candidate:
                            continue

                        try:
                            # raw_decode cleanly extracts the first valid JSON object from a stream
                            _, idx = decoder.raw_decode(resp_body_candidate)
                            resp_body = resp_body_candidate[:idx]
                            break  # Valid JSON found and extracted.
                        except json.JSONDecodeError:
                            continue  # Not full JSON yet — keep reading.

            except TimeoutError:
                _LOGGER.debug(
                    "%s [RAW] Socket chunk read timed out (5.0s limit reached).",
                    self.log_prefix,
                )

            if not resp_body:
                resp_body = buffer.decode("utf-8", "ignore")

        return resp_body

    def _log_masked_response(self, resp_body: str) -> None:
        """Compact, mask sensitive data, and log the response body."""
        log_body = resp_body.replace("\r", "").replace("\n", "")
        try:
            json_obj = json_loads(resp_body)
            masked_obj = mask_sensitive_data(json_obj)
            log_body = json_dumps(masked_obj)
        except Exception:  # pylint: disable=broad-exception-caught
            pass  # Keep cleaned string if not valid JSON.

        _LOGGER.debug(
            "%s Response body received: '%s'",
            self.log_prefix,
            log_body,
        )

    async def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[str | None, str | None]:
        """Send an HTTP request over the persistent SSL socket and return (body, error)."""
        async with self._lock:
            retried = False
            while True:
                try:
                    await self.connect()

                    writer = self._writer
                    reader = self._reader
                    if writer is None or reader is None:
                        raise CannotConnect("No connection established")

                    request_bytes = self._build_request_bytes(
                        method, path, headers=headers, body=body
                    )
                    writer.write(request_bytes)
                    try:
                        async with asyncio.timeout(GLOBAL_HTTP_TIMEOUT // 2):
                            await writer.drain()
                    except TimeoutError as exc:
                        await self.close()
                        raise CannotConnect(
                            "Timeout sending request or reading status line"
                        ) from exc

                    (
                        status_code,
                        content_length,
                        has_content_length_header,
                        content_type,
                        headers_received,
                    ) = await self._read_response_headers(reader)

                    resp_body = await self._read_response_body(
                        reader, content_length, has_content_length_header
                    )

                    _LOGGER.debug(
                        "%s Headers received: %s",
                        self.log_prefix,
                        headers_received,
                    )
                    _LOGGER.debug(
                        "%s Content-Length: %d, Content-Type: %s",
                        self.log_prefix,
                        content_length,
                        content_type,
                    )

                    self._log_masked_response(resp_body)

                    if status_code == 401:
                        raise AuthError("401 Unauthorized")
                    if status_code not in (200, 204):
                        return None, f"HTTP {status_code}: {resp_body}"

                    return resp_body, None

                except CannotConnect:
                    # Already closed by the inner handler; propagate directly.
                    raise
                except (
                    ConnectionResetError,
                    BrokenPipeError,
                    asyncio.IncompleteReadError,
                ) as exc:
                    await self.close()
                    if not retried:
                        retried = True
                        continue
                    raise CannotConnect("Unstable connection") from exc
                except AuthError:
                    await self.close()
                    raise
                except asyncio.CancelledError:
                    _LOGGER.debug(
                        "%s [RAW] Request was cancelled by coordinator timeout. Closing socket.",
                        self.log_prefix,
                    )
                    await self.close()
                    raise
                except ssl.SSLError as exc:
                    await self.close()
                    raise CannotConnect(f"Error SSL: {exc}") from exc
                except Exception:
                    # An unexpected programming bug occurred (TypeError, etc.)
                    await self.close()
                    raise  # Fail-fast: do not mask as a CannotConnect
