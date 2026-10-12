"""Classic momentum signal family (pre-registered E3 candidates).

Two textbook, low-parameter signals — deliberately not alpha-zoo combinations:

- ``tsmom``: time-series momentum. Long when an asset's own trailing ``lookback``
  return is positive, flat otherwise (Moskowitz/Ooi/Pedersen style, simplified).
- ``xsmom``: cross-sectional momentum. Each date, long the top ``top_quantile``
  of trailing ``lookback`` return across the universe, flat otherwise.

Both are causal: a date's signal uses only closes at or before that date, so they
are safe to feed a walk-forward backtest via ``run_backtest(signal_series=...)``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def trailing_return(close: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Trailing ``lookback``-day return per symbol (wide, index=date)."""
    if lookback < 1:
        raise ValueError("lookback must be >= 1")
    return close / close.shift(lookback) - 1.0


def time_series_momentum_signal(close: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """``+1`` where trailing return > 0, ``0`` otherwise; NaN where undefined."""
    tr = trailing_return(close, lookback)
    return (tr > 0).astype(float).where(tr.notna())


def cross_sectional_momentum_signal(
    close: pd.DataFrame,
    lookback: int,
    top_quantile: float = 0.30,
) -> pd.DataFrame:
    """``+1`` for the top ``top_quantile`` of trailing return each date, else ``0``."""
    if not 0 < top_quantile <= 1:
        raise ValueError("top_quantile must be in (0, 1]")
    tr = trailing_return(close, lookback)
    ranks = tr.rank(axis=1, ascending=False, method="first")
    counts = tr.notna().sum(axis=1)
    keep = np.ceil(counts * top_quantile).clip(lower=1)
    selected = ranks.le(keep, axis=0).astype(float)
    return selected.where(tr.notna())


def momentum_signal_map(
    symbols: list[str],
    *,
    kind: str,
    lookback: int = 126,
    top_quantile: float = 0.30,
    limit: int = 520,
) -> dict[str, pd.Series]:
    """Build per-symbol causal momentum signal series from a universe panel.

    ``kind`` is ``"tsmom"`` or ``"xsmom"``. Returns ``{symbol: series}`` indexed by
    date, ready for ``run_backtest(signal_series=...)``.
    """
    if kind not in ("tsmom", "xsmom"):
        raise ValueError(f"unknown momentum kind: {kind!r}")

    from arthaai.factors.panel import build_panel_from_symbols

    panel = build_panel_from_symbols(list(symbols), limit=limit)
    close = panel.get("close")
    if close is None or close.empty:
        return {}
    if kind == "tsmom":
        wide = time_series_momentum_signal(close, lookback)
    else:
        wide = cross_sectional_momentum_signal(close, lookback, top_quantile)
    return {str(sym): wide[sym].dropna() for sym in wide.columns}
