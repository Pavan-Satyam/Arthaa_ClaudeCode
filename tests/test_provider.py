"""Multi-source ingestion failover chain — LSE → yfinance → empty."""

import pandas as pd
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from arthaai.data.provider import fetch_ohlcv, ingest_resilient, IngestResult


def _make_df(symbol="GLD", n=10):
    dates = pd.date_range("2025-01-01", periods=n, freq="B", tz="UTC")
    return pd.DataFrame({
        "ts": dates, "open": 100.0, "high": 101.0, "low": 99.0,
        "close": 100.5, "volume": 1e6,
    })


def _empty_df():
    return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])


class TestFetchOhlcv:
    def test_lse_succeeds_no_fallback(self, monkeypatch):
        """When LSE returns data, yfinance is never called."""
        df = _make_df()
        monkeypatch.setattr("arthaai.config.get_settings", lambda: type("S", (), {
            "lse_api_key": "test-key", "lse_base_url": "https://fake.lse.com",
        })())
        monkeypatch.setattr("arthaai.data.lse.download", lambda *a, **kw: df)

        yf_called = []
        def _yf_download(*a, **kw):
            yf_called.append(True)
            return _empty_df()
        monkeypatch.setattr("arthaai.data.ingest._download", _yf_download)

        result, provider = fetch_ohlcv("GLD", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 2, 1, tzinfo=timezone.utc))
        assert provider == "lse"
        assert len(result) == 10
        assert not yf_called  # yfinance was never called

    def test_lse_empty_falls_back_to_yfinance(self, monkeypatch):
        """When LSE returns empty (404), yfinance is tried."""
        yf_df = _make_df(n=20)
        monkeypatch.setattr("arthaai.config.get_settings", lambda: type("S", (), {
            "lse_api_key": "test-key", "lse_base_url": "https://fake.lse.com",
        })())
        monkeypatch.setattr("arthaai.data.lse.download", lambda *a, **kw: _empty_df())
        monkeypatch.setattr("arthaai.data.ingest._download", lambda *a, **kw: yf_df)

        result, provider = fetch_ohlcv("USO", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 2, 1, tzinfo=timezone.utc))
        assert provider == "yfinance"
        assert len(result) == 20

    def test_both_empty_returns_none(self, monkeypatch):
        """When both providers return empty, provider is 'none'."""
        monkeypatch.setattr("arthaai.config.get_settings", lambda: type("S", (), {
            "lse_api_key": "test-key", "lse_base_url": "https://fake.lse.com",
        })())
        monkeypatch.setattr("arthaai.data.lse.download", lambda *a, **kw: _empty_df())
        monkeypatch.setattr("arthaai.data.ingest._download", lambda *a, **kw: _empty_df())

        result, provider = fetch_ohlcv("FAKE", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 2, 1, tzinfo=timezone.utc))
        assert provider == "none"
        assert result.empty

    def test_no_lse_key_uses_yfinance(self, monkeypatch):
        """When no LSE API key is set, goes straight to yfinance."""
        yf_df = _make_df(n=15)
        monkeypatch.setattr("arthaai.data.provider.get_settings", lambda: type("S", (), {
            "lse_api_key": None, "lse_base_url": "https://fake.lse.com",
        })())
        monkeypatch.setattr("arthaai.data.ingest._download", lambda *a, **kw: yf_df)

        result, provider = fetch_ohlcv("GLD", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 2, 1, tzinfo=timezone.utc))
        assert provider == "yfinance"
        assert len(result) == 15

    def test_lse_error_falls_back_to_yfinance(self, monkeypatch):
        """When LSE raises an exception, yfinance is tried."""
        yf_df = _make_df(n=10)
        monkeypatch.setattr("arthaai.config.get_settings", lambda: type("S", (), {
            "lse_api_key": "test-key", "lse_base_url": "https://fake.lse.com",
        })())

        def _lse_error(*a, **kw):
            raise ConnectionError("LSE is down")
        monkeypatch.setattr("arthaai.data.lse.download", _lse_error)
        monkeypatch.setattr("arthaai.data.ingest._download", lambda *a, **kw: yf_df)

        result, provider = fetch_ohlcv("GLD", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 2, 1, tzinfo=timezone.utc))
        assert provider == "yfinance"
        assert len(result) == 10


