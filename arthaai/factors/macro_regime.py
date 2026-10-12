"""Macro term-spread regime signals (pre-registered E3 candidates).

A market-wide macro axis: the US treasury 10y-2y term spread (FRED ``T10Y2Y``),
free and keyless. An upward curve (spread > 0) is treated as an expansion/risk-on
regime. The series is market data and non-revised, so it is point-in-time safe.

- ``macro``: long every symbol on risk-on days (spread > 0), flat otherwise.
- ``macro_tsmom``: the macro gate applied to each symbol's own ``tsmom``.
"""

from __future__ import annotations

import pandas as pd

_TERM_SPREAD_SERIES = "T10Y2Y"


def macro_regime(
    dates,
    *,
    term_spread: pd.Series | None = None,
) -> pd.Series:
    """Risk-on indicator (1.0/0.0) aligned to ``dates``; spread > 0 = risk-on."""
    index = pd.DatetimeIndex(dates)
    if term_spread is None:
        from arthaai.data.macro_series import fred_series

        term_spread = fred_series(_TERM_SPREAD_SERIES)
    if term_spread is None or term_spread.empty:
        return pd.Series(float("nan"), index=index)
    aligned = (
        term_spread.reindex(index.union(term_spread.index))
        .sort_index()
        .ffill()
        .reindex(index)
    )
    return (aligned > 0).astype(float).where(aligned.notna())


def macro_signal_map(
    symbols: list[str],
    *,
    kind: str = "macro",
    lookback: int = 126,
    limit: int = 520,
    term_spread: pd.Series | None = None,
) -> dict[str, pd.Series]:
    """Build per-symbol causal macro-regime signal series from a universe panel."""
    if kind not in ("macro", "macro_tsmom"):
        raise ValueError(f"unknown macro kind: {kind!r}")

    from arthaai.factors.panel import build_panel_from_symbols

    panel = build_panel_from_symbols(list(symbols), limit=limit)
    close = panel.get("close")
    if close is None or close.empty:
        return {}
    regime = macro_regime(close.index, term_spread=term_spread)

    if kind == "macro":
        wide = pd.DataFrame({sym: regime for sym in close.columns})
    else:
        from arthaai.factors.momentum import time_series_momentum_signal

        tsmom = time_series_momentum_signal(close, lookback)
        wide = tsmom.mul(regime, axis=0)

    return {str(sym): wide[sym].dropna() for sym in wide.columns}
