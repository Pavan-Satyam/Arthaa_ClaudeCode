"""Backtest transaction-cost model (ARTHA-312), DB-independent via monkeypatch."""

import pandas as pd

from arthaai.backtest import run_backtest


def _uptrend_frame(n=300, growth=1.015):
    closes = [100.0 * (growth ** i) for i in range(n)]
    idx = pd.date_range("2023-01-02", periods=n, freq="B", tz="UTC")
    return pd.DataFrame({
        "ts": idx,
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": 1e6,
    })


def test_cost_bps_zero_matches_default(monkeypatch):
    df = _uptrend_frame()
    monkeypatch.setattr("arthaai.db.timescale.load_ohlcv", lambda sym, limit=500: df)
    default = run_backtest("GLD", warmup=60, signal="breakout")
    explicit = run_backtest("GLD", warmup=60, signal="breakout", cost_bps=0.0)
    assert default.total_return == explicit.total_return


def test_costs_never_increase_return(monkeypatch):
    df = _uptrend_frame()
    monkeypatch.setattr("arthaai.db.timescale.load_ohlcv", lambda sym, limit=500: df)
    free = run_backtest("GLD", warmup=60, signal="breakout", cost_bps=0.0)
    costly = run_backtest("GLD", warmup=60, signal="breakout", cost_bps=50.0)
    assert costly.total_return <= free.total_return + 1e-12
    assert costly.trades == free.trades  # costs change P&L, not the signal


def test_signal_actually_trades_in_uptrend(monkeypatch):
    df = _uptrend_frame()
    monkeypatch.setattr("arthaai.db.timescale.load_ohlcv", lambda sym, limit=500: df)
    res = run_backtest("GLD", warmup=60, signal="breakout")
    assert res.trades > 0