class TestIngestResilient:
    def test_returns_ingest_result(self, monkeypatch):
        """ingest_resilient returns IngestResult with correct fields."""
        df = _make_df(n=50)
        monkeypatch.setattr("arthaai.config.get_settings", lambda: type("S", (), {
            "lse_api_key": "test-key", "lse_base_url": "https://fake.lse.com",
        })())
        monkeypatch.setattr("arthaai.data.lse.download", lambda *a, **kw: df)
        monkeypatch.setattr("arthaai.db.timescale.asset_meta", lambda s: {"symbol": s})
        monkeypatch.setattr("arthaai.db.timescale.latest_ts", lambda s, i: None)
        monkeypatch.setattr("arthaai.db.timescale.upsert_ohlcv", lambda s, i, d: len(d))
        monkeypatch.setattr("arthaai.data.ingest._publish_event", lambda s, n: None)

        result = ingest_resilient("GLD", lookback_days=730, provider="auto")
        assert isinstance(result, IngestResult)
        assert result.rows == 50
        assert result.provider == "lse"
        assert result.symbol == "GLD"
        assert result.incremental is False

    def test_incremental_returns_zero(self, monkeypatch):
        """When data is already up to date, returns 0 rows."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        monkeypatch.setattr("arthaai.db.timescale.asset_meta", lambda s: {"symbol": s})
        monkeypatch.setattr("arthaai.db.timescale.latest_ts", lambda s, i: now)
        monkeypatch.setattr("arthaai.db.timescale.upsert_ohlcv", lambda s, i, d: len(d))

        result = ingest_resilient("GLD", provider="auto")
        assert result.rows == 0
        assert result.incremental is True

    def test_provider_lse_only(self, monkeypatch):
        """provider='lse' never calls yfinance."""
        df = _make_df(n=30)
        monkeypatch.setattr("arthaai.config.get_settings", lambda: type("S", (), {
            "lse_api_key": "test-key", "lse_base_url": "https://fake.lse.com",
        })())
        monkeypatch.setattr("arthaai.data.lse.download", lambda *a, **kw: df)
        monkeypatch.setattr("arthaai.db.timescale.asset_meta", lambda s: {"symbol": s})
        monkeypatch.setattr("arthaai.db.timescale.latest_ts", lambda s, i: None)
        monkeypatch.setattr("arthaai.db.timescale.upsert_ohlcv", lambda s, i, d: len(d))

        yf_called = []
        monkeypatch.setattr("arthaai.data.ingest._download", lambda *a, **kw: yf_called.append(1) or _empty_df())

        result = ingest_resilient("GLD", provider="lse")
        assert result.provider == "lse"
        assert result.rows == 30
        assert not yf_called

    def test_provider_yfinance_only(self, monkeypatch):
        """provider='yfinance' never calls LSE."""
        df = _make_df(n=25)
        monkeypatch.setattr("arthaai.config.get_settings", lambda: type("S", (), {
            "lse_api_key": "test-key", "lse_base_url": "https://fake.lse.com",
        })())
        monkeypatch.setattr("arthaai.db.timescale.asset_meta", lambda s: {"symbol": s})
        monkeypatch.setattr("arthaai.db.timescale.latest_ts", lambda s, i: None)
        monkeypatch.setattr("arthaai.db.timescale.upsert_ohlcv", lambda s, i, d: len(d))
        monkeypatch.setattr("arthaai.data.ingest._download", lambda *a, **kw: df)

        lse_called = []
        monkeypatch.setattr("arthaai.data.lse.download", lambda *a, **kw: lse_called.append(1) or _empty_df())

        result = ingest_resilient("GLD", provider="yfinance")
        assert result.provider == "yfinance"
        assert result.rows == 25
        assert not lse_called
