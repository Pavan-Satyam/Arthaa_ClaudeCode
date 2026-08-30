"""Offline evaluation — walk-forward backtest with look-ahead-bias guards."""

from arthaai.backtest.engine import BacktestResult, oos_slice, run_backtest
from arthaai.backtest.promotion import (
    MAX_DD,
    MIN_SHARPE,
    check_criteria,
    evaluate_promotion,
    get_promotion_status,
)

__all__ = [
    "MAX_DD",
    "MIN_SHARPE",
    "BacktestResult",
    "check_criteria",
    "evaluate_promotion",
    "get_promotion_status",
    "oos_slice",
    "run_backtest",
]