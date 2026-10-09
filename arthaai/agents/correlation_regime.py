"""Correlation Regime agent — risk-off fusion detection (Tier 2, ARTHA-215).

Diversification is regime-dependent: in a genuine risk-off event, correlations
across assets spike toward 1 and "diversified" books behave like one position.
This agent measures the average pairwise correlation of a universe over a
rolling window and labels the regime, so the Master LLM can reason about whether
apparent diversification is real.

Deterministic: correlations are computed here, never by the LLM. Degrades to
``available: False`` when there is not enough overlapping history.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from arthaai.db import timescale
from arthaai.security import AgentIdentity, authorize_tool

IDENTITY = AgentIdentity("correlation_regime", "spiffe://arthaai/agent/correlation_regime")

# Default cross-asset universe: commodities, energy, equity — the blueprint's
# "risk-off fusion" set.
DEFAULT_UNIVERSE = ["GLD", "SLV", "USO", "XOM", "AAPL"]

# Average pairwise correlation boundaries. At/above HIGH the book is effectively
# one position (risk-off fusion); at/below LOW it is genuinely diversified.
HIGH_CORRELATION = 0.70
LOW_CORRELATION = 0.30


def _returns(df: pd.DataFrame) -> pd.Series:
    return df["close"].pct_change(fill_method=None).dropna()


def _mean_pairwise_correlation(corr: pd.DataFrame) -> float | None:
    """Mean of the upper-triangle (distinct pairs) of a correlation matrix."""
    n = corr.shape[0]
    values = [
        float(corr.iloc[i, j])
        for i in range(n)
        for j in range(i + 1, n)
        if corr.iloc[i, j] == corr.iloc[i, j]  # not NaN
    ]
    return float(np.mean(values)) if values else None


def assess(
    returns_map: dict[str, pd.Series],
    *,
    window: int = 60,
    high: float = HIGH_CORRELATION,
    low: float = LOW_CORRELATION,
) -> dict:
    """Label the correlation regime from a map of per-asset return series."""
    if len(returns_map) < 2:
        return {"available": False, "reason": "need at least two assets for a correlation regime"}

    frame = pd.DataFrame(returns_map).tail(window).dropna(how="all")
    frame = frame.dropna(axis=1, how="all")
    if frame.shape[1] < 2 or len(frame) < 2:
        return {"available": False, "reason": "insufficient overlapping history"}

    corr = frame.corr()
    avg = _mean_pairwise_correlation(corr)
    if avg is None:
        return {"available": False, "reason": "undefined pairwise correlations"}

    if avg >= high:
        regime = "risk_off"
    elif avg <= low:
        regime = "diversified"
    else:
        regime = "mixed"

    return {
        "available": True,
        "regime": regime,
        "avg_correlation": round(avg, 4),
        "window": window,
        "observations": int(len(frame)),
        "assets": [str(c) for c in corr.columns],
    }


def run(symbol: str, universe: list[str] | None = None, window: int = 60) -> dict:
    """Load the universe and label its current correlation regime."""
    authorize_tool(IDENTITY, "correlation_regime")
    symbol = symbol.upper()
    syms = [symbol] + [s.upper() for s in (universe or DEFAULT_UNIVERSE) if s.upper() != symbol]

    returns_map: dict[str, pd.Series] = {}
    for sym in syms:
        df = timescale.load_ohlcv(sym, limit=max(window * 3, 200))
        if not df.empty:
            returns_map[sym] = _returns(df)

    out = assess(returns_map, window=window)
    out["symbol"] = symbol
    return out