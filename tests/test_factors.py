"""Alpha Zoo factor engine — base operators, registry, panel, IC evaluation."""

import numpy as np
import pandas as pd
import pytest

from arthaai.factors.base import (
    rank, zscore, scale, delay, delta, ts_mean, ts_std, ts_max, ts_min,
    ts_rank, ts_argmax, ts_argmin, ts_corr, ts_cov, decay_linear, signed_power,
    safe_div, sigmoid, winsorize, truncate, normalize, ts_sum, ts_var,
    decay_exp, product,
)
from arthaai.factors.panel import build_panel, compute_forward_returns
from arthaai.factors.eval import compute_ic_series, compute_ic_stats, categorise


def _make_wide(n_dates=50, n_cols=3, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=n_dates, freq="B")
    cols = [f"SYM{i}" for i in range(n_cols)]
    return pd.DataFrame(rng.normal(0, 1, (n_dates, n_cols)), index=dates, columns=cols)


# --- Base operator tests ---

class TestCrossSectionalOperators:
    def test_rank_returns_percentile(self):
        df = _make_wide()
        r = rank(df)
        assert r.shape == df.shape
        # Each row should be percentile-ranked in [0, 1]
        row = r.iloc[-1].dropna()
        assert row.min() > 0
        assert row.max() <= 1.0

    def test_zscore_mean_zero(self):
        df = _make_wide()
        z = zscore(df)
        row = z.iloc[-1].dropna()
        assert abs(row.mean()) < 0.01

    def test_scale_l1_norm(self):
        df = _make_wide()
        s = scale(df)
        row = s.iloc[-1].dropna()
        assert abs(row.abs().sum() - 1.0) < 0.01


class TestTimeSeriesOperators:
    def test_delay_shifts(self):
        df = _make_wide()
        d = delay(df, 1)
        # delay(1) means row i of d has the value from row i-1 of df
        np.testing.assert_array_almost_equal(d.iloc[1:].values, df.iloc[:-1].values)

    def test_delta_lookahead_ban(self):
        df = _make_wide()
        with pytest.raises(ValueError, match="lookahead"):
            delta(df, 0)

    def test_ts_mean_warmup_nan(self):
        df = _make_wide()
        m = ts_mean(df, 5)
        assert m.iloc[:4].isna().all().all()
        assert m.iloc[4:].notna().all().all()

    def test_ts_argmax_returns_index(self):
        df = _make_wide()
        a = ts_argmax(df, 3)
        assert a.shape == df.shape
        assert a.iloc[2:].notna().all().all()
        # argmax should be 0-based index into the 3-bar window
        assert a.iloc[-1].dropna().max() <= 2.0

    def test_ts_corr_returns_nan_for_constant(self):
        df = _make_wide()
        const = pd.DataFrame(1.0, index=df.index, columns=df.columns)
        c = ts_corr(df, const, 5)
        assert c.iloc[4:].isna().all().all()


class TestExtraOperators:
    def test_sigmoid_range(self):
        df = _make_wide()
        s = sigmoid(df)
        assert s.shape == df.shape
        assert s.stack().min() > 0
        assert s.stack().max() < 1

    def test_safe_div_zero_denominator(self):
        df = _make_wide()
        zero = pd.DataFrame(0.0, index=df.index, columns=df.columns)
        r = safe_div(df, zero)
        assert r.isna().all().all()

    def test_signed_power_preserves_sign(self):
        df = _make_wide()
        sp = signed_power(df, 2.0)
        assert (np.sign(sp.stack()) == np.sign(df.stack())).all()

    def test_decay_linear_weights(self):
        df = _make_wide()
        d = decay_linear(df, 3)
        assert d.iloc[2:].notna().all().all()


# --- Panel tests ---

class TestPanel:
    def test_build_panel_columns(self):
        dates = pd.date_range("2025-01-01", periods=30, freq="B", tz="UTC")
        data_map = {
            "GLD": pd.DataFrame({"ts": dates, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1e6}).set_index("ts"),
            "SLV": pd.DataFrame({"ts": dates, "open": 50.0, "high": 51.0, "low": 49.0, "close": 50.5, "volume": 2e6}).set_index("ts"),
        }
        panel = build_panel(data_map)
        assert "close" in panel
        assert "volume" in panel
        assert panel["close"].shape == (30, 2)
        assert list(panel["close"].columns) == ["GLD", "SLV"]

    def test_compute_forward_returns(self):
        dates = pd.date_range("2025-01-01", periods=10, freq="B", tz="UTC")
        panel = {"close": pd.DataFrame({"GLD": np.linspace(100, 110, 10)}, index=dates)}
        fwd = compute_forward_returns(panel, horizon=1)
        assert fwd.iloc[-1].isna().all()  # last bar has no forward return
        assert fwd.iloc[0].iloc[0] > 0  # price goes up


# --- IC evaluation tests ---

class TestICEval:
    def test_compute_ic_stats(self):
        ic = pd.Series([-0.01, 0.02, 0.03, 0.01, 0.04, -0.02, 0.05, 0.03, 0.02, 0.01])
        stats = compute_ic_stats(ic)
        assert stats["ic_count"] == 10
        assert abs(stats["ic_mean"] - ic.mean()) < 0.001
        assert "ir" in stats
        assert "t_stat" in stats

    def test_categorise_alive(self):
        cat = categorise(ic_mean=0.05, ic_positive_ratio=0.7, ic_std=0.03, ic_count=100)
        assert cat == "alive"

    def test_categorise_dead(self):
        cat = categorise(ic_mean=0.005, ic_positive_ratio=0.51, ic_std=0.02, ic_count=100)
        assert cat == "dead"

    def test_ic_series_empty_for_no_overlap(self):
        factor = pd.DataFrame({"A": [1, 2, 3]}, index=pd.date_range("2025-01-01", periods=3))
        returns = pd.DataFrame({"B": [0.1, 0.2, 0.3]}, index=pd.date_range("2025-01-01", periods=3))
        ic = compute_ic_series(factor, returns)
        assert ic.empty


# --- Registry tests ---

class TestRegistry:
    def test_registry_loads(self):
        from arthaai.factors.registry import Registry
        reg = Registry()
        health = reg.health()
        assert health["loaded"] > 400  # we have 445 alphas
        assert health["failed"] == 0

    def test_registry_list_by_zoo(self):
        from arthaai.factors.registry import Registry
        reg = Registry()
        alpha101 = reg.list(zoo="alpha101")
        assert len(alpha101) == 101
        gtja = reg.list(zoo="gtja191")
        assert len(gtja) >= 189
        qlib = reg.list(zoo="qlib158")
        assert len(qlib) >= 150

    def test_registry_compute_factor(self):
        from arthaai.factors.registry import Registry
        from arthaai.factors.panel import build_panel

        reg = Registry()
        dates = pd.date_range("2025-01-01", periods=100, freq="B", tz="UTC")
        rng = np.random.default_rng(42)
        close = 100 * np.cumprod(1 + rng.normal(0.001, 0.015, 100))
        data_map = {"GLD": pd.DataFrame({
            "ts": dates, "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": rng.integers(1e6, 5e6, 100).astype(float),
        }).set_index("ts")}
        panel = build_panel(data_map)

        result = reg.compute("alpha101_101", panel)
        assert isinstance(result, pd.DataFrame)
        assert result.shape == panel["close"].shape
