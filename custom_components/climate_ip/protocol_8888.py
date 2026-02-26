# climate_ip/protocol_8888.py
"""
Pure Python library for Samsung AC (Port 8888).
Supports Raw Sockets and SSL auto-negotiation (Legacy vs Modern).
"""
import asyncio
import json
import logging
import ssl
from functools import partial
from typing import Optional, Tuple, Dict

from .exceptions import AuthError
from .helpers import mask_sensitive_data

_LOGGER = logging.getLogger(__name__)

class ProtocolError(Exception):
    pass

class ConnectionError(ProtocolError):
    pass

class AuthError(ProtocolError):
    pass

class Samsung8888Client:
    """Robust asynchronous client with multi-SSL support."""

    def __init__(
        self,
        host: str,
        port: int = 8888,
        cert_path: Optional[str] = None,
        log_prefix: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.cert_path = cert_path
        self.log_prefix = log_prefix or f"[{host}]"
        self._ssl_context: Optional[ssl.SSLContext] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()

    async def _create_ssl_context(self) -> ssl.SSLContext:
        """Configure SSL, replicating the logic from connection_request.py."""
        from .helpers import async_create_samsung_ssl_context
        ctx = await async_create_samsung_ssl_context(
            ciphers="ALL:@SECLEVEL=0",
            verify_mode=ssl.CERT_NONE
        )
        
        # --- START OF FIX: Optimize SSL for low-memory devices ---
        # Disable session tickets and compression to reduce handshake overhead
        try:
            applied_opts = []
            op_no_ticket = getattr(ssl, "OP_NO_TICKET", 0)
            if op_no_ticket:
                ctx.options |= op_no_ticket
                if ctx.options & op_no_ticket:
                    applied_opts.append("OP_NO_TICKET")

            op_no_compression = getattr(ssl, "OP_NO_COMPRESSION", 0)
            if op_no_compression:
                ctx.options |= op_no_compression
                if ctx.options & op_no_compression:
                    applied_opts.append("OP_NO_COMPRESSION")

            if applied_opts:
                _LOGGER.debug("%s SSL Optimizations enabled: %s", self.log_prefix, ", ".join(applied_opts))
        except Exception:
            pass # Ignore if options not supported
        # --- END OF FIX ---

        if self.cert_path:
            try:
                # Use run_in_executor to avoid blocking the event loop
                loop = asyncio.get_running_loop()
                load_chain_func = partial(ctx.load_cert_chain, self.cert_path)
                await loop.run_in_executor(None, load_chain_func)
            except Exception as e:
                _LOGGER.warning(
                    "%s Error loading certificate %s: %s",
                    self.log_prefix,
                    self.cert_path,
                    e,
                )
        
        # Log the configured TLS limits using friendly names
        from .helpers import get_tls_version_name
        max_ver = get_tls_version_name(getattr(ctx, 'maximum_version', 'Unknown'))
        min_ver = get_tls_version_name(getattr(ctx, 'minimum_version', 'Unknown'))
        _LOGGER.debug("%s [protocol_8888] SSLContext configured. Min: %s, Max: %s", self.log_prefix, min_ver, max_ver)

        return ctx

    async def connect(self):
        if self._writer:
            return
        if not self._ssl_context:
            self._ssl_context = await self._create_ssl_context()
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port, ssl=self._ssl_context),
                timeout=10.0
            )
            # Attempt to log the negotiated TLS version
            try:
                ssl_obj = self._writer.get_extra_info('ssl_object')
                negotiated_tls = ssl_obj.version() if ssl_obj else "Unknown"
                _LOGGER.debug("%s [Samsung8888Client] Connected successfully. Negotiated TLS: %s", self.log_prefix, negotiated_tls)
            except Exception:
                pass
        except asyncio.TimeoutError:
            raise ConnectionError(f"Connection timed out to {self.host}:{self.port}")
        except Exception as e:
            raise ConnectionError(f"Connection error: {e}")

    async def close(self):
        if self._writer:
            try:
                _LOGGER.debug("%s [Samsung8888Client] Closing socket writer...", self.log_prefix)
                self._writer.close()
                
                # Wait for the close to complete, but with a timeout
                try:
                    await asyncio.wait_for(self._writer.wait_closed(), timeout=2.0)
                except asyncio.TimeoutError:
                    _LOGGER.warning("%s [Samsung8888Client] Timeout waiting for socket close, forcing abort (RST)", self.log_prefix)
                    # Forcefully abort the transport to ensure the socket is closed at the OS level
                    if self._writer.transport:
                        self._writer.transport.abort()
                except Exception as e:
                    _LOGGER.warning("%s [Samsung8888Client] Error during wait_closed, forcing abort: %s", self.log_prefix, e)
                    if self._writer.transport:
                        self._writer.transport.abort()

            except Exception as e:
                _LOGGER.debug("%s [Samsung8888Client] Error closing writer: %s", self.log_prefix, e)
            finally:
                # Ensure references are cleared to prevent reuse of dead objects
                self._writer = None
                self._reader = None
        else:
            # Clear reader just in case writer was None but reader wasn't
            self._reader = None

    async def request(self, method: str, path: str, body: Optional[Dict] = None, headers: Optional[Dict] = None) -> Tuple[Optional[str], Optional[str]]:
        # Debug Logging for Lock Contention
        # _LOGGER.debug("%s [Lock] Requesting lock for: %s %s", self.log_prefix, method, path)
        async with self._lock:
            # _LOGGER.debug("%s [Lock] Acquired lock for: %s %s", self.log_prefix, method, path)
            try:
                # Force cleanup if the reader is potentially corrupted (internal check)
                if self._reader and hasattr(self._reader, "_waiter") and self._reader._waiter is not None:
                     _LOGGER.warning("%s [Concurrency] Reader has pending waiter! Forced close.", self.log_prefix)
                     await self.close()

                retry = True
                while retry:
                    retry = False
                    try:
                        await self.connect()
                        
                        # Use local non-Optional references to satisfy type checkers
                        writer = self._writer
                        reader = self._reader
                        if writer is None or reader is None:
                            raise ConnectionError("No connection established")
                        
                        # Manual HTTP construction to avoid header errors
                        req = [f"{method} {path} HTTP/1.1", f"Host: {self.host}:{self.port}", "Connection: keep-alive"]
                        if headers:
                            for k, v in headers.items():
                                req.append(f"{k}: {v}")
                        
                        payload = json.dumps(body) if body else ""
                        if payload:
                            req.append(f"Content-Length: {len(payload)}")
                        else:
                            req.append("Content-Length: 0")
                        
                        request_str = "\r\n".join(req) + "\r\n\r\n" + (payload if payload else "")
                        writer.write(request_str.encode('utf-8'))
                        try:
                            await asyncio.wait_for(writer.drain(), timeout=5.0)
                            
                            status_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
                        except asyncio.TimeoutError:
                            raise ConnectionError("Timeout sending request or reading status line")
                        if not status_line:
                            raise ConnectionResetError("Remote closure")
                        
                        try:
                            status_code = int(status_line.decode('utf-8', 'ignore').strip().split(' ')[1])
                        except Exception:
                            raise ConnectionError(f"Invalid status: {status_line!r}")
                        
                        # Read headers
                        headers_received = []
                        content_length = 0
                        content_type = ""
                        while True:
                            try:
                                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                            except asyncio.TimeoutError:
                                raise ConnectionError("Timeout reading headers")
                            
                            if not line or line == b'\r\n':
                                break
                            line_str = line.decode('utf-8', 'ignore').strip()
                            headers_received.append(line_str)
                            line_lower = line_str.lower()
                            if 'content-length' in line_lower:
                                try:
                                    content_length = int(line_lower.split(':', 1)[1].strip())
                                except Exception:
                                    pass
                            if 'content-type' in line_lower:
                                try:
                                    content_type = line_lower.split(':', 1)[1].strip()
                                except Exception:
                                    pass
    
                        # Read body
                        resp_body = ""
                        if content_length > 0:
                            try:
                                chunk = await asyncio.wait_for(reader.readexactly(content_length), timeout=10.0)
                                resp_body = chunk.decode('utf-8', 'ignore')
                            except asyncio.TimeoutError:
                                raise ConnectionError("Timeout reading response body")
                            except Exception:
                                resp_body = ""
                        elif content_length == 0 and "content-length" in [h.lower().split(':')[0] for h in headers_received]:
                             # Explicitly 0, do not read
                             resp_body = ""
                        else:
                            # Fallback: read until closed or timeout and try to assemble complete JSON
                            buffer = b""
                            end_time = asyncio.get_running_loop().time() + 5.0
                            
                            while True:
                                timeout_left = end_time - asyncio.get_running_loop().time()
                                if timeout_left <= 0:
                                    _LOGGER.debug("%s [RAW] Read loop reached 5.0s absolute timeout.", self.log_prefix)
                                    break
                                
                                try:
                                    chunk = await asyncio.wait_for(reader.read(8192), timeout=timeout_left)
                                    if not chunk:
                                        break # Connection closed
                                    
                                    buffer += chunk
                                    resp_body_candidate = buffer.decode('utf-8', 'ignore')
                                    
                                    if not resp_body_candidate.strip():
                                        continue
                                        
                                    try:
                                        json.loads(resp_body_candidate)
                                        resp_body = resp_body_candidate
                                        break # Valid JSON found
                                    except json.JSONDecodeError:
                                        continue # Not full JSON yet, keep reading
                                        
                                except asyncio.TimeoutError:
                                    _LOGGER.debug("%s [RAW] Socket chunk read timed out.", self.log_prefix)
                                    break
                            
                            if not resp_body:
                                resp_body = buffer.decode('utf-8', 'ignore')
    
                        _LOGGER.debug("%s Headers received: %s", self.log_prefix, headers_received)
                        _LOGGER.debug("%s Content-Length: %d, Content-Type: %s", self.log_prefix, content_length, content_type)
                        # Compact JSON for logging
                        log_body = resp_body.replace("\r", "").replace("\n", "")
                        try:
                            # Try to compact JSON if possible
                            json_obj = json.loads(resp_body)
                            # Mask sensitive data before logging
                            masked_obj = mask_sensitive_data(json_obj)
                            log_body = json.dumps(masked_obj, separators=(',', ':'))
                        except Exception:
                            pass # Keep original cleaned string if not valid JSON
                        
                        _LOGGER.debug("%s Response body received: '%s'", self.log_prefix, log_body)
    
                        if status_code == 401:
                            raise AuthError("401 Unauthorized")
                        if status_code not in (200, 204):
                            return None, f"HTTP {status_code}: {resp_body}"
    
                        return resp_body, None
    
                    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
                        await self.close()
                        if not retry:
                            retry = True
                            continue
                        else:
                            raise ConnectionError("Unstable connection")
                    except AuthError:
                        await self.close()
                        raise
                    except asyncio.CancelledError:
                        _LOGGER.debug("%s [RAW] Request was cancelled by coordinator timeout. Closing socket.", self.log_prefix)
                        await self.close()
                        raise
                    except Exception as e:
                        await self.close()
                        if "ssl" in str(e).lower():
                            raise ConnectionError(f"Error SSL: {e}")
                        raise ConnectionError(f"Unexpected error: {e}")
            finally:
                pass # Just ensuring cleanup if needed
                
            # If we exit the retry loop without returning, return a tuple explicitly
            return None, "No response"
