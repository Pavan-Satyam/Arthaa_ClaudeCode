"""Multi-source ingestion failover chain.

Tries LSE (London Strategic Edge) first, falls back to yfinance when LSE
returns empty (symbol not available, e.g. USO) or errors. A single
``ingest_resilient()`` entry point means the user never needs to know which
provider has which symbol.

Provider chain (auto mode):
    1. LSE  — if API key set, returns empty DataFrame on 404
    2. yfinance — fallback for any symbol LSE doesn't have
    3. If both empty → symbol not found anywhere

Each provider's incremental ingest is preserved: ``latest_ts()`` is checked
before fetching so only new bars are downloaded.

Usage::

    from arthaai.data.provider import ingest_resilient
    rows, provider = ingest_resilient("GLD")
    print(f"ingested {rows} bars via {provider}")
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

import pandas as pd

from arthaai.config import get_settings
from arthaai.db import timescale


@dataclass
class IngestResult:
    """Outcome of a resilient ingest — how many bars and which provider succeeded."""

    rows: int
    provider: str  # "lse" | "yfinance" | "none"
    symbol: str
    incremental: bool  # True if only fetched new bars


def fetch_ohlcv(
    symbol: str,
    start: datetime,
    end: datetime,
    timeframe: str = "1d",
) -> tuple[pd.DataFrame, str]:
    """Fetch OHLCV through the provider chain. Returns (DataFrame, provider_name).

    LSE is tried first (if API key is configured). If it returns empty (404 /
    symbol not available) or errors, yfinance is tried. If both return empty,
    an empty DataFrame is returned with provider="none".
    """
    symbol = symbol.upper()
    s = get_settings()

    # 1. Try LSE first (richer data, 2-year history, faster for many symbols)
    if s.lse_api_key:
        try:
            from arthaai.data import lse

            df = lse.download(symbol, start, end, timeframe=timeframe)
            if not df.empty:
                return df, "lse"
        except Exception:
            pass  # LSE error → fall through to yfinance

    # 2. Fallback to yfinance
    try:
        from arthaai.data import ingest as yf_ingest

        # yfinance uses "1d" / "1h" / "5m" / "1m" — map LSE timeframe if needed
        yf_interval = timeframe if timeframe in ("1d", "1h", "5m", "1m") else "1d"
        df = yf_ingest._download(symbol, start, yf_interval)
        if not df.empty:
            return df, "yfinance"
    except Exception:
        pass

    return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"]), "none"


def _friendly_meta(symbol: str) -> tuple[str, str]:
    """Best-effort name + asset class — tries yfinance, falls back to LSE map."""
    try:
        from arthaai.data import ingest as yf_ingest

        return yf_ingest._friendly_meta(symbol)
    except Exception:
        from arthaai.data import lse

        return lse._friendly_meta(symbol)


def ingest_resilient(
    symbol: str,
    lookback_days: int = 730,
    timeframe: str = "1d",
    provider: str = "auto",
) -> IngestResult:
    """Fetch OHLCV through the provider chain and persist to TimescaleDB.

    Args:
        symbol: Ticker symbol (e.g. "GLD", "USO", "AAPL").
        lookback_days: How far back to fetch if no existing data.
        timeframe: Candle timeframe — 1d, 1h, 5m, 1m.
        provider: "auto" (LSE → yfinance), "lse" (LSE only), "yfinance" (yfinance only).

    Returns:
        IngestResult with rows written, which provider succeeded, and whether
        the ingest was incremental (only new bars).
    """
    symbol = symbol.upper()

    # Ensure the asset exists (FK constraint)
    if not timescale.asset_meta(symbol):
        name, asset_class = _friendly_meta(symbol)
        timescale.ensure_asset(symbol, name=name, asset_class=asset_class)

    # Incremental: check if we already have data
    last = timescale.latest_ts(symbol, timeframe)
    now = datetime.now(timezone.utc)
    incremental = False

    if last:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last.date() >= now.date():
            return IngestResult(rows=0, provider="none", symbol=symbol, incremental=True)
        start = last + timedelta(days=1)
        incremental = True
    else:
        start = now - timedelta(days=lookback_days)

    # Route to the appropriate provider
    if provider == "lse":
        from arthaai.data import lse

        df = lse.download(symbol, start, now, timeframe=timeframe)
        used = "lse" if not df.empty else "none"
    elif provider == "yfinance":
        from arthaai.data import ingest as yf_ingest

        yf_interval = timeframe if timeframe in ("1d", "1h", "5m", "1m") else "1d"
        df = yf_ingest._download(symbol, start, yf_interval)
        used = "yfinance" if not df.empty else "none"
    else:
        # auto: try LSE first, fall back to yfinance
        df, used = fetch_ohlcv(symbol, start, now, timeframe=timeframe)

    if df.empty:
        return IngestResult(rows=0, provider=used, symbol=symbol, incremental=incremental)

    written = timescale.upsert_ohlcv(symbol, timeframe, df)

    # Publish Kafka event (best-effort, never blocks)
    try:
        from arthaai.data import ingest as yf_ingest

        yf_ingest._publish_event(symbol, written)
    except Exception:
        pass

    return IngestResult(rows=written, provider=used, symbol=symbol, incremental=incremental)
