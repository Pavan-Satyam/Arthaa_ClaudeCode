"""London Strategic Edge (LSE) market-data provider.

Fetches historical OHLCV candles from the LSE free API
(https://londonstrategicedge.com) and converts them to the DataFrame format
the rest of ArthaAI expects (ts, open, high, low, close, volume).

The LSE API serves 133 billion ticks across 118K datasets — stocks, ETFs,
forex, crypto, futures, commodities, indices, bond yields and 14K macro
series. The free "registered" plan provides daily/intraday candles via a
single API key.

API structure (discovered 2026-08-25):
    GET /v1/candles?symbol=GLD&timeframe=1d&start=2024-01-01&end=2025-01-01
    Header: X-API-Key: lse_live_...
    Response: {symbol, timeframe, start, end, rows, plan, data: [{timestamp, open, high, low, close, volume}]}

Timeframes: 1m, 5m, 1h, 1d
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd

from arthaai.config import get_settings


def download(
    symbol: str,
    start: str | datetime,
    end: str | datetime,
    timeframe: str = "1d",
) -> pd.DataFrame:
    """Download OHLCV candles for ``symbol`` from LSE.

    Returns a DataFrame with columns: ts, open, high, low, close, volume
    (the same schema as ``data.ingest._download`` uses for yfinance).
    Returns an empty DataFrame if the API call fails or returns no data.
    """
    s = get_settings()
    if not s.lse_api_key:
        raise RuntimeError("LSE_API_KEY not set — add it to .env")

    if isinstance(start, datetime):
        start = start.strftime("%Y-%m-%d")
    if isinstance(end, datetime):
        end = end.strftime("%Y-%m-%d")

    resp = httpx.get(
        f"{s.lse_base_url}/v1/candles",
        headers={"X-API-Key": s.lse_api_key},
        params={"symbol": symbol.upper(), "timeframe": timeframe, "start": start, "end": end},
        timeout=30.0,
    )
    # 404 = symbol not available on LSE (e.g. USO, some ETFs). Return empty
    # so the caller can fall back to yfinance.
    if resp.status_code == 404:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    resp.raise_for_status()
    data = resp.json()
    bars = data.get("data", [])
    if not bars:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(bars)
    df = df.rename(columns={"timestamp": "ts"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df[["ts", "open", "high", "low", "close", "volume"]]


def ingest(symbol: str, lookback_days: int = 730, timeframe: str = "1d") -> int:
    """Fetch candles from LSE and persist to TimescaleDB. Returns rows written.

    Mirrors ``data.ingest.ingest()`` (the yfinance path) so the two providers
    are interchangeable. Uses incremental ingest when possible: if the symbol
    already has data, fetch only from the last known bar to today.
    """
    from arthaai.db import timescale

    symbol = symbol.upper()

    # Incremental: fetch only new bars if we already have history.
    last = timescale.latest_ts(symbol, timeframe)
    now = datetime.now(timezone.utc)
    if last:
        # latest_ts returns naive UTC from PostgreSQL; make it aware for comparison.
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last.date() >= now.date():
            return 0  # today's bar already in the DB
        start = last + timedelta(days=1)
    else:
        start = now - timedelta(days=lookback_days)
    end = now

    # Ensure the asset exists (FK constraint on ohlcv table).
    if not timescale.asset_meta(symbol):
        name, asset_class = _friendly_meta(symbol)
        timescale.ensure_asset(symbol, name=name, asset_class=asset_class)

    df = download(symbol, start, end, timeframe=timeframe)
    if df.empty:
        return 0
    return timescale.upsert_ohlcv(symbol, timeframe, df)


def _friendly_meta(symbol: str) -> tuple[str, str]:
    """Best-effort name + asset class for LSE symbols."""
    symbol = symbol.upper()
    etfs = {"GLD": "SPDR Gold Shares", "SLV": "iShares Silver Trust",
            "USO": "United States Oil Fund", "XOM": "Exxon Mobil", "AAPL": "Apple Inc.",
            "DBC": "Invesco DB Commodity Index", "TSLA": "Tesla Inc."}
    commodities = {"GLD", "SLV", "USO", "DBC"}
    name = etfs.get(symbol, symbol)
    asset_class = "commodity_etf" if symbol in commodities else "equity"
    return name, asset_class
