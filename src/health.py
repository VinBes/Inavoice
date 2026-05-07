"""Tiny HTTP listener for Railway / uptime probes.

Runs in a daemon thread alongside Telegram polling so the bot exposes a
`/healthz` endpoint without taking on a web framework dependency.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import structlog

log = structlog.get_logger()

_OK_PAYLOAD = json.dumps({"status": "ok"}).encode()


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — http.server interface
        if self.path in ("/healthz", "/"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(_OK_PAYLOAD)))
            self.end_headers()
            self.wfile.write(_OK_PAYLOAD)
        else:
            self.send_response(404)
            self.end_headers()

    def version_string(self) -> str:
        # Suppress the default `Server: BaseHTTP/x.y Python/z.z.z` header
        # so the health endpoint doesn't disclose the runtime version.
        return ""

    def log_message(self, *args, **kwargs) -> None:
        # Silence default stderr access logs; structlog handles app logs.
        return


def start_health_server(port: int) -> None:
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    threading.Thread(
        target=server.serve_forever, name="health-server", daemon=True
    ).start()
    log.info("health.started", port=port)
