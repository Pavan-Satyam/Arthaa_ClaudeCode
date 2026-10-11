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

Pass an ``audit`` (path or AuditLog) to persist orders, fills and breaker events
as JSONL so the trail survives a process restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from arthaai.execution.audit import AuditLog
from arthaai.execution.fills import FillModel
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
    status: str = "filled"
    filled_quantity: float = 0.0
    slippage_bps: float = 0.0


class ExecutionEngine:
    """Paper execution engine backed by the shared state machine."""

    def __init__(
        self,
        initial_equity: float = 100_000.0,
        equity: float | None = None,
        drawdown_trigger: float = 0.10,
        drawdown_lookback: int = 5,
        stop_loss_pct: float = 0.08,
        audit: AuditLog | str | Path | None = None,
        fill_model: FillModel | None = None,
    ) -> None:
        if equity is not None:
            initial_equity = equity
        self.fill_model = fill_model or FillModel()
        self.portfolio = Portfolio(
            initial_equity=initial_equity,
            drawdown_trigger=drawdown_trigger,
            drawdown_lookback=drawdown_lookback,
            fill_model=self.fill_model,
        )
        self.portfolio._equity_curve = [initial_equity]
        self.portfolio._peak_equity = initial_equity
        self.stop_loss_pct = stop_loss_pct
        self.orders: list[Order] = []
        if isinstance(audit, (str, Path)):
            audit = AuditLog(audit)
        self.audit: AuditLog | None = audit

    def _audit(self, event: str, **fields) -> None:
        if self.audit is not None:
            self.audit.write(event, **fields)

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

    def shadow_account_audit(self, prices: dict[str, float] | None = None) -> dict:
        """Return a conservative reconciliation snapshot for the live paper account.

        The purpose is not to predict future performance; it is to make the current
        execution state auditable: cash on hand, marked open notional, aggregate
        gross/net exposure, and any obvious reconciliation issues. This is the
        minimal implementation needed for the deferred shadow-account board item.
        """
        prices = prices or {}
        open_positions: list[dict] = []
        gross_exposure = 0.0
        net_exposure = 0.0
        discrepancies: list[str] = []

        for symbol, pos in sorted(self.portfolio.positions.items()):
            if pos.state != PositionState.OPEN:
                continue
            price = prices.get(symbol, pos.entry_price)
            if price is None:
                discrepancies.append(f"missing_price:{symbol}")
                continue
            quantity = float(pos.quantity)
            notional = quantity * float(price)
            gross_exposure += abs(notional)
            net_exposure += notional
            open_positions.append(
                {
                    "symbol": symbol,
                    "quantity": quantity,
                    "entry_price": float(pos.entry_price),
                    "mark_price": float(price),
                    "notional": float(notional),
                    "side": "long" if quantity >= 0 else "short",
                }
            )

        cash = float(self.portfolio.cash)
        status = "ok" if not discrepancies else "mismatch"
        return {
            "cash": cash,
            "open_positions": open_positions,
            "gross_exposure": float(gross_exposure),
            "net_exposure": float(net_exposure),
            "equity": float(self.equity),
            "state": self.portfolio.state.value,
            "status": status,
            "discrepancies": discrepancies,
        }

    def mark_equity(self, equity: float) -> None:
        before = self.portfolio.state
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
        if self.portfolio.state != before:
            self._audit("breaker", state=self.portfolio.state.value, equity=equity)

    def step(self, bar) -> dict:
        """Advance one bar: mark positions, fire stops/targets, update breaker."""
        before = self.portfolio.state
        fills = self.portfolio.step(bar)
        for sym, fill in fills.items():
            if fill is None:
                continue
            self._audit(
                "fill", symbol=sym, side=fill.side, quantity=fill.quantity,
                price=fill.price, reason=fill.reason or "exit",
                slippage_bps=fill.slippage_bps, ts=fill.ts,
            )
        if self.portfolio.state != before:
            self._audit("breaker", state=self.portfolio.state.value)
        return fills

    def submit(
        self,
        symbol: str,
        allocation: dict,
        last_price: float,
        direction: str,
        ts: pd.Timestamp | None = None,
        bar: pd.Series | dict | None = None,
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
        requested_qty = notional / price if price else 0.0
        fill_ts = ts if ts is not None else pd.Timestamp.now(tz="UTC")

        outcome = self.fill_model.apply(side, price, requested_qty, bar=bar)
        if outcome.rejected:
            order = Order(
                symbol=symbol.upper(), side=side, notional=0.0, stop_loss=0.0,
                status="rejected",
            )
            self.orders.append(order)
            self._audit(
                "reject", symbol=order.symbol, side=side, reason=outcome.reason, ts=fill_ts,
            )
            return order

        fill_price = outcome.price
        stop = round(
            fill_price * (1 - self.stop_loss_pct) if side == "buy" else fill_price * (1 + self.stop_loss_pct),
            4,
        )
        fill = Fill(
            ts=fill_ts,
            symbol=symbol,
            side=side,
            quantity=outcome.quantity,
            price=fill_price,
            slippage_bps=outcome.slippage_bps,
            reason="entry",
        )
        is_new = pos.state in (PositionState.FLAT, PositionState.CLOSED)
        if is_new:
            pos.open(fill, stop_price=stop, target_price=None)
            self.portfolio.record_entry_equity(fill.quantity, fill.price)
            self.portfolio.deposit(fill.notional())
        order = Order(
            symbol=symbol.upper(), side=side, notional=fill.notional(), stop_loss=stop,
            status="partial" if outcome.partial else "filled",
            filled_quantity=outcome.quantity, slippage_bps=outcome.slippage_bps,
        )
        self.orders.append(order)
        self._audit(
            "order", symbol=order.symbol, side=order.side, notional=order.notional,
            stop_loss=order.stop_loss, paper=order.paper, status=order.status,
            filled_quantity=order.filled_quantity, slippage_bps=order.slippage_bps, ts=fill_ts,
        )
        return order

    def close(self, symbol: str, fill: Fill) -> None:
        pos = self.portfolio.positions.get(symbol)
        if pos is not None and pos.state == PositionState.OPEN:
            pos.close(fill)

    def exit_position(
        self,
        symbol: str,
        price: float,
        ts: pd.Timestamp | None = None,
        reason: str = "exit",
    ) -> Fill | None:
        """Close an open position at ``price`` (signal exit), crediting proceeds."""
        pos = self.portfolio.positions.get(symbol)
        if pos is None or pos.state != PositionState.OPEN:
            return None
        exit_price = self.fill_model.exit_price("sell", price)
        fill = Fill(
            ts=ts if ts is not None else pd.Timestamp.now(tz="UTC"),
            symbol=symbol,
            side="sell",
            quantity=pos.quantity,
            price=exit_price,
            slippage_bps=self.fill_model.slippage_bps,
            reason=reason,
        )
        pos.close(fill)
        self.portfolio.add_proceeds(fill.notional())
        self._audit(
            "fill", symbol=symbol, side="sell", quantity=fill.quantity,
            price=fill.price, reason=reason, slippage_bps=fill.slippage_bps, ts=fill.ts,
        )
        return fill

    def kill_switch(self, prices: dict[str, float] | None = None) -> dict:
        """Flatten all open positions and lock the portfolio (manual unlock)."""
        fills = self.portfolio.kill_switch(prices)
        self._audit("kill_switch", closed=sorted(fills), state=self.portfolio.state.value)
        return fills

    def reset_day(self) -> None:
        """Clear an active (unlocked) drawdown breaker at a session boundary."""
        before = self.portfolio.state
        self.portfolio.reset_day()
        if self.portfolio.state != before:
            self._audit("reset_day", state=self.portfolio.state.value)

    def unlock(self) -> None:
        """Manual unlock from DRAWDOWN_BREAKER / SYSTEM_LOCKED."""
        self.portfolio.unlock()
        self._audit("unlock", state=self.portfolio.state.value)
