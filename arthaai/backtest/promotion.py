"""Signal promotion gate: offline-out-of-sample validation before a strategy
is allowed to run live.

A signal is promoted only when it passes ALL THREE criteria on a held-out
out-of-sample slice:

1. Sharpe >= MIN_SHARPE (1.0) on OOS
2. Max drawdown <= MAX_DD (20%) on OOS
3. Beats buy-and-hold on OOS (strategy_return > buy_hold_return)

These are deterministic — computed by the backtest engine, never by an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_SHARPE: float = 1.0
MAX_DD: float = 0.20


@dataclass
class PromotionEvaluation:
    symbol: str
    qualified: bool
    sharpe: float
    max_drawdown: float
    oos_return: float
    buy_hold_return: float
    sharpe_ok: bool
    dd_ok: bool
    bh_ok: bool
    failures: list[str]

    @property
    def reason(self) -> str:
        if self.qualified:
            return "qualified"
        return "; ".join(self.failures)


def check_criteria(
    sharpe: float,
    max_drawdown: float,
    oos_return: float,
    buy_hold_return: float,
) -> tuple[bool, bool, bool, bool, list[str]]:
    """Apply the strict promotion gate.

    Returns (qualified, sharpe_ok, dd_ok, bh_ok, failures).
    All three must pass; any failure disqualifies.
    """
    sharpe_ok = sharpe >= MIN_SHARPE
    dd_ok = abs(max_drawdown) <= MAX_DD
    bh_ok = oos_return > buy_hold_return

    failures: list[str] = []
    if not sharpe_ok:
        failures.append(f"sharpe {sharpe:.2f} < {MIN_SHARPE}")
    if not dd_ok:
        failures.append(f"max_drawdown {max_drawdown:.1%} exceeds {MAX_DD:.0%} cap")
    if not bh_ok:
        failures.append(f"oos_return {oos_return:.4f} <= buy_hold {buy_hold_return:.4f}")

    return all([sharpe_ok, dd_ok, bh_ok]), sharpe_ok, dd_ok, bh_ok, failures


def evaluate_promotion(
    oos_sharpe: float,
    oos_max_drawdown: float,
    oos_total_return: float,
    buy_hold_return: float,
) -> PromotionEvaluation:
    """Evaluate whether a signal meets all promotion criteria."""
    qualified, sharpe_ok, dd_ok, bh_ok, failures = check_criteria(
        sharpe=oos_sharpe,
        max_drawdown=oos_max_drawdown,
        oos_return=oos_total_return,
        buy_hold_return=buy_hold_return,
    )
    return PromotionEvaluation(
        symbol="",
        qualified=qualified,
        sharpe=oos_sharpe,
        max_drawdown=oos_max_drawdown,
        oos_return=oos_total_return,
        buy_hold_return=buy_hold_return,
        sharpe_ok=sharpe_ok,
        dd_ok=dd_ok,
        bh_ok=bh_ok,
        failures=failures,
    )


def get_promotion_status(symbol: str) -> dict | None:
    """Check the promotion status of a symbol from the DB.

    Returns a dict with qualified, sharpe, max_drawdown, oos_return,
    buy_hold_return, evaluated_at; or None if no promotion record exists.
    """
    from arthaai.db import timescale

    return timescale.get_signal_promotion(symbol)