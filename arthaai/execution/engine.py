"""Tier 4 paper execution engine with hardcoded circuit-breaker guardrails.

Blueprint §"Programmable Guardrails": deterministic anchors against probabilistic
hallucinations — a max daily drawdown that halts ALL trading (e.g. 10%) and a
mandatory stop-loss on every position. These are hard limits the LLM cannot
override.

PAPER ONLY. This never contacts a broker; it records intended orders against a
simulated account. Real execution (a broker MCP tool) plugs in at `._place()`
behind the same guardrails.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class TradingHalted(RuntimeError):
    """Raised when the daily-drawdown circuit breaker has tripped (OPEN)."""


@dataclass
class Order:
    symbol: str
    side: str            # 'buy' | 'sell'
    notional: float      # currency amount
    stop_loss: float     # absolute stop price level
    paper: bool = True


@dataclass
class ExecutionEngine:
    equity: float                       # current account equity
    max_daily_drawdown: float = 0.10    # halt all trading at 10% daily loss
    stop_loss_pct: float = 0.08         # mandatory per-position stop distance
    _day_start_equity: float = field(default=0.0)
    orders: list[Order] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self._day_start_equity == 0.0:
            self._day_start_equity = self.equity

    @property
    def daily_pnl_pct(self) -> float:
        return (self.equity - self._day_start_equity) / self._day_start_equity

    @property
    def breaker_state(self) -> str:
        return "OPEN" if self.daily_pnl_pct <= -self.max_daily_drawdown else "CLOSED"

    def mark_equity(self, equity: float) -> None:
        """Update equity intraday (drives the drawdown breaker)."""
        self.equity = equity

    def submit(self, symbol: str, allocation: dict, last_price: float, direction: str) -> Order:
        """Turn an approved allocation into a bounded paper order.

        `allocation` is the Asset Manager output (already Kelly-scaled + policy-capped).
        Refuses if the daily-drawdown breaker is OPEN.
        """
        if self.breaker_state == "OPEN":
            raise TradingHalted(
                f"Daily drawdown {self.daily_pnl_pct:.1%} breached "
                f"{self.max_daily_drawdown:.0%} limit — all trading halted."
            )
        fraction = float(allocation.get("final_fraction", 0.0))
        notional = round(self.equity * fraction, 2)
        side = "buy" if direction == "bullish" else "sell"
        stop = round(
            last_price * (1 - self.stop_loss_pct) if side == "buy" else last_price * (1 + self.stop_loss_pct),
            4,
        )
        order = Order(symbol=symbol.upper(), side=side, notional=notional, stop_loss=stop)
        self.orders.append(order)
        return order
