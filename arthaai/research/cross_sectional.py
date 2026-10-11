"""Research-only walk-forward validation for cross-sectional factor portfolios."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from arthaai.backtest.engine import oos_windows
from arthaai.factors.composite import DEFAULT_COMPOSITE_FACTOR_IDS, ic_weighted_composite


@dataclass
class CrossSectionalWindow:
    """Descriptive metrics for one held-out window; never a promotion verdict."""

    start: str
    end: str
    observations: int
    complete_assets: int
    active_fraction: float
    total_return: float
    benchmark_return: float
    excess_return: float
    sharpe: float
    max_drawdown: float
    average_turnover: float
    benchmark_average_turnover: float
    cost_bps: float


@dataclass
class CrossSectionalResearchReport:
    """Research output deliberately has no ``qualified`` or promotion field."""

    signal: str
    benchmark: str
    windows: list[CrossSectionalWindow]
    skipped_windows: list[str]
    factor_ids: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "benchmark": self.benchmark,
            "windows": [asdict(window) for window in self.windows],
            "skipped_windows": list(self.skipped_windows),
            "factor_ids": list(self.factor_ids),
        }


def _max_drawdown(daily_returns: pd.Series) -> float:
    equity = (1.0 + daily_returns).cumprod()
    peak = equity.cummax()
    return float(((equity - peak) / peak).min()) if len(equity) else 0.0


def _drift_weights(weights: pd.Series, returns: pd.Series) -> pd.Series:
    """Update target weights after a return period, retaining cash weight."""
    asset_values = weights * (1.0 + returns)
    portfolio_value = float(1.0 - weights.sum() + asset_values.sum())
    if portfolio_value <= 0:
        return pd.Series(0.0, index=weights.index)
    return asset_values / portfolio_value


def _window_metrics(
    close: pd.DataFrame,
    scores: pd.DataFrame,
    *,
    lo: int,
    hi: int,
    top_quantile: float,
    cost_bps: float,
    min_assets: int,
) -> CrossSectionalWindow | None:
    dates = close.index
    if lo <= 0 or hi > len(dates) or hi - lo < 2:
        return None
    aligned_prices = close.ffill(limit=1)
    window_close = aligned_prices.iloc[lo - 1 : hi]
    complete = window_close.notna().all(axis=0)
    assets = list(close.columns[complete])
    if len(assets) < min_assets:
        return None

    window_close = window_close.loc[:, assets]
    window_scores = scores.reindex(index=dates, columns=assets)
    returns = window_close.pct_change(fill_method=None).iloc[1:]
    test_dates = dates[lo:hi]
    strategy_returns: list[float] = []
    turnovers: list[float] = []
    benchmark_net_returns: list[float] = []
    benchmark_turnovers: list[float] = []
    active_days = 0
    prior_weights = pd.Series(0.0, index=assets)
    benchmark_target = pd.Series(1.0 / len(assets), index=assets)
    benchmark_prior_weights = pd.Series(0.0, index=assets)

    for date_index, current_date in enumerate(test_dates, start=lo):
        decision_date = dates[date_index - 1]
        row = window_scores.loc[decision_date].dropna().sort_values(ascending=False, kind="mergesort")
        target_weights = pd.Series(0.0, index=assets)
        if len(row) >= min_assets:
            selection_count = max(1, int(np.ceil(len(row) * top_quantile)))
            selected = row.index[:selection_count]
            target_weights.loc[selected] = 1.0 / len(selected)
            active_days += 1

        turnover = float((target_weights - prior_weights).abs().sum())
        gross_return = float((target_weights * returns.loc[current_date]).sum())
        strategy_returns.append(gross_return - turnover * cost_bps / 10_000.0)
        turnovers.append(turnover)
        realized_returns = returns.loc[current_date]
        prior_weights = _drift_weights(target_weights, realized_returns)

        benchmark_turnover = float((benchmark_target - benchmark_prior_weights).abs().sum())
        benchmark_gross_return = float((benchmark_target * realized_returns).sum())
        benchmark_net_returns.append(
            benchmark_gross_return - benchmark_turnover * cost_bps / 10_000.0
        )
        benchmark_turnovers.append(benchmark_turnover)
        benchmark_prior_weights = _drift_weights(benchmark_target, realized_returns)

    strategy = pd.Series(strategy_returns, index=test_dates, dtype=float)
    benchmark = pd.Series(benchmark_net_returns, index=test_dates, dtype=float)
    if strategy.empty or strategy.isna().any() or benchmark.isna().any():
        return None
    volatility = float(strategy.std(ddof=1))
    sharpe = float(strategy.mean() / volatility * np.sqrt(252)) if volatility > 0 else 0.0
    strategy_total = float((1.0 + strategy).prod() - 1.0)
    benchmark_total = float((1.0 + benchmark).prod() - 1.0)
    return CrossSectionalWindow(
        start=str(test_dates[0]),
        end=str(test_dates[-1]),
        observations=len(strategy),
        complete_assets=len(assets),
        active_fraction=active_days / len(strategy),
        total_return=strategy_total,
        benchmark_return=benchmark_total,
        excess_return=strategy_total - benchmark_total,
        sharpe=sharpe,
        max_drawdown=_max_drawdown(strategy),
        average_turnover=float(np.mean(turnovers)),
        benchmark_average_turnover=float(np.mean(benchmark_turnovers)),
        cost_bps=cost_bps,
    )


def evaluate_cross_sectional_scores(
    close: pd.DataFrame,
    scores: pd.DataFrame,
    *,
    top_quantile: float = 0.20,
    cost_bps: float = 10.0,
    windows: int = 2,
    oos_pct: float = 0.20,
    min_assets: int = 3,
) -> CrossSectionalResearchReport:
    """Evaluate causal cross-sectional scores on sequential held-out windows.

    Signals are observed at the prior close and earn the next close-to-close
    return. A single missing session is marked at the last close to accommodate
    exchange calendar differences; assets with longer gaps are excluded from
    that window. The benchmark is a daily rebalanced equal-weight portfolio of
    the same common-calendar assets, not per-symbol buy-and-hold and not the
    existing E3 promotion criterion.
    """
    if close.empty or close.shape[1] < min_assets:
        raise ValueError(f"close must contain at least {min_assets} assets")
    if not 0 < top_quantile <= 1:
        raise ValueError("top_quantile must be in (0, 1]")
    if cost_bps < 0:
        raise ValueError("cost_bps must be non-negative")
    if min_assets < 2:
        raise ValueError("min_assets must be at least 2")
    if windows < 1:
        raise ValueError("windows must be at least 1")
    if not 0 < oos_pct <= 0.5:
        raise ValueError("oos_pct must be in (0, 0.5]")

    prices = close.copy()
    prices.index = pd.to_datetime(prices.index, utc=True, errors="coerce")
    prices = prices.loc[~prices.index.isna()].sort_index()
    prices = prices.loc[:, ~prices.columns.duplicated()]
    prices.columns = [str(symbol).upper() for symbol in prices.columns]
    if prices.index.has_duplicates:
        prices = prices.groupby(level=0).last()
    prices = prices.apply(pd.to_numeric, errors="coerce")
    signal_scores = scores.replace([np.inf, -np.inf], np.nan).copy()
    signal_scores.index = pd.to_datetime(signal_scores.index, utc=True, errors="coerce")
    signal_scores = signal_scores.loc[~signal_scores.index.isna()].sort_index()
    signal_scores.columns = [str(symbol).upper() for symbol in signal_scores.columns]

    candidate_windows = oos_windows(
        len(prices), oos_pct=oos_pct, count=windows, min_bars=2
    )
    passed_windows: list[CrossSectionalWindow] = []
    skipped: list[str] = []
    for lo, hi in reversed(candidate_windows):
        aligned_window = prices.ffill(limit=1).iloc[lo - 1 : hi]
        complete_assets = int(aligned_window.notna().all(axis=0).sum())
        if complete_assets < min_assets:
            skipped.append(
                f"{lo}:{hi} only {complete_assets}/{min_assets} assets survive "
                "the one-session gap rule"
            )
            continue
        result = _window_metrics(
            prices,
            signal_scores,
            lo=lo,
            hi=hi,
            top_quantile=top_quantile,
            cost_bps=cost_bps,
            min_assets=min_assets,
        )
        if result is None:
            skipped.append(f"{lo}:{hi} has no evaluable returns or valid portfolio scores")
        else:
            passed_windows.append(result)

    return CrossSectionalResearchReport(
        signal="IC-weighted cross-sectional top-quantile long-only",
        benchmark="daily rebalanced equal-weight same-universe portfolio",
        windows=passed_windows,
        skipped_windows=skipped,
        factor_ids=[],
    )


def run_factor_research(
    panel: dict[str, pd.DataFrame],
    *,
    factor_ids: list[str] | None = None,
    horizon: int = 1,
    min_ic_obs: int = 20,
    embargo: int = 1,
    top_quantile: float = 0.20,
    cost_bps: float = 10.0,
    windows: int = 2,
    oos_pct: float = 0.20,
    min_assets: int = 3,
    registry=None,
) -> CrossSectionalResearchReport:
    """Build lagged IC-weighted scores from a price panel and test OOS windows."""
    close = panel.get("close")
    if close is None:
        raise ValueError("panel must contain a close DataFrame")
    effective_factor_ids = factor_ids or DEFAULT_COMPOSITE_FACTOR_IDS
    scores = ic_weighted_composite(
        panel,
        factor_ids=effective_factor_ids,
        registry=registry,
        horizon=horizon,
        min_ic_obs=min_ic_obs,
        embargo=embargo,
    )
    report = evaluate_cross_sectional_scores(
        close,
        scores,
        top_quantile=top_quantile,
        cost_bps=cost_bps,
        windows=windows,
        oos_pct=oos_pct,
        min_assets=min_assets,
    )
    report.factor_ids = list(effective_factor_ids)
    return report