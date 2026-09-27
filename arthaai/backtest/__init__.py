"""Offline evaluation — walk-forward backtest with look-ahead-bias guards."""

from arthaai.backtest.engine import BacktestResult, oos_slice, oos_windows, run_backtest
from arthaai.backtest.promotion import (
    MAX_DD,
    MIN_SHARPE,
    check_criteria,
    combine_windows,
    evaluate_promotion,
    get_promotion_status,
)

__all__ = [
    "MAX_DD",
    "MIN_SHARPE",
    "BacktestResult",
    "check_criteria",
    "combine_windows",
    "evaluate_promotion",
    "get_promotion_status",
    "oos_slice",
    "oos_windows",
    "run_backtest",
]
