"""Deterministic indicator layer."""

import numpy as np
import pandas as pd
import pytest

from arthaai.agents import indicators


def _series(values):
    return pd.Series(values, dtype="float64")


def test_sma_returns_none_when_insufficient():
    assert indicators.sma(_series([1, 2, 3]), 5) is None


def test_sma_value():
    assert indicators.sma(_series([1, 2, 3, 4]), 2) == 3.5


def test_rsi_bounds():
    up = _series(np.linspace(100, 200, 60))
    r = indicators.rsi(up)
    assert r is not None and 0 <= r <= 100 and r > 60  # steady uptrend -> high RSI


def test_annualised_stats_keys():
    close = _series(np.cumprod(1 + np.random.default_rng(0).normal(0, 0.01, 300)) * 100)
    stats = indicators.annualised_stats(close)
    assert {"mu", "variance", "sigma"} <= stats.keys()
    assert stats["sigma"] >= 0


def test_trend_signal_labels():
    up = _series(np.linspace(100, 200, 80))
    label, score = indicators.trend_signal(up)
    assert label in {"bullish", "bearish", "neutral"} and -1 <= score <= 1


def test_signal_kelly_stats_on_trend():
    # A strong uptrend with mild noise: up-days dominate so a persistently
    # bullish trend signal is right more often than wrong -> W > 0.5.
    rng = np.random.default_rng(42)
    rets = rng.normal(0.005, 0.008, 260)  # strong positive drift, mild noise
    up = _series(np.cumprod(1 + rets) * 100)
    w, r = indicators.signal_kelly_stats(up)
    assert 0.0 <= w <= 1.0
    assert r > 0
    assert w > 0.5  # strong uptrend: the bullish signal is right on balance


def test_signal_kelly_stats_random_walk_near_even():
    # A pure random walk has no directional edge, so the hit rate should be
    # close to 0.5 (the signal has no real edge to exploit).
    rng = np.random.default_rng(7)
    rets = rng.normal(0.0, 0.01, 260)
    rw = _series(np.cumprod(1 + rets) * 100)
    w, _ = indicators.signal_kelly_stats(rw)
    assert 0.4 <= w <= 0.6  # no edge -> coin-flip hit rate


def test_signal_kelly_stats_insufficient_history():
    short = _series(np.linspace(100, 110, 10))
    w, r = indicators.signal_kelly_stats(short)
    assert (w, r) == (0.5, 1.0)  # neutral prior when too little history


def test_signal_kelly_stats_bearish_wins_positive_r():
    # A strong downtrend: the trend signal goes bearish and is correct (next-day
    # returns are negative). Before the abs() fix, bearish wins accumulated
    # signed (negative) returns into win_sum, making R negative and forcing flat
    # sizing via discrete_kelly's win_loss_ratio <= 0 guard. R must be positive.
    rng = np.random.default_rng(99)
    rets = rng.normal(-0.005, 0.008, 260)  # strong negative drift
    down = _series(np.cumprod(1 + rets) * 100)
    _w, r = indicators.signal_kelly_stats(down)
    assert r > 0  # bearish wins must not corrupt the payoff ratio


def test_wr_from_tallies_formula():
    # 60 wins, 40 losses, avg win 0.02, avg loss 0.01 -> W=0.6, R=2.0
    w, r = indicators.wr_from_tallies(60, 40, 60 * 0.02, 40 * 0.01)
    assert w == pytest.approx(0.6)
    assert r == pytest.approx(2.0)


def test_wr_from_tallies_no_wins_returns_neutral():
    w, r = indicators.wr_from_tallies(0, 10, 0.0, 0.05)
    assert (w, r) == (0.5, 1.0)


def test_trend_signal_series_matches_per_bar():
    # The vectorized series must produce the same label at every bar as calling
    # trend_signal on the prefix up to that bar. This guards against subtle
    # vectorization divergences (RSI seeding, NaN propagation, etc.).
    rng = np.random.default_rng(123)
    close = _series(np.cumprod(1 + rng.normal(0.001, 0.015, 250)) * 100)
    labels_vec, scores_vec = indicators._trend_signal_series(close)
    for t in range(60, len(close)):
        label_bar, score_bar = indicators.trend_signal(close.iloc[: t + 1])
        assert labels_vec[t] == label_bar, f"label mismatch at bar {t}"
        assert abs(scores_vec[t] - score_bar) < 0.002, f"score mismatch at bar {t}"


def test_signal_kelly_stats_breakout_path():
    # The breakout signal_class path must produce valid (W, R) when given
    # high/low/close. It uses breakout_positions internally (O(n)).
    rng = np.random.default_rng(55)
    rets = rng.normal(0.003, 0.012, 260)
    close = _series(np.cumprod(1 + rets) * 100)
    high = close * (1 + np.abs(rng.normal(0, 0.005, 260)))
    low = close * (1 - np.abs(rng.normal(0, 0.005, 260)))
    w, r = indicators.signal_kelly_stats(close, high=high, low=low, signal_class="breakout")
    assert 0.0 <= w <= 1.0
    assert r > 0


def test_signal_kelly_stats_breakout_needs_high_low():
    # Without high/low, the breakout path must fall back to trend (not crash).
    rng = np.random.default_rng(55)
    close = _series(np.cumprod(1 + rng.normal(0.001, 0.012, 260)) * 100)
    w, r = indicators.signal_kelly_stats(close, signal_class="breakout")
    # Falls back to trend -> still valid
    assert 0.0 <= w <= 1.0
    assert r > 0
