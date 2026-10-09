"""Deterministic risk metrics — VaR, Expected Shortfall, stress tests (ARTHA-310)."""

import pandas as pd
import pytest

from arthaai.agents import asset_manager as am
from arthaai.agents import risk


class TestHistorical:
    def test_var_is_the_loss_quantile(self):
        # 6 worst returns of 100 sit at the 5% quantile -> VaR = 0.10
        returns = pd.Series([-0.10] * 6 + [0.01] * 94)
        assert risk.historical_var(returns, 0.95) == pytest.approx(0.10)

    def test_expected_shortfall_at_least_var(self):
        returns = pd.Series([-0.20, -0.10, -0.05] + [0.01] * 17)
        var = risk.historical_var(returns, 0.95)
        es = risk.historical_expected_shortfall(returns, 0.95)
        assert es >= var

    def test_no_loss_returns_zero(self):
        assert risk.historical_var(pd.Series([0.01, 0.02, 0.03]), 0.95) == 0.0

    def test_nan_is_dropped(self):
        returns = pd.Series([float("nan")] + [-0.10] * 6 + [0.01] * 94)
        assert risk.historical_var(returns, 0.95) == pytest.approx(0.10)

    def test_empty_series_is_zero(self):
        assert risk.historical_var(pd.Series([], dtype="float64")) == 0.0


class TestParametric:
    def test_var_matches_normal_quantile(self):
        # mu=0, sigma=0.20 -> 1.6449 * 0.20
        assert risk.parametric_var(0.0, 0.20, 0.95) == pytest.approx(0.32897, abs=1e-4)

    def test_expected_shortfall_exceeds_var(self):
        var = risk.parametric_var(0.05, 0.20, 0.95)
        es = risk.parametric_expected_shortfall(0.05, 0.20, 0.95)
        assert es > var

    def test_zero_sigma_is_zero(self):
        assert risk.parametric_var(0.05, 0.0) == 0.0
        assert risk.parametric_expected_shortfall(0.05, 0.0) == 0.0

    def test_positive_drift_reduces_var(self):
        assert risk.parametric_var(0.10, 0.20) < risk.parametric_var(0.0, 0.20)


class TestSizingReportsRisk:
    def test_var_and_es_populated_when_sigma_present(self):
        quant = {"mu": 0.10, "variance": 0.04, "sigma": 0.20, "win_prob": 0.55, "win_loss_ratio": 1.1}
        alloc = am.size(quant)
        assert alloc.var_95 is not None
        assert alloc.expected_shortfall_95 is not None
        assert alloc.expected_shortfall_95 >= alloc.var_95 >= 0.0
        assert "VaR" in alloc.rationale

    def test_var_none_without_sigma(self):
        alloc = am.size({"mu": 0.10, "variance": 0.04, "win_prob": 0.55, "win_loss_ratio": 1.1})
        assert alloc.var_95 is None
        assert alloc.expected_shortfall_95 is None

    def test_risk_does_not_change_sizing(self):
        base = {"mu": 0.10, "variance": 0.04, "win_prob": 0.55, "win_loss_ratio": 1.1}
        with_sigma = dict(base, sigma=0.20)
        assert am.size(base).final_fraction == am.size(with_sigma).final_fraction