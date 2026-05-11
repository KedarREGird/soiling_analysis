"""Small local web server for the soiling-analysis interface."""
from __future__ import annotations

import argparse
import json
import mimetypes
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


class SoilingHandler(BaseHTTPRequestHandler):
    server_version = "SoilingAnalysisWeb/0.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
        if self.path in {"/api/defaults", "/api/defaults/"}:
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
        if self.path not in {"/api/analyze", "/api/analyze/"}:
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

    def _serve_static(self) -> None:
        raw_path = self.path.split("?", 1)[0].strip("/")
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
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local soiling-analysis web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
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
