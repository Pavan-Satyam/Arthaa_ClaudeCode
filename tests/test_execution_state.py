"""Tests for the Position / Portfolio state machine.

Covers:
- Position lifecycle (FLAT → OPEN → EXITING → CLOSED) and stop/target triggers
- Portfolio equity-curve breaker (peak-to-trough, rolling window)
- Breaker auto-reset on session boundary
- Breaker escalation: 2 consecutive trips → SYSTEM_LOCKED
- ExecutionEngine integration
"""

import pandas as pd
import pytest

from arthaai.execution import (
    ExecutionEngine,
    Fill,
    Portfolio,
    PortfolioState,
    Position,
    PositionState,
    TradingHalted,
)


def _bar(ts, o, h, l, c):
    return pd.Series({"ts": pd.Timestamp(ts), "open": o, "high": h, "low": l, "close": c})


def _entry_fill(ts, price=100.0, qty=10.0, sym="GLD"):
    return Fill(ts=pd.Timestamp(ts), symbol=sym, side="buy", quantity=qty, price=price)


class TestPosition:
    def test_opens_from_flat(self):
        p = Position(symbol="GLD")
        p.open(_entry_fill("2025-01-01", price=100.0), stop_price=92.0)
        assert p.state == PositionState.OPEN
        assert p.entry_price == 100.0
        assert p.stop_price == 92.0
        assert p.quantity == 10.0

    def test_cannot_open_when_already_open(self):
        p = Position(symbol="GLD")
        p.open(_entry_fill("2025-01-01"), stop_price=92.0)
        with pytest.raises(ValueError, match="cannot open"):
            p.open(_entry_fill("2025-01-02"), stop_price=92.0)

    def test_stop_triggered_when_low_hits_stop(self):
        p = Position(symbol="GLD")
        p.open(_entry_fill("2025-01-01", price=100.0, qty=10.0), stop_price=92.0)
        bar = _bar("2025-01-02", 100, 102, 90, 95)
        fill = p.step(bar)
        assert fill is not None
        assert fill.side == "sell"
        assert fill.price == 92.0
        assert p.state == PositionState.EXITING
        p.close(fill)
        assert p.state == PositionState.CLOSED
        assert p.realised_pnl == (92.0 - 100.0) * 10.0

    def test_target_triggered_when_high_hits_target(self):
        p = Position(symbol="GLD")
        p.open(
            _entry_fill("2025-01-01", price=100.0, qty=10.0),
            stop_price=92.0,
            target_price=120.0,
        )
        bar = _bar("2025-01-02", 100, 125, 100, 122)
        fill = p.step(bar)
        assert fill is not None
        assert fill.price == 120.0

    def test_no_trigger_in_normal_range(self):
        p = Position(symbol="GLD")
        p.open(_entry_fill("2025-01-01", price=100.0, qty=10.0), stop_price=92.0)
        bar = _bar("2025-01-02", 100, 105, 98, 103)
        assert p.step(bar) is None
        assert p.unrealized_pnl == (103 - 100) * 10.0

    def test_step_noop_when_flat(self):
        p = Position(symbol="GLD")
        assert p.step(_bar("2025-01-01", 100, 105, 98, 103)) is None


