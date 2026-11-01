# Binance Trading Desk

HTML dashboard for your Binance spot balances, market watch, candles, and recent fills.

## Run (HTML)

```bash
cp .env.example .env
# edit .env with a read-only Binance API key

python3 serve_dashboard.py
```

Open [http://127.0.0.1:8080/](http://127.0.0.1:8080/).

### Credentials

Create an API key at Binance → API Management:

- Enable **reading** only
- Do **not** enable withdrawals or futures unless you intentionally need them
- Put the key/secret in `.env` (gitignored)

Without credentials the dashboard still loads live public market data; account panels stay empty until keys are set.

### Regional / geo notes

This environment cannot reach `api.binance.com` (HTTP 451). Public market data uses `https://data-api.binance.vision` by default.

If signed account calls fail from your network, set:

```bash
BINANCE_API_BASE=https://api.binance.us   # Binance.US accounts
# or your local/VPN-reachable Binance REST host
```

## Streamlit (optional legacy)

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```
