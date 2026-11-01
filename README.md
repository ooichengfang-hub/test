# Kraken Trading Desk

Crypto trading dashboard for portfolio equity, holdings, market watch, candles, and fills — backed by Kraken public market data.

## HTML mode (recommended)

Single-page dashboard with a tiny local proxy (needed because Kraken’s public API does not allow browser CORS).

```bash
python3 serve_dashboard.py
```

Open [http://127.0.0.1:8080/](http://127.0.0.1:8080/).

- Live tickers + OHLC from Kraken
- Portfolio / fills from the `PORTFOLIO` object at the top of `dashboard.html` (seeded from the paper workspace)
- Times shown in **Asia/Kuala_Lumpur**

Edit balances and trades in `dashboard.html` to match your book. For live account balances, keep API secrets off the client — use the Streamlit app with server-side secrets instead.

## Streamlit mode (optional)

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

| Mode | When it activates |
|------|-------------------|
| **Live** | `KRAKEN_API_KEY` + `KRAKEN_API_SECRET` in env or `.streamlit/secrets.toml` |
| **Paper** | Local `kraken` CLI with `KRAKEN_WORKSPACE` |
| **Demo** | Neither of the above |

### Live credentials (Streamlit only)

```toml
# .streamlit/secrets.toml
KRAKEN_API_KEY = "your-key"
KRAKEN_API_SECRET = "your-secret"
```

Use a **read-only** key. Do not enable withdraw.