class TestPortfolioBreaker:
    def test_breaker_trips_on_peak_to_trough_drawdown(self):
        p = Portfolio(initial_equity=100_000.0, drawdown_trigger=0.10, drawdown_lookback=2)
        p.positions["GLD"] = Position(symbol="GLD")
        p.positions["GLD"].open(
            _entry_fill("2025-01-01", price=100.0, qty=1000.0),
            stop_price=50.0,
        )
        p.record_entry_equity(1000.0, 100.0)
        p.step(_bar("2025-01-02", 80, 80, 80, 80))
        assert p.state == PortfolioState.DRAWDOWN_BREAKER
        assert p._consecutive_trips == 1

        p.step(_bar("2025-01-15", 80, 80, 80, 80))
        assert p.state == PortfolioState.ACTIVE

    def test_breaker_does_not_trip_on_small_drawdown(self):
        p = Portfolio(initial_equity=100_000.0, drawdown_trigger=0.10, drawdown_lookback=5)
        p.positions["GLD"] = Position(symbol="GLD")
        p.positions["GLD"].open(
            _entry_fill("2025-01-01", price=100.0, qty=100.0),
            stop_price=50.0,
        )
        p.record_entry_equity(100.0, 100.0)
        for i, close in enumerate([99, 98, 97, 96, 95]):
            p.step(_bar(f"2025-01-{i+2:02d}", close, close, close, close))
        assert p.state == PortfolioState.ACTIVE

    def test_breaker_auto_resets_next_session(self):
        p = Portfolio(initial_equity=100_000.0, drawdown_trigger=0.10, drawdown_lookback=2)
        p.positions["GLD"] = Position(symbol="GLD")
        p.positions["GLD"].open(
            _entry_fill("2025-01-01", price=100.0, qty=1000.0),
            stop_price=50.0,
        )
        p.record_entry_equity(1000.0, 100.0)
        p.step(_bar("2025-01-02", 80, 80, 80, 80))
        assert p.state == PortfolioState.DRAWDOWN_BREAKER
        assert p._consecutive_trips == 1

        p.step(_bar("2025-01-15", 80, 80, 80, 80))
        assert p.state == PortfolioState.ACTIVE

    def test_consecutive_trips_escalate_to_system_locked(self):
        p = Portfolio(
            initial_equity=100_000.0,
            drawdown_trigger=0.10,
            drawdown_lookback=2,
            max_consecutive_trips=2,
        )
        p.positions["GLD"] = Position(symbol="GLD")
        p.positions["GLD"].open(
            _entry_fill("2025-01-01", price=100.0, qty=1000.0),
            stop_price=50.0,
        )
        p.record_entry_equity(1000.0, 100.0)
        p.step(_bar("2025-01-02", 80, 80, 80, 80))
        assert p.state == PortfolioState.DRAWDOWN_BREAKER
        assert p._consecutive_trips == 1

        p.positions.clear()
        p.positions["SLV"] = Position(symbol="SLV")
        p.positions["SLV"].open(
            _entry_fill("2025-01-15", price=50.0, qty=2000.0),
            stop_price=25.0,
        )
        p.record_entry_equity(2000.0, 50.0)
        p.step(_bar("2025-01-15", 8, 8, 8, 8))
        assert p.state == PortfolioState.SYSTEM_LOCKED

    def test_manual_unlock(self):
        p = Portfolio(initial_equity=100_000.0)
        p.state = PortfolioState.SYSTEM_LOCKED
        p.unlock()
        assert p.state == PortfolioState.ACTIVE
        assert p._consecutive_trips == 0


class TestExecutionEngine:
    def test_submit_creates_order_when_active(self):
        e = ExecutionEngine(initial_equity=100_000.0)
        e.portfolio.positions["GLD"] = Position(symbol="GLD")
        e.portfolio.positions["GLD"].open(
            _entry_fill("2025-01-01", price=100.0, qty=1000.0), stop_price=50.0
        )
        e.portfolio.record_entry_equity(1000.0, 100.0)
        order = e.submit(
            "GLD",
            {"final_fraction": 0.05},
            last_price=100.0,
            direction="bullish",
            ts=pd.Timestamp("2025-01-01"),
        )
        assert order.symbol == "GLD"
        assert order.side == "buy"
        assert order.notional == 10_000.0
        assert order.stop_loss == pytest.approx(92.0)

    def test_submit_refuses_when_breaker_open(self):
        e = ExecutionEngine(initial_equity=100_000.0)
        e.portfolio.state = PortfolioState.DRAWDOWN_BREAKER
        e.portfolio.positions["GLD"] = Position(symbol="GLD")
        with pytest.raises(TradingHalted):
            e.submit(
                "GLD",
                {"final_fraction": 0.05},
                last_price=100.0,
                direction="bullish",
                ts=pd.Timestamp("2025-01-01"),
            )

    def test_step_propagates_fills(self):
        e = ExecutionEngine(initial_equity=100_000.0)
        e.portfolio.positions["GLD"] = Position(symbol="GLD")
        e.submit(
            "GLD",
            {"final_fraction": 0.10},
            last_price=100.0,
            direction="bullish",
            ts=pd.Timestamp("2025-01-01"),
        )
        assert e.portfolio.positions["GLD"].state == PositionState.OPEN

        e.step(_bar("2025-01-02", 100, 102, 90, 95))
        assert e.portfolio.positions["GLD"].state == PositionState.CLOSED
        assert e.portfolio.positions["GLD"].realised_pnl < 0
