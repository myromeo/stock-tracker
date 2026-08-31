"""
Prediction service.

Reads historical daily closing prices from TimescaleDB, fits a Prophet
time-series model per symbol, and writes the forecast (with upper/lower
confidence bounds) back to the `predictions` table.

This is a statistical trend forecast, not trading advice. It does not
recommend buying or selling anything - the end user interprets the trend
and confidence bands themselves.
"""
import logging
import os
import time

import pandas as pd
import psycopg2
from apscheduler.schedulers.blocking import BlockingScheduler
from prophet import Prophet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("prediction")
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

SYMBOLS = [s.strip().upper() for s in os.environ.get("SYMBOLS", "AAPL,MSFT,GOOGL").split(",") if s.strip()]
FORECAST_DAYS = int(os.environ.get("FORECAST_DAYS", "14"))
RETRAIN_INTERVAL_HOURS = int(os.environ.get("RETRAIN_INTERVAL_HOURS", "6"))
MIN_DATA_POINTS = 30  # Prophet needs a reasonable history to fit sensibly

DB_CONFIG = dict(
    host=os.environ.get("POSTGRES_HOST", "timescaledb"),
    port=os.environ.get("POSTGRES_PORT", "5432"),
    user=os.environ.get("POSTGRES_USER", "stockuser"),
    password=os.environ.get("POSTGRES_PASSWORD", "stockpass"),
    dbname=os.environ.get("POSTGRES_DB", "stocks"),
)


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def load_history(conn, symbol: str) -> pd.DataFrame:
    query = """
        SELECT ts, close FROM prices
        WHERE symbol = %s
        ORDER BY ts ASC
    """
    df = pd.read_sql(query, conn, params=(symbol,))
    return df


def fit_and_forecast(df: pd.DataFrame, horizon_days: int) -> pd.DataFrame:
    prophet_df = df.rename(columns={"ts": "ds", "close": "y"})
    prophet_df["ds"] = pd.to_datetime(prophet_df["ds"]).dt.tz_localize(None)

    model = Prophet(
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality=True,
        interval_width=0.80,
    )
    model.fit(prophet_df)

    future = model.make_future_dataframe(periods=horizon_days)
    forecast = model.predict(future)

    # Only keep the forward-looking portion
    last_history_date = prophet_df["ds"].max()
    forecast = forecast[forecast["ds"] > last_history_date]

    return forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]]


def store_forecast(conn, symbol: str, forecast: pd.DataFrame):
    rows = [
        (symbol, row.ds, float(row.yhat), float(row.yhat_lower), float(row.yhat_upper))
        for row in forecast.itertuples()
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO predictions (symbol, ts, yhat, yhat_lower, yhat_upper)
            VALUES (%s, %s, %s, %s, %s)
            """,
            rows,
        )
    conn.commit()


def run_forecast_cycle():
    log.info("Starting forecast cycle for symbols: %s", SYMBOLS)
    conn = get_connection()
    try:
        for symbol in SYMBOLS:
            try:
                df = load_history(conn, symbol)
                if len(df) < MIN_DATA_POINTS:
                    log.info(
                        "Skipping %s: only %d data points (need >= %d)",
                        symbol, len(df), MIN_DATA_POINTS,
                    )
                    continue

                forecast = fit_and_forecast(df, FORECAST_DAYS)
                store_forecast(conn, symbol, forecast)
                log.info("Stored %d-day forecast for %s", FORECAST_DAYS, symbol)
            except Exception:
                log.exception("Failed to forecast for %s", symbol)
    finally:
        conn.close()
    log.info("Forecast cycle complete")


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
    # Give ingestion a head start so there's data to forecast from
    time.sleep(30)

    run_forecast_cycle()

    scheduler = BlockingScheduler()
    scheduler.add_job(run_forecast_cycle, "interval", hours=RETRAIN_INTERVAL_HOURS)
    log.info("Scheduler started, retraining every %d hours", RETRAIN_INTERVAL_HOURS)
    scheduler.start()
