"""London Strategic Edge (LSE) data provider — format conversion and error handling."""

import pandas as pd
import pytest

from arthaai.data import lse


def test_download_returns_empty_on_404(monkeypatch):
    """When LSE returns 404 (symbol not available), return empty DataFrame — not raise."""
    class FakeResp:
        status_code = 404
        def json(self): return {"detail": "Symbol not available via this endpoint."}
        def raise_for_status(self): pass  # not called because we check 404 first

    monkeypatch.setattr("arthaai.data.lse.get_settings", lambda: type("S", (), {
        "lse_api_key": "test-key", "lse_base_url": "https://fake.lse.com",
    })())
    monkeypatch.setattr("httpx.get", lambda *a, **kw: FakeResp())

    df = lse.download("USO", "2025-01-01", "2025-02-01")
    assert df.empty
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]


def test_download_parses_candle_response(monkeypatch):
    """Verify LSE candle JSON is converted to the ArthaAI DataFrame schema."""
    fake_data = [
        {"timestamp": "2025-01-02T14:30:00Z", "open": 190.0, "high": 192.0, "low": 189.0, "close": 191.0, "volume": 5000000.0},
        {"timestamp": "2025-01-03T14:30:00Z", "open": 191.0, "high": 193.0, "low": 190.5, "close": 192.5, "volume": 4000000.0},
    ]

    class FakeResp:
        status_code = 200
        def json(self): return {"symbol": "GLD", "timeframe": "1d", "data": fake_data}
        def raise_for_status(self): pass

    monkeypatch.setattr("arthaai.data.lse.get_settings", lambda: type("S", (), {
        "lse_api_key": "test-key", "lse_base_url": "https://fake.lse.com",
    })())
    monkeypatch.setattr("httpx.get", lambda *a, **kw: FakeResp())

    df = lse.download("GLD", "2025-01-01", "2025-01-31")
    assert len(df) == 2
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert df["close"].iloc[0] == 191.0
    assert df["close"].iloc[1] == 192.5
    assert df["ts"].iloc[0].tz is not None  # UTC-aware


def test_download_requires_api_key(monkeypatch):
    """Without an API key, download should raise a clear error."""
    monkeypatch.setattr("arthaai.data.lse.get_settings", lambda: type("S", (), {
        "lse_api_key": None, "lse_base_url": "https://fake.lse.com",
    })())
    with pytest.raises(RuntimeError, match="LSE_API_KEY"):
        lse.download("GLD", "2025-01-01", "2025-02-01")


def test_friendly_meta_maps_known_symbols():
    name, cls = lse._friendly_meta("GLD")
    assert name == "SPDR Gold Shares"
    assert cls == "commodity_etf"

    name, cls = lse._friendly_meta("AAPL")
    assert name == "Apple Inc."
    assert cls == "equity"

    name, cls = lse._friendly_meta("UNKNOWN")
    assert name == "UNKNOWN"
    assert cls == "equity"
