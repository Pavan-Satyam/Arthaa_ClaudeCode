"""Cross-sectional factor composite — rank a universe, not one asset.

The single-asset factor path (``quant_agent._evaluate_factors``) reads one
asset's last factor value. That cannot tell a *cross-sectional* factor (one
whose meaning is "this asset ranks high vs its peers") from a time-series one,
and the 42 Qlib cross-sectional alphas are degenerate without a universe.

This module standardises each factor **across symbols on each date** (z-score),
averages the standardised factors into a composite score per asset per date, and
ranks the universe. Standardising cross-sectionally removes each factor's
arbitrary scale and makes factors comparable before they are combined.

Everything is causal: a date's score uses only that date's cross-section and the
factor series itself is computed from bars ``<= t``, so the composite is safe to
feed a walk-forward backtest.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from arthaai.factors.base import zscore
from arthaai.factors.eval import compute_ic_series
from arthaai.factors.panel import compute_forward_returns
from arthaai.factors.registry import get_default_registry

# Same a-priori set the single-asset sizing signal uses, so live and composite
# paths share a factor family.
DEFAULT_COMPOSITE_FACTOR_IDS = [
    "alpha101_024",
    "alpha101_009",
    "alpha101_012",
    "alpha101_023",
    "alpha101_031",
]


def cross_sectional_zscore(factor_df: pd.DataFrame) -> pd.DataFrame:
    """Standardise a factor across symbols on each date (row-wise z-score).

    Delegates to the canonical ``factors.base.zscore`` operator (sample std) so
    the composite standardises factors identically to every other consumer.
    """
    return zscore(factor_df)


def composite_scores(
    factor_map: dict[str, pd.DataFrame],
    *,
    min_assets: int = 2,
) -> pd.DataFrame:
    """Average cross-sectional z-scores of several factors into one composite.

    Args:
        factor_map: ``{alpha_id: factor_df}`` where each frame is wide
            (index=date, columns=symbols).
        min_assets: A date must have at least this many assets in a factor's
            cross-section to contribute; thinner dates are dropped per factor.

    Returns:
        Wide composite (index=date, columns=symbols); NaN where no factor had a
        usable value. Higher = more attractive on the combined factors.
    """
    standardized: list[pd.DataFrame] = []
    for factor_df in factor_map.values():
        if factor_df is None or factor_df.empty:
            continue
        z = cross_sectional_zscore(factor_df)
        if min_assets > 1:
            z = z.where(z.notna().sum(axis=1) >= min_assets)
        standardized.append(z)
    if not standardized:
        return pd.DataFrame()

    stacked = pd.concat(standardized, keys=range(len(standardized)))
    # level 0 = factor index, level 1 = date -> mean across factors per date.
    return stacked.groupby(level=1).mean()


def composite_from_panel(
    panel: dict[str, pd.DataFrame],
    factor_ids: list[str] | None = None,
    registry=None,
) -> pd.DataFrame:
    """Compute the cross-sectional composite directly from an OHLCV panel."""
    if not panel or "close" not in panel:
        return pd.DataFrame()
    reg = registry or get_default_registry()
    ids = factor_ids or DEFAULT_COMPOSITE_FACTOR_IDS
    factor_map: dict[str, pd.DataFrame] = {}
    for fid in ids:
        try:
            df = reg.compute(fid, panel)
        except Exception:  # noqa: BLE001 - a bad factor must not kill the composite
            continue
        if df is not None and not df.empty and df.shape[1] >= 1:
            factor_map[fid] = df
    return composite_scores(factor_map)


def ic_weighted_composite(
    panel: dict[str, pd.DataFrame],
    factor_ids: list[str] | None = None,
    registry=None,
    *,
    horizon: int = 1,
    min_ic_obs: int = 20,
    embargo: int = 1,
) -> pd.DataFrame:
    """IC-weighted cross-sectional composite (the E3 candidate signal).

    Each factor's cross-sectional z-score is weighted by the **expanding mean of
    its historical rank-IC** (against forward returns), floored at zero. The IC
    series is lagged by ``horizon + embargo - 1`` bars so a date's weight never
    uses the forward return it will be graded on — the embargo that keeps the
    weighting look-ahead-free. Until a factor has ``min_ic_obs`` IC observations
    its weight is zero; dates where no factor has a positive weight fall back to
    the equal-weight composite.

    Returns a wide composite (index=date, columns=symbols), higher = more
    attractive on the historically-informative factors.
    """
    if not panel or "close" not in panel:
        return pd.DataFrame()
    reg = registry or get_default_registry()
    ids = factor_ids or DEFAULT_COMPOSITE_FACTOR_IDS

    zs: dict[str, pd.DataFrame] = {}
    for fid in ids:
        try:
            factor_df = reg.compute(fid, panel)
        except Exception:  # noqa: BLE001
            continue
        if factor_df is not None and not factor_df.empty:
            zs[fid] = cross_sectional_zscore(factor_df)
    if not zs:
        return pd.DataFrame()

    forward = compute_forward_returns(panel, horizon=horizon)
    if forward.empty:
        return composite_scores(zs)

    lag = max(0, horizon + embargo - 1)
    weights: dict[str, pd.Series] = {}
    for fid, z in zs.items():
        ic = compute_ic_series(z, forward, step=1)
        if ic.empty:
            weights[fid] = pd.Series(0.0, index=z.index)
        else:
            w = ic.expanding(min_periods=min_ic_obs).mean().shift(lag).clip(lower=0.0)
            weights[fid] = w.reindex(z.index)

    index = zs[list(zs)[0]].index
    for z in zs.values():
        index = index.union(z.index)
    columns = zs[list(zs)[0]].columns
    for z in zs.values():
        columns = columns.union(z.columns)

    numerator = pd.DataFrame(0.0, index=index, columns=columns)
    denominator = pd.DataFrame(0.0, index=index, columns=columns)
    for fid, z in zs.items():
        zz = z.reindex(index=index, columns=columns)
        ww = weights[fid].reindex(index).to_numpy()[:, None]
        mask = zz.notna().to_numpy()
        numerator += np.where(mask, ww * zz.to_numpy(), 0.0)
        denominator += np.where(mask, ww, 0.0)

    equal_weight = pd.concat(
        [z.reindex(index=index, columns=columns) for z in zs.values()],
        keys=range(len(zs)),
    ).groupby(level=1).mean()

    composite = numerator.div(denominator.replace(0.0, np.nan))
    return composite.where(denominator > 0.0, equal_weight)


def per_symbol_signals(composite: pd.DataFrame) -> dict[str, pd.Series]:
    """Split a wide composite into per-symbol date-indexed signal series.

    Each returned series is causal (its value at date *t* uses only bars <= *t*)
    and can be fed to ``run_backtest(signal_series=...)``.
    """
    if composite is None or composite.empty:
        return {}
    return {str(sym): composite[sym].dropna() for sym in composite.columns}


def cross_sectional_signal_map(
    symbols: list[str],
    *,
    limit: int = 520,
    ic_weighted: bool = True,
    factor_ids: list[str] | None = None,
    registry=None,
) -> dict[str, pd.Series]:
    """Build per-symbol causal signal series from the universe cross-section.

    Loads the universe panel from TimescaleDB, computes the (IC-weighted)
    cross-sectional composite over that universe, and returns one date-indexed
    series per symbol. This is the bridge that lets the per-symbol E3 gate test a
    cross-sectional signal it could not otherwise see.
    """
    from arthaai.factors.panel import build_panel_from_symbols

    panel = build_panel_from_symbols(list(symbols), limit=limit)
    if not panel:
        return {}
    if ic_weighted:
        composite = ic_weighted_composite(panel, factor_ids, registry)
    else:
        composite = composite_from_panel(panel, factor_ids, registry)
    return per_symbol_signals(composite)


def rank_assets(composite: pd.DataFrame, date=None) -> pd.Series:
    """Rank symbols by composite score at ``date`` (default: last date).

    Returns a Series sorted best-first; ties broken by symbol name for
    determinism.
    """
    if composite.empty:
        return pd.Series(dtype=float)
    row = composite.iloc[-1] if date is None else composite.loc[date]
    row = row.dropna()
    return row.sort_values(ascending=False, kind="mergesort")