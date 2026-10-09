"""Correlation Regime agent — risk-off fusion detection (ARTHA-215)."""

import pandas as pd
import pytest

from arthaai.agents import correlation_regime as cr


def _series(values):
    return pd.Series([float(v) for v in values])


class TestAssess:
    def test_perfectly_correlated_is_risk_off(self):
        a = _series([1, -1, 1, -1, 1, -1, 1, -1])
        b = _series([2, -2, 2, -2, 2, -2, 2, -2])
        out = cr.assess({"A": a, "B": b}, window=20)
        assert out["available"] is True
        assert out["regime"] == "risk_off"
        assert out["avg_correlation"] == pytest.approx(1.0)

    def test_anticorrelated_is_diversified(self):
        a = _series([1, -1, 1, -1, 1, -1, 1, -1])
        b = _series([-1, 1, -1, 1, -1, 1, -1, 1])
        out = cr.assess({"A": a, "B": b}, window=20)
        assert out["regime"] == "diversified"
        assert out["avg_correlation"] < 0

    def test_orthogonal_is_mixed_or_diversified(self):
        a = _series([1, 1, -1, -1, 1, 1, -1, -1])
        b = _series([1, -1, 1, -1, 1, -1, 1, -1])
        out = cr.assess({"A": a, "B": b}, window=20)
        assert out["regime"] in {"mixed", "diversified"}
        assert abs(out["avg_correlation"]) < 0.3

    def test_single_asset_unavailable(self):
        out = cr.assess({"A": _series([1, 2, 3])})
        assert out["available"] is False

    def test_insufficient_history_unavailable(self):
        out = cr.assess({"A": _series([1.0]), "B": _series([2.0])}, window=20)
        assert out["available"] is False


class TestRun:
    def test_run_loads_universe(self, monkeypatch):
        import numpy as np

        def fake_load(symbol, limit=1000):
            rng = np.random.default_rng(0)
            base = rng.normal(0, 0.01, 120)
            return pd.DataFrame({"ts": pd.date_range("2024-01-01", periods=120, freq="B", tz="UTC"),
                                 "close": 100 * (1 + base).cumprod()})

        monkeypatch.setattr(cr.timescale, "load_ohlcv", fake_load)
        out = cr.run("GLD", universe=["SLV", "USO"], window=60)
        assert out["available"] is True
        assert out["symbol"] == "GLD"
        assert set(out["assets"]) == {"GLD", "SLV", "USO"}