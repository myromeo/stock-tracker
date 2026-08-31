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

## Quick start (build locally)

1. Get a free Alpha Vantage API key: https://www.alphavantage.co/support/#api-key
2. Copy the environment template and fill in your key:
   ```bash
   cp .env.example .env
   # edit .env: set ALPHA_VANTAGE_API_KEY and SYMBOLS
   ```
3. Start the stack, building images locally:
   ```bash
   docker compose up -d --build
   ```
4. Open the dashboard: http://localhost:8501
   API docs (Swagger UI): http://localhost:8000/docs

## CI: automated image builds (GitHub Actions)

`.github/workflows/docker-build.yml` builds all four service images
(`ingestion`, `prediction`, `api`, `dashboard`) and publishes them to
GitHub Container Registry (GHCR) as:

```
ghcr.io/<owner>/stock-tracker-ingestion
ghcr.io/<owner>/stock-tracker-prediction
ghcr.io/<owner>/stock-tracker-api
ghcr.io/<owner>/stock-tracker-dashboard
```

It triggers on:
- pushes to `main` that touch any service directory (tags images `latest` + short commit sha)
- version tags like `v1.0.0` (tags images `1.0.0` and `1.0`)
- pull requests (build-only, no push - validates the Dockerfiles still work)
- manual runs via the Actions tab ("Run workflow")

**No setup needed for the workflow itself** - it authenticates to GHCR
using the automatically-provided `GITHUB_TOKEN`, which already has
`packages: write` permission granted in the workflow file. Just push it to
the repo and it runs.

**One manual step:** the first time each image is published, GHCR makes it
**private** by default. If you want to `docker compose pull` without
authenticating, go to your GitHub profile → **Packages**, open each
`stock-tracker-*` package → **Package settings** → **Change visibility** →
**Public**. If you're fine keeping them private, `docker login ghcr.io`
with a personal access token (`read:packages` scope) before pulling instead.

To cut a versioned release: `git tag v1.0.0 && git push --tags`.

## Running from pre-built images

Once the workflow has published images at least once, you can skip local
builds entirely:

```bash
cp .env.example .env
# edit .env: set ALPHA_VANTAGE_API_KEY, SYMBOLS, GITHUB_OWNER, IMAGE_TAG
docker compose -f docker-compose.prod.yml up -d
```

`GITHUB_OWNER` should be your GitHub username/org (`myromeo` for this repo).
`IMAGE_TAG` defaults to `latest`; pin it to a release tag (e.g. `v1.0.0`)
for anything you want to keep stable.

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

# or, if running the prod compose file:
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml down -v
```
