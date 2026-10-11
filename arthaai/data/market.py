"""Optional market-data adapters with a stable ArthaAI output contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict

import pandas as pd

OHLCV_COLUMNS = ["ts", "open", "high", "low", "close", "volume"]
ACTION_COLUMNS = ["dividends", "stock_splits"]


class CryptoTicker(TypedDict):
    exchange: str
    symbol: str
    timestamp: datetime | None
    last: float | None
    bid: float | None
    ask: float | None
    base_volume: float | None
    quote_volume: float | None


class CryptoOrderBook(TypedDict):
    exchange: str
    symbol: str
    timestamp: datetime | None
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]


class MarketDataFetcher:
    """Fetch adjusted equity bars, crypto quotes, and exchange calendar status.

    Optional providers are imported lazily. Equity OHLC prices are auto-adjusted
    by yfinance for splits and dividends; the action columns are retained when
    available so downstream research can audit corporate actions.
    """

    def __init__(self, exchange_factory: Any | None = None) -> None:
        self._exchange_factory = exchange_factory

    @staticmethod
    def _empty_equity_frame() -> pd.DataFrame:
        return pd.DataFrame(columns=OHLCV_COLUMNS + ACTION_COLUMNS)

    @staticmethod
    def _normalize_equity_frame(raw: pd.DataFrame) -> pd.DataFrame:
        if raw.empty:
            return MarketDataFetcher._empty_equity_frame()

        frame = raw.copy()
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        if "ts" not in frame.columns:
            frame = frame.rename_axis("ts").reset_index()
        normalized_names = {
            str(column).lower().replace(" ", "_"): column for column in frame.columns
        }
        timestamp_column = normalized_names.get("datetime", normalized_names.get("date"))
        if timestamp_column is not None and timestamp_column != "ts":
            frame = frame.rename(columns={timestamp_column: "ts"})
        for column in OHLCV_COLUMNS[1:] + ACTION_COLUMNS:
            source = normalized_names.get(column.lower())
            if source is not None and source != column:
                frame = frame.rename(columns={source: column})
        if "ts" not in frame:
            raise ValueError("equity provider result has no timestamp column or index")

        for column in OHLCV_COLUMNS[1:]:
            if column not in frame:
                frame[column] = pd.NA
        for column in ACTION_COLUMNS:
            if column not in frame:
                frame[column] = 0.0
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True, errors="coerce")
        frame = frame.dropna(subset=["ts"]).sort_values("ts").drop_duplicates("ts", keep="last")
        return frame[OHLCV_COLUMNS + ACTION_COLUMNS].reset_index(drop=True)

    def fetch_equity_ohlcv(
        self,
        ticker: str,
        *,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        period: str | None = None,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch yfinance equity/ETF bars, including dividend and split actions.

        Pass either ``period`` or a ``start`` date (and optional ``end``). The
        interval limits and retention windows are those imposed by Yahoo Finance.
        """
        if period is not None and start is not None:
            raise ValueError("provide period or start/end, not both")
        if period is None and start is None:
            raise ValueError("provide either period or start")

        import yfinance as yf

        raw = yf.download(
            ticker.strip().upper(),
            start=start,
            end=end,
            period=period,
            interval=interval,
            auto_adjust=True,
            actions=True,
            progress=False,
        )
        return self._normalize_equity_frame(raw)

    def _crypto_exchange(self, exchange_id: str):
        if self._exchange_factory is not None:
            return self._exchange_factory(exchange_id)
        import ccxt

        exchange_type = getattr(ccxt, exchange_id, None)
        if exchange_type is None:
            raise ValueError(f"unsupported ccxt exchange: {exchange_id}")
        return exchange_type({"enableRateLimit": True})

    @staticmethod
    def _utc_timestamp(milliseconds: int | None) -> datetime | None:
        if milliseconds is None:
            return None
        return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)

    def fetch_crypto_ticker(self, exchange_id: str, symbol: str) -> CryptoTicker:
        """Fetch a current crypto ticker using a ccxt exchange adapter."""
        exchange = self._crypto_exchange(exchange_id)
        quote = exchange.fetch_ticker(symbol)
        return CryptoTicker(
            exchange=exchange_id,
            symbol=symbol,
            timestamp=self._utc_timestamp(quote.get("timestamp")),
            last=quote.get("last"),
            bid=quote.get("bid"),
            ask=quote.get("ask"),
            base_volume=quote.get("baseVolume"),
            quote_volume=quote.get("quoteVolume"),
        )

    def fetch_crypto_order_book(
        self, exchange_id: str, symbol: str, *, limit: int | None = None
    ) -> CryptoOrderBook:
        """Fetch normalized bid/ask price-level lists from a ccxt exchange."""
        exchange = self._crypto_exchange(exchange_id)
        book = exchange.fetch_order_book(symbol, limit=limit)
        return CryptoOrderBook(
            exchange=exchange_id,
            symbol=symbol,
            timestamp=self._utc_timestamp(book.get("timestamp")),
            bids=[(float(price), float(amount)) for price, amount in book.get("bids", [])],
            asks=[(float(price), float(amount)) for price, amount in book.get("asks", [])],
        )

    @staticmethod
    def is_exchange_open(exchange: str, when: datetime) -> bool:
        """Return whether the named exchange is open at an aware datetime.

        ``exchange`` uses the exchange_calendars calendar name (for example
        ``XNYS`` or ``XLON``). Naive datetimes are rejected to avoid guessing a
        timezone and returning a misleading session result.
        """
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("when must be timezone-aware")
        import exchange_calendars as calendars

        calendar = calendars.get_calendar(exchange.upper())
        return bool(calendar.is_open_on_minute(pd.Timestamp(when).tz_convert("UTC")))