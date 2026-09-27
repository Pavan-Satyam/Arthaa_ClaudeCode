"""Factor IC evaluation: rank-IC, embargo step, and Benjamini-Hochberg FDR."""

import numpy as np
import pandas as pd
import pytest

from arthaai.factors.eval import (
    benjamini_hochberg,
    compute_ic_series,
    evaluate_factors,
    t_to_p,
)


def _frame(n_dates=60, n_syms=10, seed=0, scale=0.01):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=n_dates, freq="B")
    cols = [f"S{i}" for i in range(n_syms)]
    return pd.DataFrame(rng.normal(0, scale, (n_dates, n_syms)), index=dates, columns=cols)


class TestTToP:
    def test_zero_is_one(self):
        assert t_to_p(0.0) == pytest.approx(1.0)

    def test_known_two_sided_value(self):
        assert t_to_p(1.959964) == pytest.approx(0.05, abs=0.005)

    def test_symmetric(self):
        assert t_to_p(-2.5) == pytest.approx(t_to_p(2.5))


class TestBenjaminiHochberg:
    def test_empty(self):
        assert benjamini_hochberg([], 0.05) == []

    def test_clear_discovery(self):
        assert benjamini_hochberg([0.001, 0.5, 0.9], 0.05) == [True, False, False]

    def test_all_small_accepted(self):
        assert all(benjamini_hochberg([0.001, 0.002, 0.003], 0.05))

    def test_all_large_rejected(self):
        assert not any(benjamini_hochberg([0.3, 0.4, 0.9], 0.05))

    def test_mask_aligned_to_input_order(self):
        # smallest p is last -> only last flagged
        assert benjamini_hochberg([0.9, 0.8, 0.0001], 0.05) == [False, False, True]


class TestIcSeriesEmbargo:
    def test_step_subsamples_series(self):
        factor = _frame(seed=1)
        ret = _frame(seed=2)
        full = compute_ic_series(factor, ret, step=1)
        half = compute_ic_series(factor, ret, step=3)
        assert len(half) == len(full.iloc[::3])

    def test_no_overlap_returns_empty(self):
        f = pd.DataFrame({"A": [1, 2, 3]}, index=pd.date_range("2025-01-01", periods=3))
        r = pd.DataFrame({"B": [0.1, 0.2, 0.3]}, index=pd.date_range("2025-01-01", periods=3))
        assert compute_ic_series(f, r).empty


class TestEvaluateFactors:
    def test_planted_factor_is_significant_noise_is_not(self):
        ret = _frame(seed=10)
        noise = _frame(seed=11, scale=1.0)
        # 'good' is a noisy copy of the return -> high rank IC with variation
        good = ret + 0.1 * noise
        results = evaluate_factors(
            {"good": good, "noise": noise}, ret, alpha=0.05, min_count=20
        )
        by_id = {r.alpha_id: r for r in results}
        assert by_id["good"].significant
        assert not by_id["noise"].significant
        assert abs(by_id["good"].ic_mean) > abs(by_id["noise"].ic_mean)
        assert by_id["good"].p_value < 0.05

    def test_sorted_by_absolute_ic(self):
        ret = _frame(seed=20)
        good = ret + 0.05 * _frame(seed=21, scale=1.0)
        noise = _frame(seed=22, scale=1.0)
        results = evaluate_factors({"good": good, "noise": noise}, ret, min_count=20)
        assert results[0].alpha_id == "good"

    def test_low_count_not_marked_significant(self):
        ret = _frame(n_dates=10, seed=30)
        good = ret + 0.1 * _frame(n_dates=10, seed=31, scale=1.0)
        results = evaluate_factors({"good": good}, ret, min_count=20)
        assert results[0].significant is False
