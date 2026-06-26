# pylint: disable=import-outside-toplevel,duplicate-code,implicit-str-concat,line-too-long,too-many-branches,too-many-instance-attributes,too-many-locals,too-many-statements
"""
Pure Python library for Samsung AC (Port 8888).
Supports Raw Sockets and SSL auto-negotiation (Legacy vs Modern).
"""
# pylint: disable=import-outside-toplevel,duplicate-code,implicit-str-concat,line-too-long,too-many-branches,too-many-instance-attributes,too-many-locals,too-many-statements

import asyncio
import json
import logging
import re
import ssl
from typing import Any

from homeassistant.util.json import json_loads
from homeassistant.helpers.json import json_dumps

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

class ProtocolError(Exception):
    """Raised for protocol-level errors in the 8888 communication layer."""


# AuthError and CannotConnect are imported from exceptions.py — do not redefine here.


class Samsung8888Client:
    """Robust asynchronous client with multi-SSL support."""

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

        # Keep track of background tasks to ensure clean shutdown (Step 3.1)
        self._active_tasks: set[asyncio.Task[Any]] = set()

    def _track_task(self, coro: Any) -> asyncio.Task[Any]:
        """Helper to track background tasks for clean shutdown."""
        task = asyncio.create_task(coro)
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)
        return task

    async def _create_ssl_context(self) -> ssl.SSLContext:
        """Configure SSL, replicating the logic from connection_request.py."""
        ctx = await async_create_samsung_ssl_context(
            ciphers="ALL:@SECLEVEL=0",
            verify_mode=ssl.CERT_NONE,
        )

        # Optimise SSL for low-memory devices — disable session tickets and compression.
        try:
            applied_opts = []
            # Bucle transaccional: iteramos el contrato estático hermético.
            for opt_name, opt_val in SSL_OPTIMIZATIONS.items():
                if opt_val:
                    ctx.options |= opt_val
                    if ctx.options & opt_val:
                        applied_opts.append(opt_name)

            if applied_opts:
                _LOGGER.debug(  # pragma: no mutate
                    "%s SSL Optimizations enabled: %s",  # pragma: no mutate
                    self.log_prefix,    # pragma: no mutate
                    ", ".join(applied_opts),  # pragma: no mutate
                )  # pragma: no mutate
        except Exception:  # pylint: disable=import-outside-toplevel,broad-exception-caught
            pass  # Ignore if options not supported on this platform.

        if self.cert_path:
            try:
                # Modern Python 3.9+ idiom for offloading blocking calls to a thread
                await asyncio.to_thread(ctx.load_cert_chain, self.cert_path)
            except Exception as e:  # pylint: disable=import-outside-toplevel,broad-exception-caught
                _LOGGER.warning(  # pragma: no mutate
                    "%s Error loading certificate %s: %s",  # pragma: no mutate
                    self.log_prefix,  # pragma: no mutate
                    self.cert_path,  # pragma: no mutate
                    e,  # pragma: no mutate
                )  # pragma: no mutate

        max_ver = get_tls_version_name(getattr(ctx, "maximum_version", 0))  # pragma: no mutate
        min_ver = get_tls_version_name(getattr(ctx, "minimum_version", 0))  # pragma: no mutate
        _LOGGER.debug(  # pragma: no mutate
            "%s [protocol_8888] SSLContext configured. Min: %s, Max: %s",  # pragma: no mutate
            self.log_prefix,  # pragma: no mutate
            min_ver,  # pragma: no mutate
            max_ver,  # pragma: no mutate
        )  # pragma: no mutate
        
        return ctx

    async def connect(self) -> None:
        """Open the SSL connection to the device if not already connected."""
        if self._writer:
            return
        if not self._ssl_context:
            self._ssl_context = await self._create_ssl_context()
        try:
            # Modern Python 3.11+ timeout context manager
            async with asyncio.timeout(10.0):
                self._reader, self._writer = await asyncio.open_connection(
                    self.host, self.port, ssl=self._ssl_context
                )
            try:
                ssl_obj = self._writer.get_extra_info("ssl_object")
                negotiated_tls = ssl_obj.version() if ssl_obj else "Unknown"
                _LOGGER.debug(  # pragma: no mutate
                    "%s [Samsung8888Client] Connected successfully. Negotiated TLS: %s",  # pragma: no mutate
                    self.log_prefix,  # pragma: no mutate
                    negotiated_tls,  # pragma: no mutate
                )  # pragma: no mutate
            except Exception:  # pylint: disable=import-outside-toplevel,broad-exception-caught
                pass
        except TimeoutError as exc:
            raise CannotConnect(f"Connection timed out to {self.host}:{self.port}") from exc
        except Exception as exc:  # pylint: disable=import-outside-toplevel,broad-exception-caught
            raise CannotConnect(f"Connection error: {exc}") from exc

    async def close(self) -> None:
        """Close and clean up the socket writer and cancel pending tasks (Step 3.1)."""
        _LOGGER.debug(  # pragma: no mutate
            "%s [Samsung8888Client] Closing and cleaning up resources...", self.log_prefix  # pragma: no mutate
        )  # pragma: no mutate

        # 1. Cancel all tracked background tasks aggressively
        tasks_to_cancel = [t for t in self._active_tasks if not t.done()]  # pragma: no mutate
        for task in tasks_to_cancel:
            task.cancel()

        if tasks_to_cancel:
            _LOGGER.debug(  # pragma: no mutate
                "%s [Samsung8888Client] Waiting for %s tasks to cancel...",  # pragma: no mutate
                self.log_prefix,  # pragma: no mutate
                len(tasks_to_cancel),  # pragma: no mutate
            )  # pragma: no mutate
            # Wait for them to actually cancel, ignoring CancelledError
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            self._active_tasks.clear()

        # 2. Close the writer gracefully
        if self._writer:
            try:
                self._writer.close()
                try:
                    async with asyncio.timeout(2.0):
                        await self._writer.wait_closed()
                except TimeoutError:
                    _LOGGER.warning(  # pragma: no mutate
                        "%s [Samsung8888Client] Timeout waiting for socket close, "  # pragma: no mutate
                        "forcing abort (RST)",  # pragma: no mutate
                        self.log_prefix,  # pragma: no mutate
                    )  # pragma: no mutate
                    if self._writer.transport:
                        self._writer.transport.abort()
                except Exception as e:  # pylint: disable=import-outside-toplevel,broad-exception-caught
                    _LOGGER.warning(  # pragma: no mutate
                        "%s [Samsung8888Client] Error during wait_closed, " "forcing abort: %s",  # pragma: no mutate
                        self.log_prefix,  # pragma: no mutate
                        e,  # pragma: no mutate
                    )  # pragma: no mutate
                    if self._writer.transport:
                        self._writer.transport.abort()

            except Exception as e:  # pylint: disable=import-outside-toplevel,broad-exception-caught
                _LOGGER.debug(  # pragma: no mutate
                    "%s [Samsung8888Client] Error closing writer: %s",  # pragma: no mutate
                    self.log_prefix,  # pragma: no mutate
                    e,  # pragma: no mutate
                )  # pragma: no mutate
            finally:
                self._writer = None
                self._reader = None
        else:
            self._reader = None

    async def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[str | None, str | None]:
        """Send an HTTP request over the persistent SSL socket and return (body, error)."""
        async with self._lock:
            # Force cleanup if the reader has a pending waiter (concurrency guard).
            if (
                self._reader
                and hasattr(self._reader, "_waiter")
                and self._reader._waiter is not None  # pylint: disable=import-outside-toplevel,protected-access
            ):
                _LOGGER.warning(  # pragma: no mutate
                    "%s [Concurrency] Reader has pending waiter! Forced close.",  # pragma: no mutate
                    self.log_prefix,  # pragma: no mutate
                )  # pragma: no mutate
                await self.close()

            retry = True
            while retry:
                retry = False
                try:
                    await self.connect()

                    writer = self._writer
                    reader = self._reader
                    if writer is None or reader is None:
                        raise CannotConnect("No connection established")

                    # Build HTTP request manually to avoid header normalisation issues.
                    req = [
                        f"{method} {path} HTTP/1.1",
                        f"Host: {self.host}:{self.port}",
                        "Connection: keep-alive",
                    ]
                    if headers:
                        for k, v in headers.items():
                            req.append(f"{k}: {v}")

                    payload = json_dumps(body) if body else ""
                    req.append(
                        f"Content-Length: {len(payload)}" if payload else "Content-Length: 0"
                    )

                    request_str = "\r\n".join(req) + "\r\n\r\n" + (payload or "")
                    writer.write(request_str.encode("utf-8"))
                    try:
                        async with asyncio.timeout(5.0):
                            await writer.drain()
                        async with asyncio.timeout(10.0):
                            status_line = await reader.readline()
                    except TimeoutError as exc:
                        raise CannotConnect(
                            "Timeout sending request or reading status line"
                        ) from exc

                    if not status_line:
                        raise ConnectionResetError("Remote closure")

                    # --- REFACTOR: Parseo blindado del Status Line ---
                    decoded_status = status_line.decode("utf-8", "ignore").strip()
                    status_match = STATUS_PATTERN.match(decoded_status)
                    if not status_match:
                        raise CannotConnect(f"Invalid status format: {decoded_status!r}")
                    
                    status_code = int(status_match.group("code"))
                    # -------------------------------------------------

                    # ── Read response headers ────────────────────────────
                    headers_received = []
                    content_length = 0
                    content_type = ""
                    while True:
                        try:
                            async with asyncio.timeout(5.0):
                                line = await reader.readline()
                        except TimeoutError as exc:
                            raise CannotConnect("Timeout reading headers") from exc

                        if not line or line == b"\r\n":
                            break
                        
                        line_str = line.decode("utf-8", "ignore").strip()
                        headers_received.append(line_str)
                        
                        # --- REFACTOR: Parseo blindado de cabeceras ---
                        match = HEADER_PATTERN.match(line_str)
                        if match:
                            key = match.group("key").lower()
                            val = match.group("value")
                            
                            if key == "content-length":
                                try:
                                    content_length = int(val)
                                except ValueError:
                                    pass  # Ignoramos si la API manda basura como Content-Length: abc
                            elif key == "content-type":
                                content_type = val
                        # -----------------------------------------------

                    # ── Read response body ────────────────────────────────
                    resp_body = ""
                    if content_length > 0:
                        try:
                            async with asyncio.timeout(10.0):
                                chunk = await reader.readexactly(content_length)
                            resp_body = chunk.decode("utf-8", "ignore")
                        except TimeoutError as exc:
                            raise CannotConnect("Timeout reading response body") from exc
                        except Exception:  # pylint: disable=import-outside-toplevel,broad-exception-caught
                            resp_body = ""
                    elif content_length == 0 and "content-length" in [
                        h.lower().split(":")[0] for h in headers_received
                    ]:
                        resp_body = ""  # Explicitly 0 — do not read.
                    else:
                        # Fallback: read until closed or timeout; extract first valid JSON object.
                        buffer = b""
                        decoder = json.JSONDecoder()

                        try:
                            # Use a single timeout context for the entire loop
                            async with asyncio.timeout(5.0):
                                while True:
                                    chunk = await reader.read(8192)
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
                            _LOGGER.debug(  # pragma: no mutate
                                "%s [RAW] Socket chunk read timed out (5.0s limit reached).",  # pragma: no mutate
                                self.log_prefix,  # pragma: no mutate
                            )  # pragma: no mutate

                        if not resp_body:
                            resp_body = buffer.decode("utf-8", "ignore")

                    _LOGGER.debug(  # pragma: no mutate
                        "%s Headers received: %s",  # pragma: no mutate
                        self.log_prefix,  # pragma: no mutate
                        headers_received,  # pragma: no mutate
                    )  # pragma: no mutate
                    _LOGGER.debug(  # pragma: no mutate
                        "%s Content-Length: %d, Content-Type: %s",  # pragma: no mutate
                        self.log_prefix,  # pragma: no mutate
                        content_length,  # pragma: no mutate
                        content_type,  # pragma: no mutate
                    )  # pragma: no mutate

                    # Compact and mask the body for logging.
                    log_body = resp_body.replace("\r", "").replace("\n", "")
                    try:
                        json_obj = json_loads(resp_body)
                        masked_obj = mask_sensitive_data(json_obj)
                        log_body = json_dumps(masked_obj)
                    except Exception:  # pylint: disable=import-outside-toplevel,broad-exception-caught
                        pass  # Keep cleaned string if not valid JSON.

                    _LOGGER.debug(  # pragma: no mutate
                        "%s Response body received: '%s'",  # pragma: no mutate
                        self.log_prefix,  # pragma: no mutate
                        log_body,  # pragma: no mutate
                    )  # pragma: no mutate

                    if status_code == 401:
                        raise AuthError("401 Unauthorized")
                    if status_code not in (200, 204):
                        return None, f"HTTP {status_code}: {resp_body}"

                    return resp_body, None

                except (
                    ConnectionResetError,
                    BrokenPipeError,
                    asyncio.IncompleteReadError,
                ) as exc:
                    await self.close()
                    if not retry:
                        retry = True
                        continue
                    raise CannotConnect("Unstable connection") from exc
                except AuthError:
                    await self.close()
                    raise
                except asyncio.CancelledError:
                    _LOGGER.debug(  # pragma: no mutate
                        "%s [RAW] Request was cancelled by coordinator timeout. Closing socket.", # pragma: no mutate
                        self.log_prefix,  # pragma: no mutate
                    )  # pragma: no mutate
                    await self.close()
                    raise
                except Exception as exc:  # pylint: disable=import-outside-toplevel,broad-exception-caught
                    await self.close()
                    if "ssl" in str(exc).lower():
                        raise CannotConnect(f"Error SSL: {exc}") from exc
                    raise CannotConnect(f"Unexpected error: {exc}") from exc

        return None, "No response"
