#!/usr/bin/env python3
"""Serve dashboard.html and proxy Kraken public REST (avoids browser CORS)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML_FILE = ROOT / "dashboard.html"
KRAKEN_PUBLIC = "https://api.kraken.com/0/public"
HOST = "127.0.0.1"
PORT = 8080
ALLOWED = {"Ticker", "OHLC", "Spread", "Depth", "Trades", "Time", "SystemStatus", "AssetPairs"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path in {"/", "/dashboard", "/dashboard.html"}:
            body = HTML_FILE.read_bytes()
            self._send(200, body, "text/html; charset=utf-8")
            return

        if path.startswith("/api/kraken/"):
            endpoint = path.split("/api/kraken/", 1)[1]
            if endpoint not in ALLOWED:
                self._send(400, b'{"error":["endpoint not allowed"]}', "application/json")
                return
            query = parsed.query
            url = f"{KRAKEN_PUBLIC}/{endpoint}"
            if query:
                url = f"{url}?{query}"
            try:
                with urllib.request.urlopen(url, timeout=20) as resp:
                    payload = resp.read()
                self._send(200, payload, "application/json")
            except urllib.error.HTTPError as exc:
                self._send(exc.code, exc.read() or b'{"error":["upstream error"]}', "application/json")
            except Exception as exc:  # noqa: BLE001
                body = json.dumps({"error": [str(exc)]}).encode()
                self._send(502, body, "application/json")
            return

        self._send(404, b"Not found", "text/plain; charset=utf-8")


def main() -> None:
    if not HTML_FILE.exists():
        raise SystemExit(f"Missing {HTML_FILE}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Kraken Trading Desk → http://{HOST}:{PORT}/")
    print("Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")


if __name__ == "__main__":
    main()
