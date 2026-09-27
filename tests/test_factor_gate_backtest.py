"""Verify the factor gate (E2) is wired into the walk-forward backtest.

factor_signal_series is monkeypatched so these tests are deterministic and
independent of the real factor engine.

The synthetic frame oscillates (3 up / 2 down days per 5) so the incremental
signal-conditioned Kelly can estimate a real (W, R) — an all-wins sample yields
the neutral (0.5, 1.0) prior and sizes flat, which would make the gate invisible.
"""

import pandas as pd

from arthaai.backtest import run_backtest


def _mixed_frame(n=300):
    closes = [100.0]
    for i in range(1, n):
        step = 0.015 if i % 5 in (0, 1, 2) else -0.010
        closes.append(closes[-1] * (1 + step))
    idx = pd.date_range("2023-01-02", periods=n, freq="B", tz="UTC")
    return pd.DataFrame({
        "ts": idx,
        "open": closes,
        "high": [c * 1.005 for c in closes],
        "low": [c * 0.995 for c in closes],
        "close": closes,
        "volume": 1e6,
    })


def _patch_signal(monkeypatch, value):
    import arthaai.agents.quant_agent as qa

    monkeypatch.setattr(
        qa,
        "factor_signal_series",
        lambda symbol, frame, factor_ids=None: pd.Series([value] * len(frame)),
    )


def test_conflicting_factor_signal_reduces_exposure(monkeypatch):
    df = _mixed_frame()
    monkeypatch.setattr("arthaai.db.timescale.load_ohlcv", lambda sym, limit=500: df)
    _patch_signal(monkeypatch, -1.0)
    on = run_backtest("GLD", warmup=60, signal="breakout", factor_gate=True, cost_bps=0.0)
    off = run_backtest("GLD", warmup=60, signal="breakout", factor_gate=False, cost_bps=0.0)
    assert off.total_return != 0.0          # sizing is actually active
    assert abs(on.total_return) < abs(off.total_return)  # dampened => smaller magnitude


def test_confirming_factor_signal_matches_ungated(monkeypatch):
    df = _mixed_frame()
    monkeypatch.setattr("arthaai.db.timescale.load_ohlcv", lambda sym, limit=500: df)
    _patch_signal(monkeypatch, +1.0)
    on = run_backtest("GLD", warmup=60, signal="breakout", factor_gate=True)
    off = run_backtest("GLD", warmup=60, signal="breakout", factor_gate=False)
    assert on.total_return == off.total_return


def test_gate_off_does_not_compute_factor_signal(monkeypatch):
    df = _mixed_frame()
    monkeypatch.setattr("arthaai.db.timescale.load_ohlcv", lambda sym, limit=500: df)
    calls = []
    import arthaai.agents.quant_agent as qa

    monkeypatch.setattr(
        qa,
        "factor_signal_series",
        lambda symbol, frame, factor_ids=None: calls.append(1) or pd.Series([-1.0] * len(frame)),
    )
    run_backtest("GLD", warmup=60, signal="breakout", factor_gate=False)
    assert calls == []
