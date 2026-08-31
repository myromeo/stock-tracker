"""
Dashboard.

Visualizes historical prices and Prophet forecast confidence bands per
symbol. This tool shows statistical trend data only - it does not
recommend trades. All trading decisions are the user's own.
"""
import os

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Stock Trend Tracker", layout="wide")

st.title("📈 Stock Trend Tracker")
st.caption(
    "Personal-use trend tracking with statistical forecasts. "
    "This is not financial advice - all trading decisions are yours to make."
)


@st.cache_data(ttl=60)
def fetch_symbols():
    try:
        resp = requests.get(f"{API_BASE_URL}/symbols", timeout=10)
        resp.raise_for_status()
        return resp.json()["symbols"]
    except Exception as e:
        st.error(f"Could not reach API: {e}")
        return []


@st.cache_data(ttl=60)
def fetch_prices(symbol: str):
    resp = requests.get(f"{API_BASE_URL}/prices/{symbol}", params={"limit": 500}, timeout=10)
    resp.raise_for_status()
    return pd.DataFrame(resp.json()["prices"])


@st.cache_data(ttl=60)
def fetch_predictions(symbol: str):
    resp = requests.get(f"{API_BASE_URL}/predictions/{symbol}", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return pd.DataFrame(data["forecast"]), data["generated_at"]


symbols = fetch_symbols()

if not symbols:
    st.warning(
        "No symbols found yet. The ingestion service may still be pulling its "
        "first batch of data - check back in a few minutes."
    )
    st.stop()

symbol = st.selectbox("Symbol", symbols)

col1, col2 = st.columns([3, 1])

try:
    prices_df = fetch_prices(symbol)
    prices_df["ts"] = pd.to_datetime(prices_df["ts"])
except Exception as e:
    st.error(f"Could not load price history for {symbol}: {e}")
    st.stop()

forecast_df = pd.DataFrame()
generated_at = None
try:
    forecast_df, generated_at = fetch_predictions(symbol)
    if not forecast_df.empty:
        forecast_df["ts"] = pd.to_datetime(forecast_df["ts"])
except Exception:
    pass  # Forecast may not exist yet - that's fine, chart the price history anyway

with col2:
    latest_close = prices_df.iloc[-1]["close"]
    prev_close = prices_df.iloc[-2]["close"] if len(prices_df) > 1 else latest_close
    change = latest_close - prev_close
    pct_change = (change / prev_close * 100) if prev_close else 0

    st.metric(
        label=f"{symbol} last close",
        value=f"${latest_close:,.2f}",
        delta=f"{change:+.2f} ({pct_change:+.2f}%)",
    )

    if generated_at:
        st.caption(f"Forecast generated: {generated_at}")
    else:
        st.caption("Forecast not available yet - model may still be training.")

with col1:
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=prices_df["ts"], y=prices_df["close"],
        mode="lines", name="Historical close",
        line=dict(color="#1f77b4"),
    ))

    if not forecast_df.empty:
        fig.add_trace(go.Scatter(
            x=forecast_df["ts"], y=forecast_df["yhat"],
            mode="lines", name="Forecast",
            line=dict(color="#ff7f0e", dash="dash"),
        ))
        fig.add_trace(go.Scatter(
            x=pd.concat([forecast_df["ts"], forecast_df["ts"][::-1]]),
            y=pd.concat([forecast_df["yhat_upper"], forecast_df["yhat_lower"][::-1]]),
            fill="toself",
            fillcolor="rgba(255,127,14,0.15)",
            line=dict(color="rgba(255,255,255,0)"),
            name="Confidence band (80%)",
            hoverinfo="skip",
        ))

    fig.update_layout(
        height=550,
        xaxis_title="Date",
        yaxis_title="Price (USD)",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.subheader("Recent price data")
st.dataframe(
    prices_df.sort_values("ts", ascending=False).head(20),
    use_container_width=True,
    hide_index=True,
)

st.caption(
    "Data source: Alpha Vantage (delayed, free tier). Forecasts are generated "
    "with Prophet and represent a statistical trend estimate, not a prediction "
    "guarantee. Nothing here constitutes financial advice."
)
