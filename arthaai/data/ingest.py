"""Market-data ingestion via yfinance (free) -> TimescaleDB.

Optionally publishes an ingestion event to the Kafka/Redpanda bus to honour the
blueprint's producer/consumer decoupling; publishing is best-effort and never
blocks ingestion (resilience over coupling).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from arthaai.config import get_settings
from arthaai.db import timescale


def _download(symbol: str, start: datetime, interval: str) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(symbol, start=start, interval=interval, auto_adjust=False, progress=False)
    if raw.empty:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw.reset_index().rename(
        columns={
            "Date": "ts", "Datetime": "ts", "Open": "open", "High": "high",
            "Low": "low", "Close": "close", "Volume": "volume",
        }
    )
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df[["ts", "open", "high", "low", "close", "volume"]]


def _publish_event(symbol: str, n: int) -> None:
    try:
        from confluent_kafka import Producer  # type: ignore

        p = Producer({"bootstrap.servers": get_settings().kafka_bootstrap})
        p.produce(get_settings().ingest_topic, key=symbol, value=f"{n}")
        p.flush(2)
    except Exception:  # noqa: BLE001 - bus is optional; never block ingestion
        pass


def _friendly_meta(symbol: str) -> tuple[str, str]:
    """Best-effort human name + asset class from yfinance; falls back to the symbol."""
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info
        name = info.get("shortName") or info.get("longName") or symbol
        quote = (info.get("quoteType") or "").upper()
        asset_class = "etf" if quote == "ETF" else "equity"
        return name, asset_class
    except Exception:  # noqa: BLE001 - enrichment is optional
        return symbol, "equity"


def ingest(symbol: str, lookback_days: int = 730, interval: str = "1d") -> int:
    """Fetch and persist bars for `symbol`. Returns rows written.

    Auto-registers the asset first so any ticker can be analysed, not just the
    seeded universe.
    """
    symbol = symbol.upper()
    name, asset_class = _friendly_meta(symbol)
    timescale.ensure_asset(symbol, name=name, asset_class=asset_class)
    start = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    df = _download(symbol, start, interval)
    written = timescale.upsert_ohlcv(symbol, interval, df)
    _publish_event(symbol, written)
    return written
