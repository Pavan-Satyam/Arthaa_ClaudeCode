"""Backtest primitives (DB-independent parts)."""

import numpy as np
import pandas as pd
import pytest

from arthaai.backtest import engine
from arthaai.backtest.engine import BacktestResult, _max_drawdown


def test_max_drawdown_on_known_series():
    # 1.0 -> 1.2 -> 0.6 -> 0.9 : trough 0.6 vs peak 1.2 = -50%
    eq = pd.Series([1.0, 1.2, 0.6, 0.9])
    assert _max_drawdown(eq) == pytest.approx(-0.5)


def test_no_drawdown_when_monotonic():
    assert _max_drawdown(pd.Series([1.0, 1.1, 1.2])) == pytest.approx(0.0)


def test_result_serialises():
    r = BacktestResult("GLD", 500, 120, 0.12, 0.08, 1.1, -0.2, 0.55, 0.10, 0.18)
    d = r.as_dict()
    assert d["symbol"] == "GLD"
    assert d["total_return"] == 0.12 and d["hit_rate"] == 0.55
    assert d["long_short_return"] == 0.10 and d["long_only_return"] == 0.18


def _ramp_frame(n=120):
    closes = list(np.linspace(100.0, 200.0, n))
    return pd.DataFrame({
        "ts": pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC"),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": 1e6,
    })


def test_signal_series_all_long_matches_buy_and_hold(monkeypatch):
    df = _ramp_frame()
    monkeypatch.setattr(engine.timescale, "load_ohlcv", lambda *a, **k: df)
    res = engine.run_backtest(
        "GLD", warmup=20, limit=120, signal="composite",
        signal_series=pd.Series([1.0] * 120), factor_gate=False,
    )
    assert res.trades == 120 - 20 - 1
    assert res.long_only_return == pytest.approx(res.buy_hold_return, rel=1e-9)


def test_signal_series_nonpositive_is_flat(monkeypatch):
    df = _ramp_frame()
    monkeypatch.setattr(engine.timescale, "load_ohlcv", lambda *a, **k: df)
    res = engine.run_backtest(
        "GLD", warmup=20, limit=120, signal="composite",
        signal_series=pd.Series([-1.0] * 120), factor_gate=False,
    )
    assert res.trades == 0
    assert res.long_only_return == pytest.approx(0.0)


def test_composite_signal_uses_factor_series(monkeypatch):
    df = _ramp_frame()
    monkeypatch.setattr(engine.timescale, "load_ohlcv", lambda *a, **k: df)
    import arthaai.agents.quant_agent as qa

    monkeypatch.setattr(
        qa,
        "factor_signal_series",
        lambda symbol, frame, factor_ids=None: pd.Series([-1.0] * len(frame)),
    )
    res = engine.run_backtest("GLD", warmup=20, limit=120, signal="composite", factor_gate=False)
    assert res.trades == 0
    assert res.long_only_return == pytest.approx(0.0)


def test_composite_signal_unavailable_raises(monkeypatch):
    df = _ramp_frame()
    monkeypatch.setattr(engine.timescale, "load_ohlcv", lambda *a, **k: df)
    import arthaai.agents.quant_agent as qa

    monkeypatch.setattr(
        qa, "factor_signal_series", lambda symbol, frame, factor_ids=None: None
    )
    with pytest.raises(ValueError, match="composite signal unavailable"):
        engine.run_backtest("GLD", warmup=20, limit=120, signal="composite", factor_gate=False)


def test_composite_signal_error_is_wrapped(monkeypatch):
    df = _ramp_frame()
    monkeypatch.setattr(engine.timescale, "load_ohlcv", lambda *a, **k: df)
    import arthaai.agents.quant_agent as qa

    def _boom(symbol, frame, factor_ids=None):
        raise RuntimeError("registry down")

    monkeypatch.setattr(qa, "factor_signal_series", _boom)
    with pytest.raises(ValueError, match="composite signal unavailable"):
        engine.run_backtest("GLD", warmup=20, limit=120, signal="composite", factor_gate=False)
