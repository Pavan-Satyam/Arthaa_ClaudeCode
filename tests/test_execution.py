"""Tier 4 execution guardrails."""

import pytest

from arthaai.execution import ExecutionEngine, TradingHalted


def test_order_sized_from_allocation():
    eng = ExecutionEngine(equity=100_000)
    order = eng.submit("GLD", {"final_fraction": 0.05}, last_price=100.0, direction="bullish")
    assert order.notional == 5000.0
    assert order.side == "buy"
    assert order.stop_loss == 92.0  # 8% below entry
    assert order.paper is True


def test_sell_stop_above_entry():
    eng = ExecutionEngine(equity=100_000)
    order = eng.submit("USO", {"final_fraction": 0.03}, last_price=100.0, direction="bearish")
    assert order.side == "sell" and order.stop_loss == 108.0


def test_drawdown_breaker_halts_trading():
    eng = ExecutionEngine(equity=100_000)
    eng.mark_equity(89_000)  # -11% on the day, past the 10% limit
    assert eng.breaker_state == "OPEN"
    with pytest.raises(TradingHalted):
        eng.submit("GLD", {"final_fraction": 0.05}, last_price=100.0, direction="bullish")
