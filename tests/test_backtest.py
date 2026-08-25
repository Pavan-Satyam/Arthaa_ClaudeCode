"""Backtest primitives (DB-independent parts)."""

import pandas as pd
import pytest

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
