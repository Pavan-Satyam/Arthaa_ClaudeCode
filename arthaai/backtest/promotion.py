"""Signal promotion gate: offline-out-of-sample validation before a strategy
is allowed to run live.

A signal is promoted only when it passes ALL criteria on held-out
out-of-sample slices:

1. Sharpe >= MIN_SHARPE (1.0) on OOS
2. Max drawdown <= MAX_DD (20%) on OOS
3. Beats buy-and-hold on OOS, **exposure-matched**

Criterion 3 compares the 100%-exposure long-only strategy return against
buy-and-hold — NOT the Kelly-sized return. Comparing a ~1–5%-exposure strategy
to a 100%-invested benchmark on raw return is unwinnable by construction and
grades the wrong quantity. The Kelly-sized return is still recorded.

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
    oos_return: float          # Kelly-sized strategy return (informational)
    buy_hold_return: float
    long_only_return: float    # 100%-exposure long/flat strategy return
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
    oos_long_only_return: float | None = None,
    min_sharpe: float = MIN_SHARPE,
) -> tuple[bool, bool, bool, bool, list[str]]:
    """Apply the strict promotion gate.

    Returns (qualified, sharpe_ok, dd_ok, bh_ok, failures).
    All criteria must pass; any failure disqualifies.

    ``bh_ok`` uses the exposure-matched long-only return when supplied; otherwise
    it falls back to the Kelly-sized return (legacy behaviour).
    """
    sharpe_ok = sharpe >= min_sharpe
    dd_ok = abs(max_drawdown) <= MAX_DD
    benchmarked = oos_long_only_return if oos_long_only_return is not None else oos_return
    bh_ok = benchmarked > buy_hold_return

    failures: list[str] = []
    if not sharpe_ok:
        failures.append(f"sharpe {sharpe:.2f} < {min_sharpe}")
    if not dd_ok:
        failures.append(f"max_drawdown {max_drawdown:.1%} exceeds {MAX_DD:.0%} cap")
    if not bh_ok:
        failures.append(
            f"long_only {benchmarked:.2%} <= buy_hold {buy_hold_return:.2%} (exposure-matched)"
        )

    return all([sharpe_ok, dd_ok, bh_ok]), sharpe_ok, dd_ok, bh_ok, failures


def evaluate_promotion(
    oos_sharpe: float,
    oos_max_drawdown: float,
    oos_total_return: float,
    buy_hold_return: float,
    oos_long_only_return: float | None = None,
    min_sharpe: float = MIN_SHARPE,
) -> PromotionEvaluation:
    """Evaluate whether a signal meets all promotion criteria."""
    qualified, sharpe_ok, dd_ok, bh_ok, failures = check_criteria(
        sharpe=oos_sharpe,
        max_drawdown=oos_max_drawdown,
        oos_return=oos_total_return,
        buy_hold_return=buy_hold_return,
        oos_long_only_return=oos_long_only_return,
        min_sharpe=min_sharpe,
    )
    benchmarked = oos_long_only_return if oos_long_only_return is not None else oos_total_return
    return PromotionEvaluation(
        symbol="",
        qualified=qualified,
        sharpe=oos_sharpe,
        max_drawdown=oos_max_drawdown,
        oos_return=oos_total_return,
        buy_hold_return=buy_hold_return,
        long_only_return=benchmarked,
        sharpe_ok=sharpe_ok,
        dd_ok=dd_ok,
        bh_ok=bh_ok,
        failures=failures,
    )


def combine_windows(evaluations: list[PromotionEvaluation]) -> tuple[bool, str]:
    """Promotion requires EVERY window to pass (an AND across windows).

    Passing one cherry-picked window is not evidence; requiring the intersection
    is the cheap, honest guard against selection across windows.
    """
    if not evaluations:
        return False, "no windows evaluated"
    failing = [e for e in evaluations if not e.qualified]
    if not failing:
        return True, f"qualified (all {len(evaluations)} windows)"
    return False, f"{len(failing)}/{len(evaluations)} window(s) failed"


def get_promotion_status(symbol: str) -> dict | None:
    """Check the promotion status of a symbol from the DB.

    Returns a dict with qualified, sharpe, max_drawdown, oos_return,
    buy_hold_return, evaluated_at; or None if no promotion record exists.
    """
    from arthaai.db import timescale

    return timescale.get_signal_promotion(symbol)
