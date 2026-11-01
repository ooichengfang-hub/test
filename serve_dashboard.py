#!/usr/bin/env python3
"""Serve the Binance trading dashboard and proxy public + signed REST calls."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML_FILE = ROOT / "dashboard.html"
ENV_FILE = ROOT / ".env"

# Public market data works from restricted regions via the data CDN.
DEFAULT_DATA_API = "https://data-api.binance.vision"
# Signed account calls need the regional API your key was issued for.
DEFAULT_TRADE_API = "https://api.binance.com"

HOST = "127.0.0.1"
PORT = 8080
WATCH = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def load_dotenv(path: Path = ENV_FILE) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_dotenv()


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


DATA_API = env("BINANCE_DATA_API", DEFAULT_DATA_API).rstrip("/")
TRADE_API = env("BINANCE_API_BASE", DEFAULT_TRADE_API).rstrip("/")
API_KEY = env("BINANCE_API_KEY")
API_SECRET = env("BINANCE_API_SECRET")


def http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> object:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def signed_get(path: str, params: dict[str, object] | None = None) -> object:
    if not API_KEY or not API_SECRET:
        raise PermissionError(
            "Missing BINANCE_API_KEY / BINANCE_API_SECRET. "
            "Copy .env.example to .env and add a read-only Binance API key."
        )
    query = dict(params or {})
    query["timestamp"] = int(time.time() * 1000)
    query.setdefault("recvWindow", 5000)
    encoded = urllib.parse.urlencode(query, doseq=True)
    signature = hmac.new(
        API_SECRET.encode(),
        encoded.encode(),
        hashlib.sha256,
    ).hexdigest()
    url = f"{TRADE_API}{path}?{encoded}&signature={signature}"
    return http_json(url, headers={"X-MBX-APIKEY": API_KEY})


def public_get(path: str, params: dict[str, object] | None = None) -> object:
    qs = urllib.parse.urlencode(params or {}, doseq=True)
    url = f"{DATA_API}{path}"
    if qs:
        url = f"{url}?{qs}"
    return http_json(url)


def non_zero_balances(account: dict) -> list[dict]:
    rows = []
    for bal in account.get("balances", []):
        free = float(bal.get("free") or 0)
        locked = float(bal.get("locked") or 0)
        total = free + locked
        if total <= 0:
            continue
        rows.append(
            {
                "asset": bal["asset"],
                "free": free,
                "locked": locked,
                "total": total,
            }
        )
    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows


def collect_trades(assets: list[str], quote: str = "USDT", limit: int = 30) -> list[dict]:
    trades: list[dict] = []
    for asset in assets:
        if asset in {quote, "USD", "USDC", "BUSD", "FDUSD"}:
            continue
        symbol = f"{asset}{quote}"
        try:
            rows = signed_get("/api/v3/myTrades", {"symbol": symbol, "limit": min(limit, 100)})
        except Exception:
            # Pair may not exist for this asset; skip quietly.
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            trades.append(
                {
                    "id": str(row.get("id")),
                    "symbol": row.get("symbol"),
                    "side": "buy" if row.get("isBuyer") else "sell",
                    "volume": float(row.get("qty") or 0),
                    "price": float(row.get("price") or 0),
                    "cost": float(row.get("quoteQty") or 0),
                    "fee": float(row.get("commission") or 0),
                    "fee_asset": row.get("commissionAsset"),
                    "time": int(row.get("time") or 0),
                }
            )
    trades.sort(key=lambda t: t["time"], reverse=True)
    return trades[:50]


def portfolio_payload() -> dict:
    account = signed_get("/api/v3/account", {"omitZeroBalances": "true"})
    if not isinstance(account, dict):
        raise RuntimeError("Unexpected account payload")
    balances = non_zero_balances(account)
    assets = [b["asset"] for b in balances]
    # Prefer USDT valuation symbols; fall back to raw units for stables.
    prices: dict[str, float] = {"USDT": 1.0, "USD": 1.0, "USDC": 1.0, "FDUSD": 1.0, "BUSD": 1.0}
    symbols = [f"{a}USDT" for a in assets if a not in prices]
    if symbols:
        raw = public_get(
            "/api/v3/ticker/price",
            {"symbols": json.dumps(symbols, separators=(",", ":"))},
        )
        if isinstance(raw, list):
            for row in raw:
                asset = str(row["symbol"]).removesuffix("USDT")
                prices[asset] = float(row["price"])

    holdings = []
    total = 0.0
    for bal in balances:
        px = prices.get(bal["asset"], 0.0)
        value = bal["total"] * px
        total += value
        holdings.append(
            {
                **bal,
                "price": px,
                "value": value,
            }
        )
    holdings.sort(key=lambda h: h["value"], reverse=True)
    for h in holdings:
        h["weight"] = (h["value"] / total * 100) if total else 0.0

    cash = sum(h["value"] for h in holdings if h["asset"] in prices and prices[h["asset"]] == 1.0)
    trades = collect_trades([h["asset"] for h in holdings if h["value"] > 0])

    return {
        "mode": "live",
        "exchange": "binance",
        "api_base": TRADE_API,
        "can_trade": bool(account.get("canTrade")),
        "account_type": account.get("accountType"),
        "equity": total,
        "cash": cash,
        "crypto": total - cash,
        "holdings": holdings,
        "trades": trades,
        "permissions": account.get("permissions") or [],
        "updated_at": int(time.time() * 1000),
    }


def tickers_payload() -> list[dict]:
    raw = public_get(
        "/api/v3/ticker/24hr",
        {"symbols": json.dumps(list(WATCH), separators=(",", ":"))},
    )
    if not isinstance(raw, list):
        raise RuntimeError("Unexpected ticker payload")
    out = []
    for row in raw:
        out.append(
            {
                "symbol": row["symbol"],
                "last": float(row["lastPrice"]),
                "open": float(row["openPrice"]),
                "high": float(row["highPrice"]),
                "low": float(row["lowPrice"]),
                "volume": float(row["volume"]),
                "change_pct": float(row["priceChangePercent"]),
            }
        )
    order = {sym: i for i, sym in enumerate(WATCH)}
    out.sort(key=lambda r: order.get(r["symbol"], 99))
    return out


def klines_payload(symbol: str, interval: str, limit: int = 72) -> list[dict]:
    raw = public_get(
        "/api/v3/klines",
        {"symbol": symbol, "interval": interval, "limit": limit},
    )
    if not isinstance(raw, list):
        raise RuntimeError("Unexpected klines payload")
    return [
        {
            "time": int(row[0] // 1000),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        }
        for row in raw
    ]


def status_payload() -> dict:
    return {
        "exchange": "binance",
        "data_api": DATA_API,
        "trade_api": TRADE_API,
        "has_credentials": bool(API_KEY and API_SECRET),
        "watch": list(WATCH),
        "key_hint": (API_KEY[:4] + "…" + API_KEY[-4:]) if len(API_KEY) >= 8 else None,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: object) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = urllib.parse.parse_qs(parsed.query)

        try:
            if path in {"/", "/dashboard", "/dashboard.html"}:
                self._send(200, HTML_FILE.read_bytes(), "text/html; charset=utf-8")
                return

            if path == "/api/status":
                self._json(200, status_payload())
                return

            if path == "/api/tickers":
                self._json(200, {"tickers": tickers_payload()})
                return

            if path == "/api/klines":
                symbol = (qs.get("symbol") or ["BTCUSDT"])[0].upper()
                interval = (qs.get("interval") or ["4h"])[0]
                limit = int((qs.get("limit") or ["72"])[0])
                if not symbol.endswith("USDT"):
                    self._json(400, {"error": "symbol must be a *USDT pair"})
                    return
                self._json(200, {"symbol": symbol, "interval": interval, "candles": klines_payload(symbol, interval, limit)})
                return

            if path == "/api/portfolio":
                self._json(200, portfolio_payload())
                return

            self._send(404, b"Not found", "text/plain; charset=utf-8")
        except PermissionError as exc:
            self._json(401, {"error": str(exc), "needs_credentials": True})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            try:
                parsed_err = json.loads(detail)
            except json.JSONDecodeError:
                parsed_err = {"msg": detail}
            self._json(
                exc.code,
                {
                    "error": parsed_err.get("msg") or detail,
                    "code": parsed_err.get("code"),
                    "api_base": TRADE_API,
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._json(502, {"error": str(exc)})


def main() -> None:
    if not HTML_FILE.exists():
        raise SystemExit(f"Missing {HTML_FILE}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Binance Trading Desk → http://{HOST}:{PORT}/")
    print(f"Market data: {DATA_API}")
    print(f"Account API: {TRADE_API}")
    print("Credentials:", "configured" if API_KEY and API_SECRET else "missing (public market only)")
    print("Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")


if __name__ == "__main__":
    main()
