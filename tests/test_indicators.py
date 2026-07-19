"""Deterministic indicator layer."""

import numpy as np
import pandas as pd

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
