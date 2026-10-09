"""Adverse fill simulation for the Tier 4 paper path.

The algebraic backtest and the paper engine previously assumed every order filled
instantly, in full, at the exact reference price. That is the most optimistic
possible model and hides three real frictions:

- **Slippage** — the market moves against you between decision and fill.
- **Partial fills** — you can only take a fraction of the bar's volume, so a
  large order is only partly filled at the reference price.
- **Rejection** — the order never fills (no liquidity, exchange reject).

``FillModel`` centralises all three so entry, stop/target exit and signal exit
paths share one deterministic model. Defaults are a no-op (zero slippage,
unlimited participation, no rejection) so existing behaviour is unchanged and the
model is strictly opt-in. Rejection is driven by a seeded RNG so a run is
reproducible when a seed is supplied.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import pandas as pd


@dataclass
class FillOutcome:
    """Result of trying to fill a requested quantity."""

    quantity: float
    price: float
    slippage_bps: float = 0.0
    rejected: bool = False
    reason: str = "filled"

    @property
    def partial(self) -> bool:
        return self.reason == "partial"


@dataclass
class FillModel:
    """Deterministic adverse-fill model.

    Args:
        slippage_bps: Adverse price move in basis points (buy fills higher,
            sell fills lower). ``0`` is frictionless.
        participation_rate: Max fraction of the bar's volume that may fill. A
            request larger than this is partially filled; ``None`` means the
            request always fills in full.
        reject_probability: Per-order chance in ``[0, 1]`` that the order is
            rejected outright. ``0`` never rejects.
        seed: RNG seed for rejection draws; set it for reproducible runs.
    """

    slippage_bps: float = 0.0
    participation_rate: float | None = None
    reject_probability: float = 0.0
    seed: int | None = None

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def _slipped_price(self, side: str, price: float) -> float:
        factor = self.slippage_bps / 10_000.0
        return price * (1 + factor) if side == "buy" else price * (1 - factor)

    def exit_price(self, side: str, price: float) -> float:
        """Apply adverse slippage to an exit price (full quantity)."""
        return self._slipped_price(side, price)

    def apply(
        self,
        side: str,
        price: float,
        quantity: float,
        bar: pd.Series | dict | None = None,
    ) -> FillOutcome:
        """Try to fill ``quantity`` at ``price``.

        Rejection is checked first, then volume participation caps the fill, then
        slippage is applied to the (possibly reduced) fill price.
        """
        if self.reject_probability > 0.0 and self._rng.random() < self.reject_probability:
            return FillOutcome(quantity=0.0, price=price, rejected=True, reason="rejected")

        filled = quantity
        reason = "filled"
        if self.participation_rate is not None and bar is not None:
            volume = bar.get("volume")
            if volume is not None and not pd.isna(volume):
                cap = self.participation_rate * float(volume)
                if cap <= 0.0:
                    return FillOutcome(
                        quantity=0.0, price=price, rejected=True, reason="no_liquidity"
                    )
                if cap < quantity:
                    filled = cap
                    reason = "partial"

        return FillOutcome(
            quantity=filled,
            price=self._slipped_price(side, price),
            slippage_bps=self.slippage_bps,
            reason=reason,
        )