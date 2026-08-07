# pylint: disable=protected-access,redefined-outer-name,unused-import,unused-variable,unnecessary-pass,import-outside-toplevel,unexpected-keyword-arg,not-context-manager,unused-argument,no-member,invalid-name,pointless-string-statement,reimported,ungrouped-imports,line-too-long,wrong-import-order,unsupported-membership-test
"""Emulator fixtures for Climate IP integration integration tests."""

# pylint: disable=import-outside-toplevel
import json
import logging
import queue
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

_LOGGER = logging.getLogger(__name__)

# --- Mock Data ---
INITIAL_DEVICE_STATE = {
    "Devices": [
        {
            "id": "0",
            "name": "RAC",
            "connected": True,
            "type": "Air_Conditioner",
            "uuid": "00000000-0000-0000-0000-000000000000",
            "Operation": {"power": "Off"},
            "Mode": {
                "modes": ["Auto", "Cool", "Dry", "Wind"],
                "supportedModes": ["Auto", "Cool", "Dry", "Wind"],
                "options": [
                    "Comode_Off",
                    "Sleep_0",
                    "Autoclean_Off",
                    "Spi_Off",
                    "Volume_100",
                ],
            },
            "Temperatures": [
                {
                    "id": "0",
                    "current": 22.0,
                    "desired": 24.0,
                    "unit": "Celsius",
                    "minimum": 16,
                    "maximum": 30,
                }
            ],
            "Wind": {"direction": "Fix", "speedLevel": 0, "maxSpeedLevel": 4},
            "Resources": ["Operation", "Mode", "Temperatures", "Wind", "Information"],
        }
    ]
}


class EmulatorHandler(BaseHTTPRequestHandler):
    """Simulates the Samsung AC 8888 API."""

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # pylint: disable=arguments-differ
        """Suppress default HTTP request logging."""

    def do_GET(self):  # pylint: disable=invalid-name
        """Handle GET requests."""
        if self.path == "/devices":
            data = json.dumps(self.server.device_state).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header(
                "Connection", "close"
            )  # Prevent keep-alive to allow clean shutdown
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.send_header("Connection", "close")
            self.end_headers()

    def do_PUT(self):  # pylint: disable=invalid-name
        """Handle PUT requests."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        if not body:
            # Some commands have no body (URL-routed); treat as empty dict
            payload = {}
        else:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {}

        # Basic state update logic
        device = self.server.device_state["Devices"][0]

        if self.path == "/devices/0/operation":
            if "Operation" in payload:
                device["Operation"].update(payload["Operation"])
            else:
                device["Operation"].update(payload)
        elif self.path == "/devices/0/temperatures/0":
            device["Temperatures"][0].update(payload)
        elif self.path == "/devices/0/mode":
            if "options" in payload:
                # Merge options logic simplified
                device["Mode"]["options"] = payload["options"]
                del payload["options"]
            device["Mode"].update(payload)
        elif self.path == "/devices/0/wind":
            device["Wind"].update(payload)

        data = json.dumps({}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header(
            "Connection", "close"
        )  # Prevent keep-alive to allow clean shutdown
        self.end_headers()
        self.wfile.write(data)

        # Signal that a command was received
        self.server.command_queue.put({"path": self.path, "payload": payload})


class EmulatorServer(HTTPServer):  # pylint: disable=too-few-public-methods
    """HTTP server that maintains device state and a command queue."""

    def __init__(self, *args, **kwargs):
        """Initialize with fresh device state and an empty command queue."""
        super().__init__(*args, **kwargs)
        self.device_state = json.loads(json.dumps(INITIAL_DEVICE_STATE))  # Deep copy
        self.command_queue = queue.Queue()


@pytest.fixture
def emulator_8888():
    """Starts the 8888 emulator in a separate thread.
    Returns an object with methods to access state and command history.
    """
    import pytest_socket

    pytest_socket.enable_socket()

    # Find a free port
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()

    server = EmulatorServer(("127.0.0.1", port), EmulatorHandler)

    # Setup SSL (Self-signed for testing)
    # Note: proper SSL setup for tests might need a generated cert or context
    # For now, we run HTTP or use an ad-hoc context if the integration forces HTTPS.
    # The integration allows disabling verification or providing a cert.

    # We will use simple HTTP for now unless the integration REQUIRES HTTPS.
    # Looking at `connection_aiohttp.py`, it supports both.

    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    yield {
        "port": port,
        "host": "127.0.0.1",
        "state": server.device_state,
        "queue": server.command_queue,
        "reset": lambda: setattr(
            server, "device_state", json.loads(json.dumps(INITIAL_DEVICE_STATE))
        ),
    }

    server.shutdown()
    server.server_close()
