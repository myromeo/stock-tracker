# Stock Trend Tracker

A self-hosted, personal-use Docker stack that tracks stock prices and
generates statistical trend forecasts. It shows you data and trend
estimates - **it does not give trading advice, and it does not place
trades**. All trading decisions are yours.

## Architecture

```
Alpha Vantage API
       │
       ▼
 ingestion (polls prices) ──► TimescaleDB ◄── prediction (Prophet forecasts)
                                    ▲
                                    │
                                  api (FastAPI, read-only)
                                    ▲
                                    │
                              dashboard (Streamlit)
```

| Service      | Role                                                             |
|--------------|-------------------------------------------------------------------|
| `timescaledb`| Postgres + TimescaleDB, stores price history and forecasts        |
| `ingestion`  | Polls Alpha Vantage on a schedule, writes OHLCV data              |
| `prediction` | Fits a Prophet model per symbol, writes forecasts w/ confidence bands |
| `api`        | FastAPI read-only endpoints over the data                         |
| `dashboard`  | Streamlit UI: price chart + forecast band + recent data table     |

## Setup

1. Get a free Alpha Vantage API key: https://www.alphavantage.co/support/#api-key
2. Copy the environment template and fill in your key:
   ```bash
   cp .env.example .env
   # edit .env: set ALPHA_VANTAGE_API_KEY and SYMBOLS
   ```
3. Start the stack:
   ```bash
   docker compose up -d --build
   ```
4. Open the dashboard: http://localhost:8501
   API docs (Swagger UI): http://localhost:8000/docs

## Notes on the free API tier

Alpha Vantage's free tier allows **5 calls/minute and 500 calls/day**. The
ingestion service paces its requests to stay under this, but if you track
many symbols at a short polling interval you can still hit the daily cap.
Rule of thumb: `symbols × (1440 / POLL_INTERVAL_MINUTES)` should stay well
under 500. The defaults (3 symbols, 15-minute polling) use under 300
calls/day.

Data on the free tier is end-of-day/daily resolution, not real-time intraday
ticks - this stack is built for **trend tracking**, not high-frequency
trading.

## Forecasts are not advice

The `prediction` service uses Facebook Prophet, a standard statistical
forecasting library, to project a trend with an 80% confidence interval.
This is a data analysis tool. It does not:
- recommend buying, selling, or holding anything
- execute trades
- guarantee future performance

Treat the forecast band as "here's the historical trend and its statistical
uncertainty," not as a signal.

## Scaling to more symbols / paid tiers

If you upgrade to a paid Alpha Vantage tier (or switch providers), just
raise `POLL_INTERVAL_MINUTES` down and adjust `SYMBOLS` in `.env`. The
ingestion service's `SECONDS_BETWEEN_CALLS` constant in
`ingestion/main.py` is what enforces the free-tier pacing - relax it if
you have higher rate limits.

## Stopping / resetting

```bash
docker compose down          # stop, keep data
docker compose down -v       # stop and wipe the database volume
```
