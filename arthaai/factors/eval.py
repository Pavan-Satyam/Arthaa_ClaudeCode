"""Factor evaluation — IC (Information Coefficient) and factor ranking.

Computes Spearman rank correlation between factor values and forward returns,
then categorises factors as alive / reversed / dead based on IC statistics.

Multiple-testing control is mandatory here: evaluating hundreds of factors and
keeping the best is how false discoveries get promoted. ``evaluate_factors``
applies Benjamini-Hochberg FDR control across the family of factors.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

_MIN_VALID_PER_DATE = 5


def compute_ic_series(
    factor_df: pd.DataFrame, return_df: pd.DataFrame, step: int = 1
) -> pd.Series:
    """Compute daily Spearman rank correlation (IC) between factor values and returns.

    Args:
        factor_df: Factor values; index=date, columns=codes.
        return_df: Returns; index=date, columns=codes.
        step: Subsample the IC series every ``step`` dates. Use ``step=horizon``
            to suppress the autocorrelation from overlapping forward windows
            (an embargo against inflating the t-statistic).

    Returns:
        IC series indexed by date.
    """
    common_dates = factor_df.index.intersection(return_df.index)
    common_codes = factor_df.columns.intersection(return_df.columns)
    if len(common_dates) == 0 or len(common_codes) == 0:
        return pd.Series(dtype=float)

    factor_df = factor_df.loc[common_dates, common_codes]
    return_df = return_df.loc[common_dates, common_codes]

    pair_mask = factor_df.notna() & return_df.notna()
    n_valid = pair_mask.sum(axis=1)

    factor_aligned = factor_df.where(pair_mask)
    return_aligned = return_df.where(pair_mask)

    factor_ranks = factor_aligned.rank(axis=1, method="average")
    return_ranks = return_aligned.rank(axis=1, method="average")
    ic = factor_ranks.corrwith(return_ranks, axis=1, method="pearson")

    ic = ic[n_valid >= _MIN_VALID_PER_DATE]
    ic = ic.dropna()
    if step > 1:
        ic = ic.iloc[::step]
    if ic.empty:
        return pd.Series(dtype=float)
    return ic.astype(float)


def t_to_p(t_stat: float) -> float:
    """Two-sided p-value for a t-statistic (normal approximation)."""
    return math.erfc(abs(t_stat) / math.sqrt(2.0))


def benjamini_hochberg(p_values: list[float], alpha: float = 0.05) -> list[bool]:
    """Benjamini-Hochberg step-up FDR control.

    Returns a boolean mask (aligned to ``p_values``) marking discoveries. This is
    the guard that stops "best of 445 factors" from being mistaken for edge.
    """
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    k_max = 0
    for rank, idx in enumerate(order, start=1):
        if p_values[idx] <= alpha * rank / m:
            k_max = rank
    accepted = [False] * m
    for rank, idx in enumerate(order, start=1):
        if rank <= k_max:
            accepted[idx] = True
    return accepted


@dataclass
class FactorICResult:
    alpha_id: str
    ic_mean: float
    ic_std: float
    ir: float
    t_stat: float
    p_value: float
    ic_count: int
    ic_positive_ratio: float
    category: str
    significant: bool = False


def evaluate_factors(
    factor_map: dict[str, pd.DataFrame],
    return_df: pd.DataFrame,
    *,
    alpha: float = 0.05,
    min_count: int = 20,
    horizon: int = 1,
) -> list[FactorICResult]:
    """Evaluate many factors' rank-IC with Benjamini-Hochberg FDR control.

    Args:
        factor_map: ``{alpha_id: factor_df}`` (index=date, columns=symbols).
        return_df: Forward returns, same shape/index as the factor frames.
        alpha: FDR level for the BH procedure.
        min_count: Minimum IC observations for a factor to be testable.
        horizon: Forward-return horizon; also used as the IC subsample step so
            overlapping windows don't inflate t-statistics.

    Returns:
        Results sorted by |IC mean| (descending). ``significant`` is True only
        for factors surviving BH at ``alpha``.
    """
    results: list[FactorICResult] = []
    for alpha_id, factor_df in factor_map.items():
        ic = compute_ic_series(factor_df, return_df, step=max(1, horizon))
        stats = compute_ic_stats(ic)
        t = float(stats["t_stat"])
        results.append(
            FactorICResult(
                alpha_id=alpha_id,
                ic_mean=stats["ic_mean"],
                ic_std=stats["ic_std"],
                ir=stats["ir"],
                t_stat=t,
                p_value=t_to_p(t),
                ic_count=stats["ic_count"],
                ic_positive_ratio=stats["ic_positive_ratio"],
                category=categorise(
                    stats["ic_mean"], stats["ic_positive_ratio"], stats["ic_std"], stats["ic_count"]
                ),
            )
        )

    tested = [r for r in results if r.ic_count >= min_count]
    mask = benjamini_hochberg([r.p_value for r in tested], alpha=alpha)
    for r, sig in zip(tested, mask):
        r.significant = sig

    return sorted(results, key=lambda r: abs(r.ic_mean), reverse=True)


def compute_ic_stats(ic: pd.Series) -> dict[str, float]:
    """Compute summary statistics from an IC series."""
    if ic.empty:
        return {"ic_mean": 0.0, "ic_std": 0.0, "ir": 0.0, "ic_positive_ratio": 0.0, "ic_count": 0, "t_stat": 0.0}
    ic_mean = float(ic.mean())
    ic_std = float(ic.std())
    ir = ic_mean / ic_std if ic_std > 0 else 0.0
    n = len(ic)
    t = ic_mean / (ic_std / math.sqrt(n)) if ic_std > 0 and n > 0 else 0.0
    return {
        "ic_mean": round(ic_mean, 6),
        "ic_std": round(ic_std, 6),
        "ir": round(ir, 4),
        "ic_positive_ratio": round(float((ic > 0).mean()), 4),
        "ic_count": int(n),
        "t_stat": round(t, 4),
    }


def categorise(ic_mean: float, ic_positive_ratio: float, ic_std: float, ic_count: int) -> str:
    """Bucket a factor into alive / reversed / dead.

    - ``alive``    : ic_mean > 0.02 and ic_positive_ratio >= 0.55 and |t| > 2
    - ``reversed`` : ic_mean < -0.02 and |t| > 2
    - ``dead``     : everything else
    """
    n = ic_count
    std = ic_std
    t = ic_mean / (std / math.sqrt(n)) if (n > 0 and std > 0 and math.isfinite(std)) else 0.0
    if ic_mean > 0.02 and ic_positive_ratio >= 0.55 and abs(t) > 2:
        return "alive"
    if ic_mean < -0.02 and abs(t) > 2:
        return "reversed"
    return "dead"


def compute_group_equity(
    factor_df: pd.DataFrame, return_df: pd.DataFrame, n_groups: int
) -> pd.DataFrame:
    """Layered backtest: rank by factor value daily, hold equal-weight, compute NAV.

    Args:
        factor_df: Factor values; index=date, columns=codes.
        return_df: Returns; index=date, columns=codes.
        n_groups: Number of quantile groups.

    Returns:
        DataFrame with index=date and columns Group_1 ... Group_N holding cumulative NAV.
    """
    if n_groups < 1:
        raise ValueError(f"n_groups must be >= 1, got {n_groups}")

    common_dates = sorted(factor_df.index.intersection(return_df.index))
    common_codes = factor_df.columns.intersection(return_df.columns)
    if len(common_dates) == 0 or len(common_codes) == 0:
        return pd.DataFrame()

    factor_df = factor_df.loc[common_dates, common_codes]
    return_df = return_df.loc[common_dates, common_codes]

    group_returns: dict[str, list[float]] = {f"Group_{i+1}": [] for i in range(n_groups)}
    valid_dates = []

    for date in common_dates:
        f = factor_df.loc[date].dropna()
        r = return_df.loc[date].dropna()
        shared = f.index.intersection(r.index)
        if len(shared) < n_groups:
            continue
        valid_dates.append(date)
        ranked = f[shared].rank(method="first")
        bins = pd.qcut(ranked, n_groups, labels=False, duplicates="drop")
        if bins.nunique() < n_groups:
            bins = pd.cut(ranked, n_groups, labels=False)
        for g in range(n_groups):
            members = bins[bins == g].index
            if len(members) > 0:
                group_returns[f"Group_{g+1}"].append(r[members].mean())
            else:
                group_returns[f"Group_{g+1}"].append(0.0)

    if not valid_dates:
        return pd.DataFrame()

    ret_df = pd.DataFrame(group_returns, index=valid_dates)
    equity_df = (1 + ret_df).cumprod()
    return equity_df
