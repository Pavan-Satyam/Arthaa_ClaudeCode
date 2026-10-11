"""Factor regression and Monte Carlo analysis for offline portfolio research."""

from __future__ import annotations

from typing import TypedDict

import numpy as np
import pandas as pd


class FactorRegressionResult(TypedDict):
    alpha: float
    betas: dict[str, float]
    r_squared: float
    observations: int


class MonteCarloResult(TypedDict):
    simulated_returns: np.ndarray
    mean_return: float
    volatility: float
    var_95: float
    expected_shortfall_95: float


class RiskSimulationEngine:
    """Run offline factor regressions and portfolio return simulations."""

    def __init__(self, seed: int | None = None) -> None:
        self._seed = seed

    @staticmethod
    def calculate_asset_beta(
        asset_returns: pd.Series,
        factor_returns: pd.DataFrame,
    ) -> FactorRegressionResult:
        """Fit OLS of asset returns on aligned factor returns and an intercept."""
        if not isinstance(asset_returns, pd.Series) or not isinstance(factor_returns, pd.DataFrame):
            raise TypeError("asset_returns must be a Series and factor_returns a DataFrame")
        if factor_returns.empty or factor_returns.shape[1] == 0:
            raise ValueError("factor_returns must contain at least one factor")

        try:
            import statsmodels.api as sm
        except ImportError as exc:
            raise RuntimeError(
                "OLS regression requires `pip install -e '.[research]'`."
            ) from exc

        joined = pd.concat(
            [asset_returns.rename("asset"), factor_returns], axis=1, join="inner"
        ).replace([np.inf, -np.inf], np.nan).dropna()
        if len(joined) <= factor_returns.shape[1]:
            raise ValueError("insufficient complete observations for factor regression")

        design = sm.add_constant(joined[factor_returns.columns], has_constant="add")
        fitted = sm.OLS(joined["asset"], design, missing="raise").fit()
        return FactorRegressionResult(
            alpha=float(fitted.params["const"]),
            betas={name: float(fitted.params[name]) for name in factor_returns.columns},
            r_squared=float(fitted.rsquared),
            observations=int(fitted.nobs),
        )

    def run_monte_carlo_portfolio(
        self,
        weights: np.ndarray | list[float],
        cov_matrix: np.ndarray | list[list[float]],
        expected_returns: np.ndarray | list[float],
        simulations: int = 10_000,
    ) -> MonteCarloResult:
        """Sample multivariate portfolio returns and report 95% tail loss metrics.

        Inputs describe one common return horizon. VaR and expected shortfall are
        positive loss magnitudes derived from the simulated lower tail.
        """
        weight_vector = np.asarray(weights, dtype=float)
        mean_vector = np.asarray(expected_returns, dtype=float)
        covariance = np.asarray(cov_matrix, dtype=float)
        if weight_vector.ndim != 1 or mean_vector.ndim != 1:
            raise ValueError("weights and expected_returns must be one-dimensional")
        if covariance.ndim != 2 or covariance.shape[0] != covariance.shape[1]:
            raise ValueError("cov_matrix must be square")
        asset_count = weight_vector.size
        if asset_count == 0 or mean_vector.size != asset_count or covariance.shape != (asset_count, asset_count):
            raise ValueError("weights, expected_returns, and cov_matrix dimensions must match")
        if simulations < 1:
            raise ValueError("simulations must be at least 1")
        if not (
            np.isfinite(weight_vector).all()
            and np.isfinite(mean_vector).all()
            and np.isfinite(covariance).all()
        ):
            raise ValueError("simulation inputs must be finite")
        if not np.allclose(covariance, covariance.T, rtol=1e-8, atol=1e-12):
            raise ValueError("cov_matrix must be symmetric")
        if np.linalg.eigvalsh(covariance).min() < -1e-10:
            raise ValueError("cov_matrix must be positive semidefinite")

        rng = np.random.default_rng(self._seed)
        asset_draws = rng.multivariate_normal(
            mean_vector, covariance, size=simulations, check_valid="raise"
        )
        portfolio_returns = asset_draws @ weight_vector
        lower_tail_cutoff = float(np.quantile(portfolio_returns, 0.05))
        tail = portfolio_returns[portfolio_returns <= lower_tail_cutoff]
        return MonteCarloResult(
            simulated_returns=portfolio_returns,
            mean_return=float(portfolio_returns.mean()),
            volatility=float(portfolio_returns.std(ddof=1)) if simulations > 1 else 0.0,
            var_95=max(0.0, -lower_tail_cutoff),
            expected_shortfall_95=max(0.0, -float(tail.mean())),
        )