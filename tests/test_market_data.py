"""Offline tests for normalized market-data adapters."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from arthaai.data.market import MarketDataFetcher


def test_equity_fetch_requests_adjusted_prices_and_actions(monkeypatch):
    calls = {}
    raw = pd.DataFrame(
        {
            "Open": [10.0],
            "High": [12.0],
            "Low": [9.0],
            "Close": [11.0],
            "Volume": [100],
            "Dividends": [0.5],
            "Stock Splits": [2.0],
        },
        index=pd.DatetimeIndex(["2025-01-02"], name="Date"),
    )

    def download(ticker, **kwargs):
        calls["ticker"] = ticker
        calls.update(kwargs)
        return raw

    monkeypatch.setitem(__import__("sys").modules, "yfinance", SimpleNamespace(download=download))
    result = MarketDataFetcher().fetch_equity_ohlcv("aapl", period="1mo", interval="1d")

    assert calls["ticker"] == "AAPL"
    assert calls["auto_adjust"] is True
    assert calls["actions"] is True
    assert list(result.columns) == [
        "ts", "open", "high", "low", "close", "volume", "dividends", "stock_splits"
    ]
    assert result.loc[0, "ts"] == pd.Timestamp("2025-01-02", tz="UTC")
    assert result.loc[0, "dividends"] == 0.5
    assert result.loc[0, "stock_splits"] == 2.0


def test_equity_fetch_requires_period_or_start():
    with pytest.raises(ValueError, match="either period or start"):
        MarketDataFetcher().fetch_equity_ohlcv("AAPL")


def test_crypto_ticker_and_order_book_are_normalized():
    class FakeExchange:
        def fetch_ticker(self, symbol):
            assert symbol == "BTC/USD"
            return {
                "timestamp": 1_735_776_000_000,
                "last": 100.0,
                "bid": 99.5,
                "ask": 100.5,
                "baseVolume": 2.0,
                "quoteVolume": 200.0,
            }

        def fetch_order_book(self, symbol, limit=None):
            return {"timestamp": None, "bids": [[99.5, 3]], "asks": [[100.5, 4]]}

    fetcher = MarketDataFetcher(exchange_factory=lambda exchange_id: FakeExchange())
    ticker = fetcher.fetch_crypto_ticker("coinbase", "BTC/USD")
    book = fetcher.fetch_crypto_order_book("coinbase", "BTC/USD", limit=10)

    assert ticker["exchange"] == "coinbase"
    assert ticker["last"] == 100.0
    assert ticker["timestamp"].tzinfo == UTC
    assert book["bids"] == [(99.5, 3.0)]
    assert book["asks"] == [(100.5, 4.0)]


def test_exchange_calendar_requires_aware_datetime(monkeypatch):
    class Calendar:
        def is_open_on_minute(self, timestamp):
            assert timestamp.utcoffset().total_seconds() == 0
            return True

    monkeypatch.setitem(
        __import__("sys").modules,
        "exchange_calendars",
        SimpleNamespace(get_calendar=lambda name: Calendar()),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        MarketDataFetcher.is_exchange_open(
            "XNYS", datetime(2025, 1, 2, 15, 0, tzinfo=UTC).replace(tzinfo=None)
        )

    assert MarketDataFetcher.is_exchange_open(
        "xnys", datetime(2025, 1, 2, 15, 0, tzinfo=UTC)
    ) is True