"""Crypto trading dashboard powered by Kraken market data.

Modes (first match wins):
1. Live API — Streamlit secrets / env `KRAKEN_API_KEY` + `KRAKEN_API_SECRET`
2. Paper CLI — local `kraken` binary with `KRAKEN_WORKSPACE` (default: dashboard)
3. Demo — bundled snapshot so the UI always loads without credentials
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

DISPLAY_TZ = ZoneInfo("Asia/Kuala_Lumpur")
KRAKEN_PUBLIC = "https://api.kraken.com/0/public"
KRAKEN_PRIVATE = "https://api.kraken.com/0/private"
WATCH_PAIRS = {
    "BTC/USD": "XXBTZUSD",
    "ETH/USD": "XETHZUSD",
    "SOL/USD": "SOLUSD",
}
ASSET_TO_PAIR = {"BTC": "XXBTZUSD", "ETH": "XETHZUSD", "SOL": "SOLUSD", "XBT": "XXBTZUSD"}
STABLES = {"USD", "ZUSD", "USDT", "USDC", "EUR", "ZEUR"}

DEMO_STATUS = {
    "starting_balance": 10000.0,
    "starting_currency": "USD",
    "current_value": 9983.75,
    "unrealized_pnl": -16.25,
    "unrealized_pnl_pct": -0.1625,
    "total_trades": 4,
    "open_orders": 0,
    "mode": "demo",
    "workspace": "demo",
}
DEMO_BALANCES = {
    "BTC": {"total": "0.05", "available": "0.05"},
    "ETH": {"total": "0.5", "available": "0.5"},
    "SOL": {"total": "7", "available": "7"},
    "USD": {"total": "4310.515231", "available": "4310.515231"},
}
DEMO_TRADES = [
    {
        "id": "DEMO-1",
        "pair": "BTCUSD",
        "side": "buy",
        "volume": 0.05,
        "price": 77523.5,
        "fee": 10.078055,
        "cost": 3876.175,
        "time": "2026-11-01T00:50:14Z",
    },
    {
        "id": "DEMO-2",
        "pair": "ETHUSD",
        "side": "buy",
        "volume": 0.5,
        "price": 2257.36,
        "fee": 2.934568,
        "cost": 1128.68,
        "time": "2026-11-01T00:50:14Z",
    },
    {
        "id": "DEMO-3",
        "pair": "SOLUSD",
        "side": "buy",
        "volume": 10.0,
        "price": 95.48,
        "fee": 2.48248,
        "cost": 954.8,
        "time": "2026-11-01T00:50:14Z",
    },
    {
        "id": "DEMO-4",
        "pair": "SOLUSD",
        "side": "sell",
        "volume": 3.0,
        "price": 95.47,
        "fee": 0.744666,
        "cost": 286.41,
        "time": "2026-11-01T00:50:37Z",
    },
]


# ---------------------------------------------------------------------------
# Kraken helpers
# ---------------------------------------------------------------------------

def _secret(name: str) -> str | None:
    try:
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass
    return os.environ.get(name) or None


def _kraken_public(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(f"{KRAKEN_PUBLIC}/{path}", params=params or {}, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(", ".join(payload["error"]))
    return payload["result"]


def _kraken_private(path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    api_key = _secret("KRAKEN_API_KEY")
    api_secret = _secret("KRAKEN_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError("Missing KRAKEN_API_KEY / KRAKEN_API_SECRET")

    payload = dict(data or {})
    payload["nonce"] = str(int(time.time() * 1000))
    postdata = urllib.parse.urlencode(payload)
    encoded = (payload["nonce"] + postdata).encode()
    message = f"/0/private/{path}".encode() + hashlib.sha256(encoded).digest()
    signature = hmac.new(base64.b64decode(api_secret), message, hashlib.sha512)
    headers = {
        "API-Key": api_key,
        "API-Sign": base64.b64encode(signature.digest()).decode(),
    }
    response = requests.post(
        f"{KRAKEN_PRIVATE}/{path}",
        data=payload,
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("error"):
        raise RuntimeError(", ".join(body["error"]))
    return body["result"]


def _run_kraken(*args: str) -> dict[str, Any] | None:
    env = os.environ.copy()
    env.setdefault("KRAKEN_WORKSPACE", "dashboard")
    try:
        completed = subprocess.run(
            ["kraken", *args, "-o", "json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None


def normalize_asset(code: str) -> str:
    code = code.upper()
    aliases = {"XXBT": "BTC", "XBT": "BTC", "XETH": "ETH", "ZUSD": "USD", "ZEUR": "EUR"}
    return aliases.get(code, code.lstrip("XZ") if len(code) > 3 and code[0] in "XZ" else code)


def fmt_money(value: float, currency: str = "USD") -> str:
    return f"${value:,.2f}" if currency in {"USD", "ZUSD", "USDT", "USDC"} else f"{value:,.4f} {currency}"


def fmt_pct(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def to_local(ts: str | float | int | None) -> str:
    if ts is None:
        return "—"
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        else:
            text = str(ts).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M MYT")
    except Exception:
        return str(ts)


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30, show_spinner=False)
def load_tickers(pair_ids: tuple[str, ...]) -> dict[str, Any]:
    result = _kraken_public("Ticker", {"pair": ",".join(pair_ids)})
    return result


@st.cache_data(ttl=60, show_spinner=False)
def load_ohlc(pair_id: str, interval: int = 60) -> pd.DataFrame:
    result = _kraken_public("OHLC", {"pair": pair_id, "interval": interval})
    key = next(k for k in result if k != "last")
    rows = result[key]
    frame = pd.DataFrame(
        rows,
        columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"],
    )
    frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True).dt.tz_convert(DISPLAY_TZ)
    for col in ["open", "high", "low", "close", "vwap", "volume"]:
        frame[col] = frame[col].astype(float)
    return frame


def detect_mode() -> str:
    if _secret("KRAKEN_API_KEY") and _secret("KRAKEN_API_SECRET"):
        return "live"
    if _run_kraken("workspace", "status") is not None:
        return "paper"
    return "demo"


def load_portfolio(mode: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if mode == "live":
        balances_raw = _kraken_private("Balance")
        balances = {
            normalize_asset(asset): {"total": amount, "available": amount}
            for asset, amount in balances_raw.items()
            if float(amount) > 0
        }
        trade_balance = _kraken_private("TradeBalance", {"asset": "ZUSD"})
        status = {
            "starting_balance": float(trade_balance.get("eb", 0) or 0),
            "starting_currency": "USD",
            "current_value": float(trade_balance.get("eb", 0) or 0),
            "unrealized_pnl": float(trade_balance.get("n", 0) or 0),
            "unrealized_pnl_pct": 0.0,
            "total_trades": 0,
            "open_orders": 0,
            "mode": "live",
            "workspace": "kraken",
        }
        trades_raw = _kraken_private("TradesHistory", {"trades": True})
        trades = []
        for trade_id, trade in list((trades_raw.get("trades") or {}).items())[:50]:
            trades.append(
                {
                    "id": trade_id,
                    "pair": trade.get("pair", ""),
                    "side": trade.get("type", ""),
                    "volume": float(trade.get("vol", 0)),
                    "price": float(trade.get("price", 0)),
                    "fee": float(trade.get("fee", 0)),
                    "cost": float(trade.get("cost", 0)),
                    "time": trade.get("time"),
                }
            )
        trades.sort(key=lambda row: float(row.get("time") or 0), reverse=True)
        if status["current_value"]:
            status["unrealized_pnl_pct"] = (
                status["unrealized_pnl"] / status["current_value"]
            ) * 100
        return status, balances, trades

    if mode == "paper":
        status = _run_kraken("workspace", "status") or DEMO_STATUS
        balance_payload = _run_kraken("workspace", "balance") or {}
        balances = balance_payload.get("balances") or DEMO_BALANCES
        history = _run_kraken("paper", "history") or {}
        trades = history.get("trades") or DEMO_TRADES
        return status, balances, trades

    return DEMO_STATUS, DEMO_BALANCES, DEMO_TRADES


def build_holdings(
    balances: dict[str, Any],
    tickers: dict[str, Any],
) -> pd.DataFrame:
    rows = []
    for asset, meta in balances.items():
        symbol = normalize_asset(asset)
        amount = float(meta.get("total") or meta.get("available") or 0)
        if amount <= 0:
            continue
        price = 1.0
        if symbol not in STABLES:
            pair_id = ASSET_TO_PAIR.get(symbol)
            ticker = tickers.get(pair_id or "", {})
            price = float(ticker.get("c", [0])[0] if "c" in ticker else ticker.get("last_price", 0) or 0)
            if not price and pair_id:
                # CLI-shaped ticker fallback already handled; public API uses c[0]
                pass
        value = amount * price
        rows.append(
            {
                "Asset": symbol,
                "Amount": amount,
                "Price (USD)": price,
                "Value (USD)": value,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    total = frame["Value (USD)"].sum()
    frame["Weight %"] = frame["Value (USD)"] / total * 100 if total else 0
    return frame.sort_values("Value (USD)", ascending=False).reset_index(drop=True)


def ticker_frame(tickers: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for label, pair_id in WATCH_PAIRS.items():
        raw = tickers.get(pair_id)
        if not raw:
            continue
        # Public API shape: c/o/h/l/v ; CLI shape: last_price/open/...
        if "c" in raw:
            last = float(raw["c"][0])
            open_px = float(raw["o"])
            high = float(raw["h"][1])
            low = float(raw["l"][1])
            volume = float(raw["v"][1])
        else:
            last = float(raw["last_price"])
            open_px = float(raw["open"])
            high = float(raw["high_24h"])
            low = float(raw["low_24h"])
            volume = float(raw["volume_24h"])
        change_pct = ((last - open_px) / open_px * 100) if open_px else 0.0
        rows.append(
            {
                "Pair": label,
                "Last": last,
                "24h %": change_pct,
                "High": high,
                "Low": low,
                "Volume": volume,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Crypto Trading Dashboard",
    page_icon="▣",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap');
      html, body, [class*="css"]  {
        font-family: 'IBM Plex Sans', sans-serif;
      }
      .block-container { padding-top: 1.4rem; max-width: 1200px; }
      h1, h2, h3 { letter-spacing: -0.02em; }
      div[data-testid="stMetricValue"] {
        font-family: 'IBM Plex Mono', monospace;
      }
      [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f3f6f4 0%, #e7eee9 100%);
      }
      .hero-band {
        background: linear-gradient(135deg, #0f2f24 0%, #1f4d3a 48%, #2f6b4f 100%);
        color: #f4faf6;
        padding: 1.35rem 1.5rem;
        border-radius: 12px;
        margin-bottom: 1.1rem;
      }
      .hero-band h1 {
        margin: 0;
        font-size: 1.75rem;
        font-weight: 600;
        color: #f4faf6;
      }
      .hero-band p {
        margin: 0.35rem 0 0;
        opacity: 0.88;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

mode = detect_mode()
mode_labels = {
    "live": "Live Kraken account",
    "paper": "Paper workspace (kraken-cli)",
    "demo": "Demo snapshot",
}

with st.sidebar:
    st.markdown("### Data source")
    st.write(mode_labels[mode])
    refresh = st.button("Refresh data", use_container_width=True)
    if refresh:
        st.cache_data.clear()
        st.rerun()

    chart_pair_label = st.selectbox("Price chart", list(WATCH_PAIRS.keys()), index=0)
    interval = st.selectbox(
        "Candle interval",
        options=[15, 60, 240, 1440],
        format_func=lambda m: {15: "15m", 60: "1h", 240: "4h", 1440: "1d"}[m],
        index=1,
    )
    st.caption(
        "Add `KRAKEN_API_KEY` and `KRAKEN_API_SECRET` in Streamlit secrets "
        "for your live balances and trades. Without keys, the app uses a local "
        "paper workspace when `kraken` is installed, otherwise a demo portfolio."
    )

st.markdown(
    f"""
    <div class="hero-band">
      <h1>Kraken Trading Desk</h1>
      <p>Portfolio, market tape, and fills · Asia/Kuala_Lumpur · {mode_labels[mode]}</p>
    </div>
    """,
    unsafe_allow_html=True,
)

try:
    tickers = load_tickers(tuple(WATCH_PAIRS.values()))
    status, balances, trades = load_portfolio(mode)
    holdings = build_holdings(balances, tickers)
    markets = ticker_frame(tickers)
    ohlc = load_ohlc(WATCH_PAIRS[chart_pair_label], interval)
except Exception as exc:
    st.error(f"Could not load market or portfolio data: {exc}")
    st.stop()

currency = status.get("starting_currency", "USD")
equity = float(status.get("current_value") or 0)
pnl = float(status.get("unrealized_pnl") or 0)
pnl_pct = float(status.get("unrealized_pnl_pct") or 0)
starting = float(status.get("starting_balance") or 0)
trade_count = int(status.get("total_trades") or len(trades))
cash = next(
    (
        float(meta.get("total") or 0)
        for asset, meta in balances.items()
        if normalize_asset(asset) in STABLES
    ),
    0.0,
)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Equity", fmt_money(equity, currency))
m2.metric("Unrealized P&L", fmt_money(pnl, currency), fmt_pct(pnl_pct))
m3.metric("Cash", fmt_money(cash, currency))
m4.metric("Starting capital", fmt_money(starting, currency))
m5.metric("Fills", f"{trade_count}")

left, right = st.columns((1.35, 1))

with left:
    st.subheader("Holdings")
    if holdings.empty:
        st.info("No balances to show.")
    else:
        display = holdings.copy()
        display["Amount"] = display["Amount"].map(lambda x: f"{x:,.8f}".rstrip("0").rstrip("."))
        display["Price (USD)"] = display["Price (USD)"].map(lambda x: f"${x:,.2f}")
        display["Value (USD)"] = display["Value (USD)"].map(lambda x: f"${x:,.2f}")
        display["Weight %"] = display["Weight %"].map(lambda x: f"{x:.1f}%")
        st.dataframe(display, use_container_width=True, hide_index=True)

        fig_alloc = px.pie(
            holdings,
            names="Asset",
            values="Value (USD)",
            hole=0.55,
            color_discrete_sequence=["#1f4d3a", "#3f7f63", "#7aa891", "#b7d0c3", "#d9e8df"],
        )
        fig_alloc.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            height=280,
            showlegend=True,
            legend=dict(orientation="h", y=-0.05),
        )
        fig_alloc.update_traces(textposition="inside", textinfo="percent+label")
        st.plotly_chart(fig_alloc, use_container_width=True)

with right:
    st.subheader("Market watch")
    if markets.empty:
        st.info("No ticker data.")
    else:
        watch = markets.copy()
        watch["Last"] = watch["Last"].map(lambda x: f"${x:,.2f}")
        watch["24h %"] = watch["24h %"].map(fmt_pct)
        watch["High"] = watch["High"].map(lambda x: f"${x:,.2f}")
        watch["Low"] = watch["Low"].map(lambda x: f"${x:,.2f}")
        watch["Volume"] = watch["Volume"].map(lambda x: f"{x:,.2f}")
        st.dataframe(watch, use_container_width=True, hide_index=True)

    st.subheader(f"{chart_pair_label} price")
    candle = go.Figure(
        data=[
            go.Candlestick(
                x=ohlc["time"],
                open=ohlc["open"],
                high=ohlc["high"],
                low=ohlc["low"],
                close=ohlc["close"],
                increasing_line_color="#2f6b4f",
                decreasing_line_color="#8b3a3a",
                name=chart_pair_label,
            )
        ]
    )
    candle.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis_rangeslider_visible=False,
        yaxis_title="Price (USD)",
        xaxis_title="Time (Asia/Kuala_Lumpur)",
        template="plotly_white",
    )
    st.plotly_chart(candle, use_container_width=True)

st.subheader("Recent fills")
if not trades:
    st.info("No trades yet.")
else:
    trade_rows = []
    for trade in trades:
        trade_rows.append(
            {
                "Time": to_local(trade.get("time")),
                "Pair": trade.get("pair", ""),
                "Side": str(trade.get("side", "")).upper(),
                "Volume": float(trade.get("volume") or 0),
                "Price": float(trade.get("price") or 0),
                "Cost": float(trade.get("cost") or 0),
                "Fee": float(trade.get("fee") or 0),
                "ID": trade.get("id", ""),
            }
        )
    trade_df = pd.DataFrame(trade_rows)
    pretty = trade_df.copy()
    pretty["Volume"] = pretty["Volume"].map(lambda x: f"{x:,.8f}".rstrip("0").rstrip("."))
    pretty["Price"] = pretty["Price"].map(lambda x: f"${x:,.2f}")
    pretty["Cost"] = pretty["Cost"].map(lambda x: f"${x:,.2f}")
    pretty["Fee"] = pretty["Fee"].map(lambda x: f"${x:,.4f}")
    st.dataframe(pretty, use_container_width=True, hide_index=True)

st.caption(
    f"Source: Kraken · refreshed cache ≤30s for tickers · "
    f"last render {datetime.now(DISPLAY_TZ).strftime('%Y-%m-%d %H:%M:%S')} Asia/Kuala_Lumpur"
)
