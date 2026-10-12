"""Operational alert ring buffer (ARTHA-5)."""

from arthaai.observability import alerts


def test_alert_records_and_recent_orders_newest_first():
    alerts._RECENT.clear()
    alerts.alert("breaker", "tripped", symbol="GLD")
    alerts.alert("llm", "fallback")
    recent = alerts.recent(5)
    assert [entry["kind"] for entry in recent] == ["llm", "breaker"]
    assert recent[0]["message"] == "fallback"
    assert recent[1]["fields"] == {"symbol": "GLD"}


def test_recent_limit_and_floor():
    alerts._RECENT.clear()
    for index in range(5):
        alerts.alert("k", f"m{index}")
    assert len(alerts.recent(2)) == 2
    assert alerts.recent(0) == []


def test_provider_empty_fetch_emits_operational_alert(monkeypatch):
    import pandas as pd

    from arthaai.data import provider

    alerts._RECENT.clear()
    monkeypatch.setattr(provider, "fetch_ohlcv", lambda *a, **k: (pd.DataFrame(), "yfinance"))
    monkeypatch.setattr("arthaai.db.timescale.asset_meta", lambda sym: {"symbol": sym})
    monkeypatch.setattr("arthaai.db.timescale.record_ingest_provider", lambda *a, **k: None)
    monkeypatch.setattr("arthaai.db.timescale.record_ingest_batch", lambda *a, **k: None)

    result = provider.refresh_history("ZZZZ", lookback_days=5)
    assert result.rows == 0
    assert any(entry["kind"] == "data_empty" for entry in alerts.recent(10))
