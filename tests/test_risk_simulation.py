"""Offline research risk-engine tests."""

import numpy as np
import pandas as pd
import pytest

from arthaai.research.risk_simulation import RiskSimulationEngine


def test_factor_regression_recovers_known_beta():
    pytest.importorskip("statsmodels")
    factor = pd.Series(np.linspace(-0.03, 0.03, 100), name="market")
    asset = 0.002 + 1.7 * factor
    result = RiskSimulationEngine.calculate_asset_beta(
        asset, pd.DataFrame({"market": factor})
    )

    assert result["alpha"] == pytest.approx(0.002)
    assert result["betas"]["market"] == pytest.approx(1.7)
    assert result["r_squared"] == pytest.approx(1.0)
    assert result["observations"] == 100


def test_monte_carlo_is_reproducible_and_reports_positive_loss_tail():
    arguments = ([0.6, 0.4], [[0.04, 0.01], [0.01, 0.09]], [0.01, 0.02])
    first = RiskSimulationEngine(seed=7).run_monte_carlo_portfolio(*arguments, simulations=5000)
    second = RiskSimulationEngine(seed=7).run_monte_carlo_portfolio(*arguments, simulations=5000)

    assert np.array_equal(first["simulated_returns"], second["simulated_returns"])
    assert first["var_95"] >= 0.0
    assert first["expected_shortfall_95"] >= first["var_95"]
    assert len(first["simulated_returns"]) == 5000


@pytest.mark.parametrize(
    "weights,covariance,means,match",
    [
        ([1.0], [[1.0, 0.0], [0.0, 1.0]], [0.0], "dimensions"),
        ([1.0, 1.0], [[1.0, 2.0], [0.0, 1.0]], [0.0, 0.0], "symmetric"),
        ([1.0, 1.0], [[1.0, 2.0], [2.0, 1.0]], [0.0, 0.0], "positive semidefinite"),
    ],
)
def test_monte_carlo_rejects_invalid_inputs(weights, covariance, means, match):
    with pytest.raises(ValueError, match=match):
        RiskSimulationEngine().run_monte_carlo_portfolio(weights, covariance, means)