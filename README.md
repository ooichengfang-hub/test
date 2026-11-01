# Kraken Trading Desk

Streamlit dashboard for crypto portfolio balances, market watch, candles, and recent fills — backed by Kraken.

### How to run it

1. Install dependencies

   ```bash
   pip install -r requirements.txt
   ```

2. Start the app

   ```bash
   streamlit run streamlit_app.py
   ```

### Data modes

| Mode | When it activates | What you see |
|------|-------------------|--------------|
| **Live** | `KRAKEN_API_KEY` + `KRAKEN_API_SECRET` in env or `.streamlit/secrets.toml` | Real balances, trade balance, trade history |
| **Paper** | Local `kraken` CLI with `KRAKEN_WORKSPACE` (default `dashboard`) | Paper equity, balances, and fills |
| **Demo** | Neither of the above | Bundled sample portfolio + live public market data |

Market tickers and OHLC always come from Kraken’s public REST API.

### Live credentials (optional)

Create `.streamlit/secrets.toml` (gitignored):

```toml
KRAKEN_API_KEY = "your-key"
KRAKEN_API_SECRET = "your-secret"
```

Use a **read-only** Kraken key (`Query Funds`, `Query Open/Closed Orders & Trades`). Do not enable withdraw.

### Paper workspace (optional)

```bash
# install kraken-cli, then:
kraken workspace create dashboard --capital 10000 --mode paper -o json
export KRAKEN_WORKSPACE=dashboard
kraken paper buy BTCUSD 0.05 -o json
streamlit run streamlit_app.py
```
