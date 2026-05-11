"""Small local web server for the soiling-analysis interface."""
from __future__ import annotations

import argparse
import base64
import hmac
import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .analysis import (
    DEFAULT_END_DATE,
    DEFAULT_INVERTER_NAME,
    DEFAULT_PLANT_UUID,
    DEFAULT_START_DATE,
    DEFAULT_STRING_PORT,
    analyze_single_string,
)
from .config import SoilingConfig


ROOT = Path(__file__).resolve().parents[1]
API_PATHS = {"/api/defaults", "/api/defaults/", "/api/analyze", "/api/analyze/"}
HEALTH_PATHS = {"/api/health", "/api/health/"}


class SoilingHandler(BaseHTTPRequestHandler):
    server_version = "SoilingAnalysisWeb/0.1"

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib hook name
        if self._request_path() not in API_PATHS | HEALTH_PATHS:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return

        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
        path = self._request_path()
        if path in HEALTH_PATHS:
            self._send_json({"status": "ok"})
            return
        if self._reject_unauthorized():
            return
        if path in {"/api/defaults", "/api/defaults/"}:
            self._send_json(
                {
                    "plant_id": DEFAULT_PLANT_UUID,
                    "inverter_name": DEFAULT_INVERTER_NAME,
                    "string_port": DEFAULT_STRING_PORT,
                    "start_date": DEFAULT_START_DATE.isoformat(),
                    "end_date": DEFAULT_END_DATE.isoformat(),
                    "config": SoilingConfig().model_dump(),
                }
            )
            return

        self._serve_static()

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
        if self._reject_unauthorized():
            return
        if self._request_path() not in {"/api/analyze", "/api/analyze/"}:
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return

        try:
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            payload = json.loads(body)
            result = analyze_single_string(payload)
        except Exception as exc:
            self._send_json({"error": str(exc), "type": type(exc).__name__}, HTTPStatus.BAD_REQUEST)
            return

        self._send_json(result)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _request_path(self) -> str:
        return self.path.split("?", 1)[0]

    def _reject_unauthorized(self) -> bool:
        username = os.environ.get("SOILING_BASIC_AUTH_USERNAME")
        password = os.environ.get("SOILING_BASIC_AUTH_PASSWORD")
        if not username or not password:
            return False

        auth = self.headers.get("Authorization", "")
        prefix = "Basic "
        if auth.startswith(prefix):
            try:
                decoded = base64.b64decode(auth[len(prefix):], validate=True).decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                decoded = ""
            expected = f"{username}:{password}"
            if hmac.compare_digest(decoded, expected):
                return False

        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Soiling Analysis"')
        self._send_cors_headers()
        self.end_headers()
        return True

    def _serve_static(self) -> None:
        raw_path = self._request_path().strip("/")
        rel_path = raw_path or "index.html"
        candidate = (ROOT / rel_path).resolve()
        if not str(candidate).startswith(str(ROOT)) or not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        content_type, _ = mimetypes.guess_type(candidate)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(candidate.stat().st_size))
        self.end_headers()
        with candidate.open("rb") as fh:
            self.wfile.write(fh.read())

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._send_cors_headers()
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        allowed = [
            item.strip()
            for item in os.environ.get("SOILING_ALLOWED_ORIGINS", "*").split(",")
            if item.strip()
        ]
        if "*" in allowed:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local soiling-analysis web UI.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", default=int(os.environ.get("PORT", "8765")), type=int)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), SoilingHandler)
    print(f"Soiling analysis web UI: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
