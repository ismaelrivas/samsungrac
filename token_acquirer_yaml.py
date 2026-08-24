import asyncio
import logging
import re
import ssl
from pathlib import Path
from typing import Any

from .exceptions import AuthTurnedOffError, CannotConnect, TokenAcquisitionError
from .helpers import async_create_samsung_ssl_context

_LOGGER = logging.getLogger(__name__)


class GenericYamlTokenAcquirer:
    """100% Data-Driven token acquirer engine based on YAML configuration."""

    def __init__(
        self,
        hass: Any,
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

        # Stream State
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

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
    # LISTENER MODE LOGIC (Port 8888)
    # ==========================================
    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle incoming client connection on the local listener server."""
        try:
            buffer_size = self.auth_config.get("buffer_size", 4096)
            data = await asyncio.wait_for(reader.read(buffer_size), timeout=10.0)
            decoded_data = data.decode("utf-8", errors="ignore")

            extract_regex = self.auth_config.get("extract_template", {}).get("regex")
            token = None

            if extract_regex:
                match = re.search(extract_regex, decoded_data)
                if match:
                    token = match.group(1).strip('"')

            listener_cfg = self.auth_config.get("listener", {})
            if token:
                self._received_token = token
                self._token_received_event.set()
                response = listener_cfg.get(
                    "success_response", "HTTP/1.1 200 OK\r\n\r\n"
                )
            else:
                response = listener_cfg.get(
                    "error_response", "HTTP/1.1 400 Bad Request\r\n\r\n"
                )

            clean_resp = response.replace("\r\n", "\n").replace("\n", "\r\n")
            writer.write(clean_resp.encode("utf-8"))
            await writer.drain()

        except Exception as e:
            _LOGGER.error("Error in listener: %s", e)  # pragma: no mutate
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (OSError, ssl.SSLError, Exception):
                pass

    async def _start_listener_server(self) -> None:
        """Start the local TLS listener server."""
        listener_cfg = self.auth_config.get("listener", {})
        port = listener_cfg.get("port", 8889)
        tls_cfg = self.auth_config.get("tls_config", {})

        cert_path = self._resolve_cert_path(tls_cfg.get("default_cert"))
        ciphers = tls_cfg.get("ciphers", ["HIGH:!aNULL:!MD5:@SECLEVEL=0"])[0]

        ssl_context = await async_create_samsung_ssl_context(
            cert_path=cert_path, ciphers=ciphers, is_server=True
        )

        bind_ip = getattr(self.hass.config.api, "local_ip", None) or "0.0.0.0"
        self._server = await asyncio.start_server(
            self._handle_client, bind_ip, port, ssl=ssl_context
        )

    # ==========================================
    # STREAM MODE LOGIC (Port 2878)
    # ==========================================
    async def _connect_stream(self) -> dict[str, Any]:
        """Establish a TLS stream socket connection across configured strategies."""
        tls_cfg = self.auth_config.get("tls_config", {})
        strategies = tls_cfg.get("strategies", [])
        ciphers = tls_cfg.get("ciphers", [])
        delay = self.auth_config.get("reconnect_delay", 1.5)

        for strategy in strategies:
            cert_path = self._resolve_cert_path(strategy.get("cert"))
            # Skip strategies requesting user_cert when no certificate was provided
            if strategy.get("cert") == "__user_cert__" and not self.user_cert_path:
                continue

            verify_mode_str = strategy.get("verify_mode", "CERT_NONE")
            verify_mode = getattr(ssl, verify_mode_str, ssl.CERT_NONE)

            for cipher in ciphers:
                try:
                    ssl_context = await async_create_samsung_ssl_context(
                        cert_path=cert_path, ciphers=cipher, verify_mode=verify_mode
                    )
                    async with asyncio.timeout(15.0):
                        self._reader, self._writer = await asyncio.open_connection(
                            self.ip_address,
                            self.auth_config["request_pairing"]["port"],
                            ssl=ssl_context,
                        )

                        # Read initial handshake
                        try:
                            async with asyncio.timeout(5.0):
                                await self._reader.read(
                                    self.auth_config.get("buffer_size", 4096)
                                )
                        except TimeoutError:
                            pass

                        saved_cert = cert_path
                        default_cert_name = tls_cfg.get("default_cert")
                        if (
                            default_cert_name
                            and cert_path
                            and Path(cert_path).name == default_cert_name
                        ):
                            saved_cert = default_cert_name
                        elif strategy.get("cert") == "__user_cert__":
                            saved_cert = self.user_cert_path

                        return {"cert": saved_cert, "verify_mode": verify_mode}

                except Exception:
                    await self.async_close()
                    await asyncio.sleep(delay)

        raise CannotConnect("All YAML TLS strategies failed.")

    # ==========================================
    # PUBLIC ACQUISITION PHASES
    # ==========================================
    async def async_initiate_pairing(self) -> dict[str, Any]:
        """Phase 1: Initiate pairing by connecting or sending initial pairing request."""
        mode = self.auth_config.get("mode")
        req_cfg = self.auth_config.get("request_pairing", {})

        if mode == "listener":
            await self._start_listener_server()

            # Dynamic construction of raw_tcp request from YAML
            tls_cfg = self.auth_config.get("tls_config", {})
            cert_path = self._resolve_cert_path(tls_cfg.get("default_cert"))
            ciphers = tls_cfg.get("ciphers", ["HIGH"])[0]
            verify_mode = getattr(ssl, tls_cfg.get("verify_mode", "CERT_NONE"))

            ssl_ctx = await async_create_samsung_ssl_context(
                cert_path=cert_path, ciphers=ciphers, verify_mode=verify_mode
            )

            reader, writer = await asyncio.open_connection(
                self.ip_address, req_cfg.get("port", 8888), ssl=ssl_ctx
            )

            body = req_cfg.get("payload", "")
            body_bytes = body.encode("utf-8") if isinstance(body, str) else body
            local_ip = getattr(self.hass.config.api, "local_ip", None) or "0.0.0.0"
            host = f"{local_ip}:{self.auth_config['listener']['port']}"
            path = req_cfg.get("path", "/devicetoken/request")

            headers = dict(req_cfg.get("headers", {}))
            if body and "Content-Length" not in headers:
                headers["Content-Length"] = str(len(body_bytes))

            req_lines = [
                f"POST {path} HTTP/1.1",
                f"Host: {host}",
            ]
            for k, v in headers.items():
                req_lines.append(f"{k}: {v}")
            req_lines.extend(
                ["", body if isinstance(body, str) else body.decode("utf-8")]
            )

            writer.write("\r\n".join(req_lines).encode("utf-8"))
            await writer.drain()

            try:
                await asyncio.wait_for(reader.read(4096), timeout=5.0)
            except Exception:
                pass

            writer.close()
            await writer.wait_closed()

            return {"ok": True, "config": "listener_started"}

        elif mode == "stream":
            successful_config = await self._connect_stream()
            raw_payload = req_cfg.get("payload", "")
            if isinstance(raw_payload, str):
                payload_bytes = (
                    raw_payload.replace("\\r", "\r")
                    .replace("\\n", "\n")
                    .encode("utf-8")
                )
            else:
                payload_bytes = raw_payload

            self._writer.write(payload_bytes)
            await self._writer.drain()

            try:
                async with asyncio.timeout(15.0):
                    data = await self._reader.read(
                        self.auth_config.get("buffer_size", 4096)
                    )
            except TimeoutError as exc:
                raise TokenAcquisitionError(
                    "Timeout waiting for 'Ready' response"
                ) from exc

            decoded = data.decode("utf-8", errors="ignore")

            succ_cfg = req_cfg.get("success_template", {})
            match_str = succ_cfg.get("match", "")
            fallback_str = succ_cfg.get("fallback_match", "")
            if match_str and match_str not in decoded:
                if not fallback_str or fallback_str not in decoded:
                    raise TokenAcquisitionError("Device did not accept pairing.")

            return successful_config

    async def async_wait_for_token(self) -> str:
        """Phase 2: Wait for user confirmation / incoming token notification."""
        mode = self.auth_config.get("mode")

        try:
            if mode == "listener":
                timeout = self.auth_config.get("listener", {}).get(
                    "timeout_seconds", 60
                )
                async with asyncio.timeout(timeout):
                    await self._token_received_event.wait()
                return self._received_token

            elif mode == "stream":
                if not self._reader:
                    raise TokenAcquisitionError("Connection not established.")
                timeout = self.auth_config.get("wait_token", {}).get(
                    "timeout_seconds", 45
                )
                try:
                    async with asyncio.timeout(timeout):
                        data = await self._reader.read(
                            self.auth_config.get("buffer_size", 4096)
                        )
                except TimeoutError as exc:
                    raise TokenAcquisitionError(
                        "Token not received within timeout window."
                    ) from exc

                if not data:
                    raise TokenAcquisitionError("Connection closed by device.")

                decoded = data.decode("utf-8", errors="ignore")

                err_cfg = self.auth_config.get("error_template", {})
                if err_cfg.get("match", "") in decoded:
                    raise AuthTurnedOffError(
                        "Authentication failed: device is turned off or busy."
                    )

                extract_regex = self.auth_config.get("extract_template", {}).get(
                    "regex"
                )
                match = re.search(extract_regex, decoded)
                if match:
                    return match.group(1)

                raise TokenAcquisitionError(
                    "Regex failed to extract token from stream."
                )

        finally:
            await self.async_close()

    async def async_close(self) -> None:
        """Deterministically close network connections and active server listeners."""
        if self._server:
            try:
                self._server.close()
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
