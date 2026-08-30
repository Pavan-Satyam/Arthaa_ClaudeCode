"""Tier 4 paper execution engine with hardcoded circuit-breaker guardrails.

Blueprint "Programmable Guardrails": deterministic anchors against probabilistic
hallucinations — a max peak-to-trough drawdown that halts ALL trading (e.g. 10%)
and a mandatory stop-loss on every position. These are hard limits the LLM cannot
override.

PAPER ONLY. This never contacts a broker; it records intended orders against a
simulated account. Real execution (a broker MCP tool) plugs in at _place() behind
the same guardrails.

Composes arthaai.execution.state for the per-symbol Position state machine and
the portfolio-level equity-curve breaker, so backtest and live execution walk
identical state transitions.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from arthaai.execution.state import (
    Fill,
    Portfolio,
    PortfolioState,
    Position,
    PositionState,
)


class TradingHalted(RuntimeError):
    """Raised when the drawdown circuit breaker is OPEN or SYSTEM_LOCKED."""


@dataclass
class Order:
    symbol: str
    side: str
    notional: float
    stop_loss: float
    paper: bool = True


class ExecutionEngine:
    """Paper execution engine backed by the shared state machine."""

    def __init__(
        self,
        initial_equity: float = 100_000.0,
        equity: float | None = None,
        drawdown_trigger: float = 0.10,
        drawdown_lookback: int = 5,
        stop_loss_pct: float = 0.08,
    ) -> None:
        if equity is not None:
            initial_equity = equity
        self.portfolio = Portfolio(
            initial_equity=initial_equity,
            drawdown_trigger=drawdown_trigger,
            drawdown_lookback=drawdown_lookback,
        )
        self.portfolio._equity_curve = [initial_equity]
        self.portfolio._peak_equity = initial_equity
        self.stop_loss_pct = stop_loss_pct
        self.orders: list[Order] = []

    @property
    def breaker_state(self) -> str:
        """Backward-compatible: 'OPEN' when breaker is tripped, else 'CLOSED'."""
        if self.portfolio.state == PortfolioState.ACTIVE:
            return "CLOSED"
        return "OPEN"

    @property
    def equity(self) -> float:
        return self.portfolio.mark_to_market(
            {s: p.entry_price for s, p in self.portfolio.positions.items() if p.state == PositionState.OPEN}
        )

    def mark_equity(self, equity: float) -> None:
        open_positions = {
            s: p for s, p in self.portfolio.positions.items() if p.state == PositionState.OPEN
        }
        open_value = sum(p.quantity * p.entry_price for p in open_positions.values())
        self.portfolio.cash = max(0.0, equity - open_value)
        self.portfolio._equity_curve.append(equity)
        self.portfolio._peak_equity = max(self.portfolio._peak_equity, equity)
        window = self.portfolio._equity_curve[-self.portfolio.drawdown_lookback :]
        local_peak = max(window) if window else equity
        if local_peak > 0:
            drawdown = (local_peak - equity) / local_peak
            if drawdown >= self.portfolio.drawdown_trigger:
                self.portfolio._trip_breaker()

    def step(self, bar) -> dict:
        return self.portfolio.step(bar)

    def submit(
        self,
        symbol: str,
        allocation: dict,
        last_price: float,
        direction: str,
        ts: pd.Timestamp | None = None,
    ) -> Order:
        if not self.portfolio.is_buyable():
            raise TradingHalted(
                f"Portfolio state {self.portfolio.state.value} — trading halted."
            )
        if symbol not in self.portfolio.positions:
            pos = Position(symbol=symbol)
            self.portfolio.positions[symbol] = pos
        pos = self.portfolio.positions[symbol]
        fraction = float(allocation.get("final_fraction", 0.0))
        notional = round(self.equity * fraction, 2)
        side = "buy" if direction == "bullish" else "sell"
        price = last_price
        stop = round(
            price * (1 - self.stop_loss_pct) if side == "buy" else price * (1 + self.stop_loss_pct),
            4,
        )
        fill_ts = ts if ts is not None else pd.Timestamp.now(tz="UTC")
        fill = Fill(
            ts=fill_ts,
            symbol=symbol,
            side=side,
            quantity=notional / price,
            price=price,
        )
        is_new = pos.state == PositionState.FLAT
        if is_new:
            pos.open(fill, stop_price=stop, target_price=None)
            self.portfolio.record_entry_equity(fill.quantity, fill.price)
            self.portfolio.deposit(fill.notional())
        order = Order(symbol=symbol.upper(), side=side, notional=notional, stop_loss=stop)
        self.orders.append(order)
        return order

    def close(self, symbol: str, fill: Fill) -> None:
        pos = self.portfolio.positions.get(symbol)
        if pos is not None and pos.state == PositionState.OPEN:
            pos.close(fill)
