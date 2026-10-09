"""Deterministic risk metrics (Tier 3) — VaR / Expected Shortfall.

The quant layer computes every number; this module adds the tail-risk view the
oversight tier needs to reason about *how bad* a position can get, not just its
expected size. All functions are pure and look-ahead-safe: they only consume a
return series the caller has already sliced to the information available.

Two estimators are provided:

- **Historical** — the empirical loss quantile and the mean of the tail beyond
  it. Distribution-free; needs a decent sample. Used by the `portfolio` CLI to
  report the tail risk of the sized portfolio's return series.
- **Parametric (normal)** — closed form from ``mu``/``sigma``, used by the sizing
  layer where only annualised summary statistics exist.

VaR/ES are returned as **positive loss magnitudes** (fractions of notional), so
``0.03`` means "lose 3% or more". A zero means the estimator found no loss at the
requested confidence.
"""

from __future__ import annotations

from statistics import NormalDist

import pandas as pd


def _clean(returns) -> pd.Series:
    s = returns if isinstance(returns, pd.Series) else pd.Series(returns, dtype="float64")
    return s.dropna().astype(float)


def historical_var(returns, confidence: float = 0.95) -> float:
    """Empirical VaR: the loss at the ``1 - confidence`` return quantile."""
    r = _clean(returns)
    if r.empty:
        return 0.0
    q = float(r.quantile(1 - confidence))
    return max(0.0, -q)


def historical_expected_shortfall(returns, confidence: float = 0.95) -> float:
    """Mean loss conditional on being beyond the VaR threshold."""
    r = _clean(returns)
    if r.empty:
        return 0.0
    q = float(r.quantile(1 - confidence))
    tail = r[r <= q]
    if tail.empty:
        return max(0.0, -q)
    return max(0.0, -float(tail.mean()))


def parametric_var(mu: float, sigma: float, confidence: float = 0.95) -> float:
    """Normal VaR from an expected return ``mu`` and volatility ``sigma``."""
    if sigma <= 0:
        return 0.0
    z = NormalDist().inv_cdf(confidence)
    return max(0.0, z * sigma - mu)


def parametric_expected_shortfall(mu: float, sigma: float, confidence: float = 0.95) -> float:
    """Normal Expected Shortfall (a.k.a. CVaR) from ``mu`` and ``sigma``."""
    if sigma <= 0:
        return 0.0
    normal = NormalDist()
    z = normal.inv_cdf(confidence)
    tail_pdf = normal.pdf(z)
    return max(0.0, sigma * tail_pdf / (1 - confidence) - mu)