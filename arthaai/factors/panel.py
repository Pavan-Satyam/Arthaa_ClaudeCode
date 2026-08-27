"""Price panel construction — convert TimescaleDB OHLCV to the factor panel format.

The factor engine expects a ``dict[str, pd.DataFrame]`` where keys are column
names ("open", "high", "low", "close", "volume") and each DataFrame is **wide**
(index=dates, columns=symbols). This module builds that panel from per-symbol
OHLCV DataFrames loaded from TimescaleDB.

Usage::

    from arthaai.factors.panel import build_panel
    panel = build_panel({"GLD": gld_df, "SLV": slv_df})
    factor_scores = registry.compute("alpha101_001", panel)
"""

from __future__ import annotations

import pandas as pd


def build_panel(
    data_map: dict[str, pd.DataFrame],
    extra_columns: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Convert per-symbol OHLCV DataFrames to a wide panel dict.

    Args:
        data_map: ``{symbol: DataFrame}`` where each DataFrame has columns
            ``ts, open, high, low, close, volume`` and a DatetimeIndex (or ``ts``
            column that will be set as index).
        extra_columns: Optional additional columns to include (e.g. ``["vwap", "amount"]``).

    Returns:
        ``{"open": wide_df, "high": wide_df, ...}`` where each wide_df has
        index=dates, columns=symbols.
    """
    columns = ["open", "high", "low", "close", "volume"]
    if extra_columns:
        columns = columns + [c for c in extra_columns if c not in columns]

    # Normalize each symbol's DataFrame
    normalized: dict[str, pd.DataFrame] = {}
    for symbol, df in data_map.items():
        d = df.copy()
        if "ts" in d.columns:
            d = d.set_index("ts")
        d.index = pd.to_datetime(d.index, utc=True, errors="coerce")
        d = d[~d.index.isna()]
        d = d.sort_index()
        normalized[symbol] = d

    # Build unified date index
    all_indices = [d.index for d in normalized.values()]
    if not all_indices:
        return {}
    all_dates = pd.DatetimeIndex(sorted(set().union(*all_indices)))
    # Normalize timezone — some indices may already be tz-aware
    if all_dates.tz is None:
        all_dates = all_dates.tz_localize("UTC")

    # Build wide panels for each column
    panel: dict[str, pd.DataFrame] = {}
    for col in columns:
        col_data: dict[str, pd.Series] = {}
        for symbol, df in normalized.items():
            if col in df.columns:
                col_data[symbol] = df[col]
        if col_data:
            panel[col] = pd.DataFrame(col_data).reindex(all_dates)

    # Compute returns if close is available
    if "close" in panel:
        panel["returns"] = panel["close"].pct_change(fill_method=None)

    return panel


def build_panel_from_symbols(
    symbols: list[str],
    limit: int = 1000,
) -> dict[str, pd.DataFrame]:
    """Load OHLCV for multiple symbols from TimescaleDB and build a panel.

    Args:
        symbols: List of ticker symbols to load.
        limit: Max bars per symbol.

    Returns:
        Wide panel dict ready for factor computation.
    """
    from arthaai.db import timescale

    data_map: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        df = timescale.load_ohlcv(symbol, limit=limit)
        if not df.empty:
            data_map[symbol] = df

    if not data_map:
        return {}

    return build_panel(data_map)


def compute_forward_returns(
    panel: dict[str, pd.DataFrame],
    horizon: int = 1,
) -> pd.DataFrame:
    """Compute forward returns for IC evaluation.

    Args:
        panel: Wide panel dict (must contain "close").
        horizon: Forward return horizon in bars (default 1 = next-day return).

    Returns:
        Wide DataFrame of forward returns (index=dates, columns=symbols).
    """
    if "close" not in panel:
        return pd.DataFrame()
    close = panel["close"]
    # Forward return: return at bar t is close[t+horizon] / close[t] - 1
    # Shift by -horizon so row t contains the return realized horizon bars ahead
    fwd = close.shift(-horizon) / close - 1
    return fwd
