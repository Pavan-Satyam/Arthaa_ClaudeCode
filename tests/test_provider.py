"""Multi-source ingestion failover chain — LSE → yfinance → empty."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from arthaai.data.provider import (
    IngestResult,
    ProviderRegistry,
    fetch_ohlcv,
    ingest_resilient,
    refresh_history,
    refresh_history_batch,
)


def _make_df(symbol="GLD", n=10):
    dates = pd.date_range("2025-01-01", periods=n, freq="B", tz="UTC")
    return pd.DataFrame({
        "ts": dates, "open": 100.0, "high": 101.0, "low": 99.0,
        "close": 100.5, "volume": 1e6,
    })


def _empty_df():
    return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])


class TestFetchOhlcv:
    def test_configured_default_selects_registered_provider_for_auto(self, monkeypatch):
        calls = []

        class NamedProvider:
            def __init__(self, name):
                self.name = name

            def is_available(self):
                return True

            def fetch_ohlcv(self, *args):
                calls.append(self.name)
                return _make_df(n=4)

        monkeypatch.setattr(
            "arthaai.config.get_settings",
            lambda: type("Settings", (), {"market_data_provider": "vendor"})(),
        )
        frame, source = fetch_ohlcv(
            "AAPL",
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 2, 1, tzinfo=UTC),
            provider="auto",
            registry=ProviderRegistry([NamedProvider("yfinance"), NamedProvider("vendor")]),
        )

        assert source == "vendor"
        assert len(frame) == 4
        assert calls == ["vendor"]

    def test_explicit_provider_overrides_configured_default(self, monkeypatch):
        calls = []

        class NamedProvider:
            def __init__(self, name):
                self.name = name

            def is_available(self):
                return True

            def fetch_ohlcv(self, *args):
                calls.append(self.name)
                return _make_df(n=2)

        monkeypatch.setattr(
            "arthaai.config.get_settings",
            lambda: type("Settings", (), {"market_data_provider": "vendor"})(),
        )
        _, source = fetch_ohlcv(
            "AAPL",
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 2, 1, tzinfo=UTC),
            provider="yfinance",
            registry=ProviderRegistry([NamedProvider("vendor"), NamedProvider("yfinance")]),
        )

        assert source == "yfinance"
        assert calls == ["yfinance"]

    def test_registered_default_provider_is_available_without_manual_injection(self, monkeypatch):
        from arthaai.data import provider as provider_module

        calls = []

        class VendorProvider:
            name = "test_vendor"

            def is_available(self):
                return True

            def fetch_ohlcv(self, *args):
                calls.append(self.name)
                return _make_df(n=1)

        monkeypatch.setattr(provider_module, "_CUSTOM_PROVIDERS", {})
        provider_module.register_provider(VendorProvider())
        monkeypatch.setattr(
            "arthaai.config.get_settings",
            lambda: type("Settings", (), {"market_data_provider": "test_vendor"})(),
        )
        frame, source = fetch_ohlcv(
            "AAPL",
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 2, 1, tzinfo=UTC),
        )

        assert source == "test_vendor"
        assert len(frame) == 1
        assert calls == ["test_vendor"]

    def test_unregistered_configured_provider_fails_clearly(self, monkeypatch):
        monkeypatch.setattr(
            "arthaai.config.get_settings",
            lambda: type("Settings", (), {"market_data_provider": "missing_vendor"})(),
        )
        with pytest.raises(ValueError, match="not registered"):
            fetch_ohlcv(
                "AAPL",
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2025, 2, 1, tzinfo=UTC),
            )

    def test_registry_rejects_duplicate_provider_names(self):
        class VendorProvider:
            name = "vendor"

            def is_available(self):
                return True

            def fetch_ohlcv(self, *args):
                return _make_df()

        with pytest.raises(ValueError, match="unique"):
            ProviderRegistry([VendorProvider(), VendorProvider()])

    def test_custom_registry_provider_can_replace_default_adapters(self):
        class CustomProvider:
            name = "vendor"

            def is_available(self):
                return True

            def fetch_ohlcv(self, symbol, start, end, timeframe):
                assert (symbol, timeframe) == ("AAPL", "1d")
                return _make_df(symbol="AAPL", n=3)

        frame, source = fetch_ohlcv(
            "aapl",
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 2, 1, tzinfo=UTC),
            registry=ProviderRegistry([CustomProvider()]),
        )

        assert source == "vendor"
        assert len(frame) == 3

    def test_registry_auto_falls_through_empty_provider(self):
        calls = []

        class EmptyProvider:
            name = "empty"

            def is_available(self):
                return True

            def fetch_ohlcv(self, *args):
                calls.append(self.name)
                return _empty_df()

        class SecondaryProvider:
            name = "secondary"

            def is_available(self):
                return True

            def fetch_ohlcv(self, *args):
                calls.append(self.name)
                return _make_df(n=2)

        frame, source = fetch_ohlcv(
            "AAPL",
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 2, 1, tzinfo=UTC),
            registry=ProviderRegistry([EmptyProvider(), SecondaryProvider()]),
        )

        assert calls == ["empty", "secondary"]
        assert source == "secondary"
        assert len(frame) == 2

    def test_explicit_provider_does_not_silently_fallback(self):
        calls = []

        class FailingProvider:
            name = "chosen"

            def is_available(self):
                return True

            def fetch_ohlcv(self, *args):
                calls.append(self.name)
                raise ConnectionError("chosen provider failed")

        class BackupProvider:
            name = "backup"

            def is_available(self):
                return True

            def fetch_ohlcv(self, *args):
                calls.append(self.name)
                return _make_df(n=2)

        with pytest.raises(ConnectionError, match="chosen provider failed"):
            fetch_ohlcv(
                "AAPL",
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2025, 2, 1, tzinfo=UTC),
                provider="chosen",
                registry=ProviderRegistry([FailingProvider(), BackupProvider()]),
            )
        assert calls == ["chosen"]

    def test_explicit_unavailable_provider_fails_without_fallback(self):
        class UnavailableProvider:
            name = "licensed"

            def is_available(self):
                return False

            def fetch_ohlcv(self, *args):
                pytest.fail("unavailable provider must not be called")

        class BackupProvider:
            name = "backup"

            def is_available(self):
                return True

            def fetch_ohlcv(self, *args):
                pytest.fail("explicit selection must not fall back")

        with pytest.raises(RuntimeError, match="not available"):
            fetch_ohlcv(
                "AAPL",
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2025, 2, 1, tzinfo=UTC),
                provider="licensed",
                registry=ProviderRegistry([UnavailableProvider(), BackupProvider()]),
            )

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

        result, provider = fetch_ohlcv("GLD", datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC))
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

        result, provider = fetch_ohlcv("USO", datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC))
        assert provider == "yfinance"
        assert len(result) == 20

    def test_both_empty_returns_none(self, monkeypatch):
        """When both providers return empty, provider is 'none'."""
        monkeypatch.setattr("arthaai.config.get_settings", lambda: type("S", (), {
            "lse_api_key": "test-key", "lse_base_url": "https://fake.lse.com",
        })())
        monkeypatch.setattr("arthaai.data.lse.download", lambda *a, **kw: _empty_df())
        monkeypatch.setattr("arthaai.data.ingest._download", lambda *a, **kw: _empty_df())

        result, provider = fetch_ohlcv("FAKE", datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC))
        assert provider == "none"
        assert result.empty

    def test_no_lse_key_uses_yfinance(self, monkeypatch):
        """When no LSE API key is set, goes straight to yfinance."""
        yf_df = _make_df(n=15)
        monkeypatch.setattr("arthaai.config.get_settings", lambda: type("S", (), {
            "lse_api_key": None, "lse_base_url": "https://fake.lse.com",
        })())
        monkeypatch.setattr("arthaai.data.ingest._download", lambda *a, **kw: yf_df)

        result, provider = fetch_ohlcv("GLD", datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC))
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

        result, provider = fetch_ohlcv("GLD", datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC))
        assert provider == "yfinance"
        assert len(result) == 10


class TestIngestResilient:
    @pytest.fixture(autouse=True)
    def _no_provider_tracking(self, monkeypatch):
        """Keep ingest tests DB-free: skip preference read + provider recording."""
        monkeypatch.setattr("arthaai.db.timescale.get_preferred_provider", lambda s: None)
        monkeypatch.setattr("arthaai.db.timescale.record_ingest_provider", lambda *a, **kw: None)

    def test_returns_ingest_result(self, monkeypatch):
        """ingest_resilient returns IngestResult with correct fields."""
        df = _make_df(n=50)
        monkeypatch.setattr("arthaai.config.get_settings", lambda: type("S", (), {
            "lse_api_key": "test-key", "lse_base_url": "https://fake.lse.com",
        })())
        monkeypatch.setattr("arthaai.data.lse.download", lambda *a, **kw: df)
        monkeypatch.setattr("arthaai.db.timescale.asset_meta", lambda s: {"symbol": s})
        monkeypatch.setattr("arthaai.db.timescale.latest_ts", lambda s, i: None)
        monkeypatch.setattr("arthaai.db.timescale.upsert_ohlcv", lambda s, i, d, **kwargs: len(d))
        monkeypatch.setattr("arthaai.data.ingest._publish_event", lambda s, n: None)

        result = ingest_resilient("GLD", lookback_days=730, provider="auto")
        assert isinstance(result, IngestResult)
        assert result.rows == 50
        assert result.provider == "lse"
        assert result.symbol == "GLD"
        assert result.incremental is False

    def test_incremental_returns_zero(self, monkeypatch):
        """When data is already up to date, returns 0 rows."""
        from datetime import datetime
        now = datetime.now(UTC)
        monkeypatch.setattr("arthaai.db.timescale.asset_meta", lambda s: {"symbol": s})
        monkeypatch.setattr("arthaai.db.timescale.latest_ts", lambda s, i: now)
        monkeypatch.setattr("arthaai.db.timescale.upsert_ohlcv", lambda s, i, d, **kwargs: len(d))

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
        monkeypatch.setattr("arthaai.db.timescale.upsert_ohlcv", lambda s, i, d, **kwargs: len(d))

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
        monkeypatch.setattr("arthaai.db.timescale.upsert_ohlcv", lambda s, i, d, **kwargs: len(d))
        monkeypatch.setattr("arthaai.data.ingest._download", lambda *a, **kw: df)

        lse_called = []
        monkeypatch.setattr("arthaai.data.lse.download", lambda *a, **kw: lse_called.append(1) or _empty_df())

        result = ingest_resilient("GLD", provider="yfinance")
        assert result.provider == "yfinance"
        assert result.rows == 25
        assert not lse_called

    def test_preferred_provider_is_honoured_in_auto(self, monkeypatch):
        """A stored per-asset preference forces that provider in auto mode."""
        df = _make_df(n=12)
        monkeypatch.setattr("arthaai.config.get_settings", lambda: type("S", (), {
            "lse_api_key": "test-key", "lse_base_url": "https://fake.lse.com",
        })())
        monkeypatch.setattr("arthaai.db.timescale.asset_meta", lambda s: {"symbol": s})
        monkeypatch.setattr("arthaai.db.timescale.latest_ts", lambda s, i: None)
        monkeypatch.setattr("arthaai.db.timescale.upsert_ohlcv", lambda s, i, d, **kwargs: len(d))
        monkeypatch.setattr("arthaai.db.timescale.get_preferred_provider", lambda s: "yfinance")
        monkeypatch.setattr("arthaai.data.ingest._download", lambda *a, **kw: df)

        lse_called = []
        monkeypatch.setattr("arthaai.data.lse.download", lambda *a, **kw: lse_called.append(1) or _empty_df())

        result = ingest_resilient("GLD", provider="auto")
        assert result.provider == "yfinance"
        assert not lse_called  # pinning yfinance skipped the LSE attempt entirely

    def test_stored_registered_provider_overrides_global_default(self, monkeypatch):
        from arthaai.data.provider import ProviderRegistry

        df = _make_df(n=6)
        calls = []

        class VendorProvider:
            name = "vendor"

            def is_available(self):
                return True

            def fetch_ohlcv(self, *args):
                calls.append("vendor")
                return df

        monkeypatch.setattr("arthaai.db.timescale.asset_meta", lambda symbol: {"symbol": symbol})
        monkeypatch.setattr("arthaai.db.timescale.latest_ts", lambda symbol, timeframe: None)
        monkeypatch.setattr("arthaai.db.timescale.get_preferred_provider", lambda symbol: "vendor")
        monkeypatch.setattr("arthaai.db.timescale.upsert_ohlcv", lambda symbol, timeframe, rows, **kwargs: len(rows))
        monkeypatch.setattr("arthaai.data.ingest._publish_event", lambda *args: None)
        monkeypatch.setattr(
            "arthaai.config.get_settings",
            lambda: type("Settings", (), {"market_data_provider": "yfinance"})(),
        )

        result = ingest_resilient(
            "AAPL", provider="auto", registry=ProviderRegistry([VendorProvider()])
        )

        assert result.provider == "vendor"
        assert calls == ["vendor"]

    def test_records_provider_after_fetch(self, monkeypatch):
        """The provider actually used is persisted for diagnostics."""
        df = _make_df(n=8)
        recorded = []
        monkeypatch.setattr("arthaai.config.get_settings", lambda: type("S", (), {
            "lse_api_key": "test-key", "lse_base_url": "https://fake.lse.com",
        })())
        monkeypatch.setattr("arthaai.db.timescale.asset_meta", lambda s: {"symbol": s})
        monkeypatch.setattr("arthaai.db.timescale.latest_ts", lambda s, i: None)
        monkeypatch.setattr("arthaai.db.timescale.upsert_ohlcv", lambda s, i, d, **kwargs: len(d))
        monkeypatch.setattr("arthaai.data.lse.download", lambda *a, **kw: df)
        monkeypatch.setattr(
            "arthaai.db.timescale.record_ingest_provider",
            lambda sym, prov: recorded.append((sym, prov)),
        )

        ingest_resilient("GLD", provider="auto")
        assert recorded == [("GLD", "lse")]


class TestRefreshHistory:
    def test_refresh_fetches_overlapping_history_and_upserts(self, monkeypatch):
        df = _make_df(n=3)
        calls = {}
        written = []
        registered = []

        def fetch(symbol, start, end, timeframe="1d", **kwargs):
            calls.update(symbol=symbol, start=start, end=end, timeframe=timeframe, **kwargs)
            return df, "yfinance"

        monkeypatch.setattr("arthaai.data.provider.fetch_ohlcv", fetch)
        monkeypatch.setattr("arthaai.db.timescale.asset_meta", lambda symbol: None)
        monkeypatch.setattr(
            "arthaai.db.timescale.ensure_asset",
            lambda *args, **kwargs: registered.append((args, kwargs)),
        )
        monkeypatch.setattr(
            "arthaai.db.timescale.upsert_ohlcv",
            lambda symbol, timeframe, rows, **kwargs: written.append(
                (symbol, timeframe, rows, kwargs)
            ) or len(rows),
        )
        monkeypatch.setattr("arthaai.db.timescale.record_ingest_provider", lambda *args: None)
        monkeypatch.setattr("arthaai.data.ingest._publish_event", lambda *args: None)

        result = refresh_history("aapl", lookback_days=45)

        assert result == IngestResult(rows=3, provider="yfinance", symbol="AAPL", incremental=False)
        assert calls["symbol"] == "AAPL"
        assert calls["timeframe"] == "1d"
        assert 44 <= (calls["end"] - calls["start"]).days <= 45
        assert registered
        assert written[0][0:2] == ("AAPL", "1d")
        assert written[0][3]["source_provider"] == "yfinance"
        assert written[0][3]["adjustment_basis"] == "yfinance_auto_adjust_false"

    def test_refresh_accepts_injected_vendor_adapter(self, monkeypatch):
        from arthaai.data.provider import ProviderRegistry

        saved = []

        class VendorProvider:
            name = "vendor"

            def is_available(self):
                return True

            def fetch_ohlcv(self, symbol, start, end, timeframe):
                return _make_df(symbol=symbol, n=2)

            def provider_symbol(self, symbol):
                return f"{symbol}.US"

        monkeypatch.setattr("arthaai.db.timescale.asset_meta", lambda symbol: {"symbol": symbol})
        monkeypatch.setattr("arthaai.db.timescale.upsert_ohlcv", lambda symbol, interval, rows, **kwargs: saved.append((symbol, interval, rows, kwargs)) or len(rows))
        monkeypatch.setattr("arthaai.db.timescale.record_ingest_provider", lambda *args: None)
        monkeypatch.setattr("arthaai.data.ingest._publish_event", lambda *args: None)

        result = refresh_history(
            "aapl", provider="vendor", registry=ProviderRegistry([VendorProvider()])
        )

        assert result.provider == "vendor"
        assert result.rows == 2
        assert saved[0][0:2] == ("AAPL", "1d")
        assert saved[0][3]["provider_symbol"] == "AAPL.US"

    @pytest.mark.parametrize("lookback_days", [0, -1])
    def test_refresh_rejects_nonpositive_window(self, lookback_days):
        with pytest.raises(ValueError, match="positive"):
            refresh_history("AAPL", lookback_days=lookback_days)

    def test_refresh_rejects_unsupported_timeframe(self):
        with pytest.raises(ValueError, match="timeframe must"):
            refresh_history("AAPL", timeframe="30m")


class TestRefreshHistoryBatch:
    def test_batch_preserves_order_and_continues_after_symbol_failure(self, monkeypatch):
        def refresh(symbol, **kwargs):
            if symbol == "BAD":
                raise ConnectionError("provider unavailable")
            return IngestResult(2, "yfinance", symbol, False)

        monkeypatch.setattr("arthaai.data.provider.refresh_history", refresh)
        results = refresh_history_batch(["aapl", "bad", "msft"])

        assert [item.symbol for item in results] == ["AAPL", "BAD", "MSFT"]
        assert results[0].rows == 2
        assert results[1].provider == "error"
        assert results[1].rows == 0
        assert results[2].provider == "yfinance"

    @pytest.mark.parametrize("symbols", [[], ["AAPL", "aapl"], ["AAPL", ""]])
    def test_batch_rejects_invalid_symbol_lists_before_refresh(self, symbols, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "arthaai.data.provider.refresh_history",
            lambda *args, **kwargs: calls.append(args) or IngestResult(0, "none", args[0], False),
        )
        with pytest.raises(ValueError):
            refresh_history_batch(symbols)
        assert calls == []

    def test_db_error_in_tracking_does_not_break_ingest(self, monkeypatch):
        """A DB predating the provider columns must not break ingestion."""
        df = _make_df(n=5)

        def _boom(*a, **kw):
            raise RuntimeError('column "preferred_provider" does not exist')

        monkeypatch.setattr("arthaai.config.get_settings", lambda: type("S", (), {
            "lse_api_key": "test-key", "lse_base_url": "https://fake.lse.com",
        })())
        monkeypatch.setattr("arthaai.db.timescale.asset_meta", lambda s: {"symbol": s})
        monkeypatch.setattr("arthaai.db.timescale.latest_ts", lambda s, i: None)
        monkeypatch.setattr("arthaai.db.timescale.upsert_ohlcv", lambda s, i, d, **kwargs: len(d))
        monkeypatch.setattr("arthaai.data.lse.download", lambda *a, **kw: df)
        monkeypatch.setattr("arthaai.db.timescale.get_preferred_provider", _boom)
        monkeypatch.setattr("arthaai.db.timescale.record_ingest_provider", _boom)

        result = ingest_resilient("GLD", provider="auto")
        assert result.rows == 5
        assert result.provider == "lse"
