"""Intermarket risk-regime signals (pre-registered E3 candidates).

A different information axis from own-price signals: the market-wide risk state,
derived from a fixed basket that is already in the frozen universe.

- ``regime``: long every symbol on risk-on days, flat on risk-off days (pure
  market timing). Risk-on = SPY above its trailing ``trend_window`` mean AND the
  credit ratio (HYG/LQD) up over ``credit_window`` bars.
- ``regime_tsmom``: the ``regime`` gate applied to each symbol's own time-series
  momentum (own-price signal AND market regime).

All inputs are daily, causal, non-revised prices already in TimescaleDB, so the
signals are point-in-time safe and need no external keys.
"""

from __future__ import annotations

import pandas as pd

REGIME_BASKET = ("SPY", "HYG", "LQD")


def risk_regime(
    close: pd.DataFrame,
    *,
    trend_window: int = 200,
    credit_window: int = 63,
) -> pd.Series:
    """Market-wide risk-on indicator (1.0 risk-on, 0.0 risk-off) per date."""
    missing = [sym for sym in REGIME_BASKET if sym not in close.columns]
    if missing:
        raise ValueError(f"regime basket missing from panel: {missing}")
    spy = close["SPY"]
    risk_on = spy > spy.rolling(trend_window).mean()
    credit = close["HYG"] / close["LQD"]
    credit_on = credit.pct_change(credit_window, fill_method=None) > 0
    return (risk_on & credit_on).astype(float)


def regime_signal_map(
    symbols: list[str],
    *,
    kind: str = "regime",
    lookback: int = 126,
    trend_window: int = 200,
    credit_window: int = 63,
    limit: int = 520,
) -> dict[str, pd.Series]:
    """Build per-symbol causal regime signal series from a universe panel."""
    if kind not in ("regime", "regime_tsmom"):
        raise ValueError(f"unknown regime kind: {kind!r}")

    from arthaai.factors.panel import build_panel_from_symbols

    panel = build_panel_from_symbols(list(symbols), limit=limit)
    close = panel.get("close")
    if close is None or close.empty:
        return {}
    regime = risk_regime(close, trend_window=trend_window, credit_window=credit_window)

    if kind == "regime":
        wide = pd.DataFrame({sym: regime for sym in close.columns})
    else:
        from arthaai.factors.momentum import time_series_momentum_signal

        tsmom = time_series_momentum_signal(close, lookback)
        wide = tsmom.mul(regime, axis=0)

    return {str(sym): wide[sym].dropna() for sym in wide.columns}
