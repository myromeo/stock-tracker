"""
Ingestion service.

Polls Alpha Vantage for daily OHLCV data for a configured list of symbols
and upserts it into the `prices` hypertable. Runs on a schedule and paces
requests to stay within Alpha Vantage's free-tier rate limit (5 calls/min).

This service only reads market data. It does not place trades or give
trading advice - all trading decisions remain with the end user.
"""
import logging
import os
import time
from datetime import datetime, timezone

import psycopg2
import requests
from apscheduler.schedulers.blocking import BlockingScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ingestion")

API_KEY = os.environ["ALPHA_VANTAGE_API_KEY"]
SYMBOLS = [s.strip().upper() for s in os.environ.get("SYMBOLS", "AAPL,MSFT,GOOGL").split(",") if s.strip()]
POLL_INTERVAL_MINUTES = int(os.environ.get("POLL_INTERVAL_MINUTES", "15"))

DB_CONFIG = dict(
    host=os.environ.get("POSTGRES_HOST", "timescaledb"),
    port=os.environ.get("POSTGRES_PORT", "5432"),
    user=os.environ.get("POSTGRES_USER", "stockuser"),
    password=os.environ.get("POSTGRES_PASSWORD", "stockpass"),
    dbname=os.environ.get("POSTGRES_DB", "stocks"),
)

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
# Free tier: 5 requests/minute. Space calls out to stay safely under that.
SECONDS_BETWEEN_CALLS = 13


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def fetch_daily_series(symbol: str) -> dict:
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "outputsize": "compact",  # last 100 data points
        "apikey": API_KEY,
    }
    resp = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if "Time Series (Daily)" not in data:
        # Common causes: rate limit hit, bad symbol, or invalid API key
        log.warning("Unexpected response for %s: %s", symbol, list(data.keys()))
        return {}

    return data["Time Series (Daily)"]


def upsert_prices(conn, symbol: str, series: dict) -> int:
    rows = []
    for date_str, values in series.items():
        ts = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        rows.append((
            symbol,
            ts,
            float(values["1. open"]),
            float(values["2. high"]),
            float(values["3. low"]),
            float(values["4. close"]),
            int(values["5. volume"]),
        ))

    if not rows:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO prices (symbol, ts, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, ts) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def run_poll_cycle():
    log.info("Starting poll cycle for symbols: %s", SYMBOLS)
    conn = get_connection()
    try:
        for i, symbol in enumerate(SYMBOLS):
            try:
                series = fetch_daily_series(symbol)
                count = upsert_prices(conn, symbol, series)
                log.info("Upserted %d rows for %s", count, symbol)
            except Exception:
                log.exception("Failed to fetch/store data for %s", symbol)

            # Pace requests to respect the free-tier rate limit
            if i < len(SYMBOLS) - 1:
                time.sleep(SECONDS_BETWEEN_CALLS)
    finally:
        conn.close()
    log.info("Poll cycle complete")


def wait_for_db():
    for attempt in range(30):
        try:
            conn = get_connection()
            conn.close()
            log.info("Database is ready")
            return
        except psycopg2.OperationalError:
            log.info("Waiting for database... (%d/30)", attempt + 1)
            time.sleep(2)
    raise RuntimeError("Database never became ready")


if __name__ == "__main__":
    wait_for_db()

    # Run once immediately on startup, then on the configured schedule
    run_poll_cycle()

    scheduler = BlockingScheduler()
    scheduler.add_job(run_poll_cycle, "interval", minutes=POLL_INTERVAL_MINUTES)
    log.info("Scheduler started, polling every %d minutes", POLL_INTERVAL_MINUTES)
    scheduler.start()
