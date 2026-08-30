"""Position / Portfolio state machine.

Shared by backtest and live execution so both walk the same state transitions
— no live-vs-back divergence. One source of truth for:

- Position: per-symbol lifecycle (FLAT → PENDING_ENTRY → OPEN → EXITING → CLOSED)
- Portfolio: multi-position aggregate with peak-to-trough equity-curve breaker
- Fill: realised fill with slippage model

Equity-curve breaker: rolling peak-to-trough on the portfolio equity curve.
A single-bar PnL threshold is a fat-tail coin-flip; the rolling window catches
regime breakdowns (correlations spiking, vol regime shift).

Breaker reset:
- Default: auto-reset at next bar after a trading-session boundary
- Optional manual mode (--manual-reset-only) for debugging
- Escalation: 2+ consecutive trip days → SYSTEM_LOCKED, requires manual unlock
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import pandas as pd


class PositionState(str, Enum):
    FLAT = "flat"
    PENDING_ENTRY = "pending_entry"
    OPEN = "open"
    EXITING = "exiting"
    CLOSED = "closed"


class PortfolioState(str, Enum):
    ACTIVE = "active"
    DRAWDOWN_BREAKER = "drawdown_breaker"
    SYSTEM_LOCKED = "system_locked"


@dataclass
class Fill:
    ts: pd.Timestamp
    symbol: str
    side: str
    quantity: float
    price: float
    slippage_bps: float = 0.0

    def notional(self) -> float:
        return self.quantity * self.price


@dataclass
class Position:
    symbol: str
    state: PositionState = PositionState.FLAT
    entry_price: float | None = None
    entry_ts: pd.Timestamp | None = None
    quantity: float = 0.0
    stop_price: float | None = None
    target_price: float | None = None
    exit_price: float | None = None
    exit_ts: pd.Timestamp | None = None
    unrealized_pnl: float = 0.0
    realised_pnl: float = 0.0

    def open(self, fill: Fill, stop_price: float, target_price: float | None = None) -> None:
        if self.state not in (PositionState.FLAT, PositionState.CLOSED):
            raise ValueError(f"cannot open: position is {self.state.value}")
        self.state = PositionState.OPEN
        self.entry_price = fill.price
        self.entry_ts = fill.ts
        self.quantity = fill.quantity
        self.stop_price = stop_price
        self.target_price = target_price
        self.unrealized_pnl = 0.0

    def close(self, fill: Fill) -> None:
        if self.state not in (PositionState.OPEN, PositionState.EXITING):
            raise ValueError(f"cannot close: position is {self.state.value}")
        if self.exit_price is None:
            self.exit_price = fill.price
        self.exit_ts = fill.ts
        self.realised_pnl = (self.exit_price - self.entry_price) * self.quantity
        self.unrealized_pnl = 0.0
        self.state = PositionState.CLOSED

    def step(self, bar: pd.Series) -> Fill | None:
        if self.state != PositionState.OPEN:
            return None

        ts = bar["ts"]
        low, high = bar["low"], bar["high"]
        mark = bar["close"]
        self.unrealized_pnl = (mark - self.entry_price) * self.quantity

        if self.stop_price is not None and low <= self.stop_price:
            self.state = PositionState.EXITING
            return Fill(ts=ts, symbol=self.symbol, side="sell",
                        quantity=self.quantity, price=self.stop_price)

        if self.target_price is not None and high >= self.target_price:
            self.state = PositionState.EXITING
            return Fill(ts=ts, symbol=self.symbol, side="sell",
                        quantity=self.quantity, price=self.target_price)

        return None


@dataclass
class Portfolio:
    initial_equity: float = 100_000.0
    positions: dict[str, Position] = field(default_factory=dict)
    cash: float = 100_000.0
    state: PortfolioState = PortfolioState.ACTIVE

    drawdown_lookback: int = 5
    drawdown_trigger: float = 0.10
    max_consecutive_trips: int = 2

    _equity_curve: list[float] = field(default_factory=list)
    _peak_equity: float = 100_000.0
    _consecutive_trips: int = 0
    _last_session_ts: pd.Timestamp | None = None

    def mark_to_market(self, prices: dict[str, float]) -> float:
        equity = self.cash
        for sym, pos in self.positions.items():
            if pos.state == PositionState.OPEN and sym in prices:
                equity += pos.quantity * prices[sym]
        return equity

    def deposit(self, amount: float) -> None:
        self.cash = max(0.0, self.cash - amount)

    def add_proceeds(self, amount: float) -> None:
        self.cash += amount

    def record_entry_equity(self, quantity: float, entry_price: float) -> None:
        if not self._equity_curve:
            entry_equity = self.cash + quantity * entry_price
            self._equity_curve = [entry_equity]
            self._peak_equity = entry_equity

    def _update_breaker(self, ts: pd.Timestamp, equity: float) -> None:
        if (self._last_session_ts is not None
                and ts.normalize() != self._last_session_ts.normalize()
                and self.state == PortfolioState.DRAWDOWN_BREAKER):
            self.state = PortfolioState.ACTIVE

        self._last_session_ts = ts

        if self.state == PortfolioState.SYSTEM_LOCKED:
            return

        if not self._equity_curve:
            self._equity_curve.append(equity)
            self._peak_equity = equity
            return

        self._equity_curve.append(equity)
        self._peak_equity = max(self._peak_equity, equity)

        window = self._equity_curve[-self.drawdown_lookback:]
        local_peak = max(window) if window else equity
        if local_peak > 0:
            drawdown = (local_peak - equity) / local_peak
            if drawdown >= self.drawdown_trigger:
                self._trip_breaker()

    def _trip_breaker(self) -> None:
        if self.state == PortfolioState.ACTIVE:
            self.state = PortfolioState.DRAWDOWN_BREAKER
            self._consecutive_trips += 1
            if self._consecutive_trips >= self.max_consecutive_trips:
                self.state = PortfolioState.SYSTEM_LOCKED

    def reset_consecutive_trips(self) -> None:
        self._consecutive_trips = 0

    def unlock(self) -> None:
        self.state = PortfolioState.ACTIVE
        self._consecutive_trips = 0

    def is_buyable(self) -> bool:
        return self.state == PortfolioState.ACTIVE

    def step(self, bar: pd.Series) -> dict[str, Fill | None]:
        fills: dict[str, Fill | None] = {}
        for sym, pos in self.positions.items():
            fill = pos.step(bar)
            if fill is not None:
                pos.close(fill)
                fills[sym] = fill
            else:
                fills[sym] = None

        for sym, fill in fills.items():
            if fill is not None:
                if fill.side == "buy":
                    self.deposit(fill.notional())
                else:
                    self.add_proceeds(fill.notional())

        close_prices = {s: bar.get("close", 0.0) for s in self.positions}
        equity = self.mark_to_market(close_prices)
        self._update_breaker(bar["ts"], equity)
        return fills
