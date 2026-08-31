"""
API service.

Exposes read-only endpoints over the price history and forecasts stored
in TimescaleDB. This is a data/analysis API only - it has no concept of
orders, positions, or trade execution, and returns no buy/sell advice.
"""
import os
from contextlib import contextmanager
from datetime import date
from typing import Optional

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

DB_CONFIG = dict(
    host=os.environ.get("POSTGRES_HOST", "timescaledb"),
    port=os.environ.get("POSTGRES_PORT", "5432"),
    user=os.environ.get("POSTGRES_USER", "stockuser"),
    password=os.environ.get("POSTGRES_PASSWORD", "stockpass"),
    dbname=os.environ.get("POSTGRES_DB", "stocks"),
)

app = FastAPI(
    title="Stock Trend Tracker API",
    description="Read-only price history and statistical forecasts. Not trading advice.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@contextmanager
def get_connection():
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/symbols")
def list_symbols():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT symbol FROM prices ORDER BY symbol")
            rows = cur.fetchall()
    return {"symbols": [r["symbol"] for r in rows]}


@app.get("/prices/{symbol}")
def get_prices(
    symbol: str,
    start: Optional[date] = Query(None, description="Earliest date to include (YYYY-MM-DD)"),
    end: Optional[date] = Query(None, description="Latest date to include (YYYY-MM-DD)"),
    limit: int = Query(500, le=5000),
):
    symbol = symbol.upper()
    query = "SELECT ts, open, high, low, close, volume FROM prices WHERE symbol = %s"
    params = [symbol]

    if start:
        query += " AND ts >= %s"
        params.append(start)
    if end:
        query += " AND ts <= %s"
        params.append(end)

    query += " ORDER BY ts DESC LIMIT %s"
    params.append(limit)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No price data found for {symbol}")

    return {"symbol": symbol, "count": len(rows), "prices": list(reversed(rows))}


@app.get("/predictions/{symbol}")
def get_predictions(symbol: str):
    """Returns the most recently generated forecast for a symbol."""
    symbol = symbol.upper()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MAX(generated_at) AS latest FROM predictions WHERE symbol = %s",
                (symbol,),
            )
            latest = cur.fetchone()["latest"]

            if latest is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No forecast available yet for {symbol}. It may still be training.",
                )

            cur.execute(
                """
                SELECT ts, yhat, yhat_lower, yhat_upper
                FROM predictions
                WHERE symbol = %s AND generated_at = %s
                ORDER BY ts ASC
                """,
                (symbol, latest),
            )
            rows = cur.fetchall()

    return {
        "symbol": symbol,
        "generated_at": latest,
        "forecast": rows,
    }
