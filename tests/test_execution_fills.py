"""Fill simulation — slippage, partial fills and rejection (ARTHA-409)."""

import pandas as pd
import pytest

from arthaai.execution import (
    ExecutionEngine,
    FillModel,
    PositionState,
    read_audit,
)
from arthaai.execution.simulate import simulate_symbol


def _frame(closes, wick=0.01, volume=1e6):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B", tz="UTC")
    return pd.DataFrame({
        "ts": idx,
        "open": closes,
        "high": [c * (1 + wick) for c in closes],
        "low": [c * (1 - wick) for c in closes],
        "close": closes,
        "volume": volume,
    })


def _bar(ts, o, h, l, c, volume=1e6):
    return pd.Series({
        "ts": pd.Timestamp(ts), "open": o, "high": h, "low": l, "close": c, "volume": volume,
    })


class TestFillModel:
    def test_default_is_noop(self):
        out = FillModel().apply("buy", 100.0, 10.0)
        assert out.price == 100.0
        assert out.quantity == 10.0
        assert not out.rejected

    def test_buy_slippage_is_adverse(self):
        assert FillModel(slippage_bps=100).apply("buy", 100.0, 10.0).price == pytest.approx(101.0)

    def test_sell_slippage_is_adverse(self):
        assert FillModel(slippage_bps=100).apply("sell", 100.0, 10.0).price == pytest.approx(99.0)

    def test_partial_fill_capped_by_volume(self):
        out = FillModel(participation_rate=0.1).apply("buy", 10.0, 50.0, bar={"volume": 100.0})
        assert out.quantity == pytest.approx(10.0)
        assert out.partial is True

    def test_no_partial_when_request_below_cap(self):
        out = FillModel(participation_rate=0.5).apply("buy", 10.0, 10.0, bar={"volume": 100.0})
        assert out.quantity == 10.0
        assert out.partial is False

    def test_rejection_probability_one_always_rejects(self):
        out = FillModel(reject_probability=1.0).apply("buy", 100.0, 10.0)
        assert out.rejected is True
        assert out.reason == "rejected"

    def test_rejection_is_seed_reproducible(self):
        a = FillModel(reject_probability=0.5, seed=7)
        b = FillModel(reject_probability=0.5, seed=7)
        draws_a = [a.apply("buy", 1.0, 1.0).rejected for _ in range(20)]
        draws_b = [b.apply("buy", 1.0, 1.0).rejected for _ in range(20)]
        assert draws_a == draws_b

    def test_zero_volume_is_no_liquidity(self):
        out = FillModel(participation_rate=0.5).apply("buy", 10.0, 5.0, bar={"volume": 0.0})
        assert out.rejected is True
        assert out.reason == "no_liquidity"


class TestEngineFillIntegration:
    def test_submit_applies_slippage_to_entry_and_stop(self):
        eng = ExecutionEngine(equity=100_000, fill_model=FillModel(slippage_bps=100))
        order = eng.submit("GLD", {"final_fraction": 0.05}, last_price=100.0, direction="bullish")
        assert order.status == "filled"
        assert order.slippage_bps == 100
        assert order.stop_loss == pytest.approx(101.0 * 0.92, rel=1e-6)

    def test_submit_partial_fill_reduces_quantity(self):
        eng = ExecutionEngine(equity=100_000, fill_model=FillModel(participation_rate=0.001))
        order = eng.submit(
            "GLD", {"final_fraction": 0.05}, 100.0, "bullish",
            bar={"volume": 1000.0},
        )
        assert order.status == "partial"
        assert order.filled_quantity == pytest.approx(1.0)
        assert eng.portfolio.positions["GLD"].quantity == pytest.approx(1.0)

    def test_submit_rejection_leaves_flat_and_audits(self, tmp_path):
        log = tmp_path / "audit.jsonl"
        eng = ExecutionEngine(
            equity=100_000, fill_model=FillModel(reject_probability=1.0), audit=log
        )
        order = eng.submit("GLD", {"final_fraction": 0.05}, 100.0, "bullish")
        assert order.status == "rejected"
        assert order.notional == 0.0
        assert eng.portfolio.positions["GLD"].state == PositionState.FLAT
        assert any(r["event"] == "reject" for r in read_audit(log))

    def test_stop_exit_applies_adverse_slippage(self):
        eng = ExecutionEngine(equity=100_000, fill_model=FillModel(slippage_bps=100))
        eng.submit("GLD", {"final_fraction": 0.10}, 100.0, "bullish")
        pos = eng.portfolio.positions["GLD"]
        fills = eng.step(_bar("2025-01-02", 100, 102, 90, 95))
        fill = fills["GLD"]
        assert fill is not None
        assert fill.reason == "stop_loss"
        assert fill.price == pytest.approx(pos.stop_price * 0.99, rel=1e-6)

    def test_signal_exit_applies_slippage(self):
        eng = ExecutionEngine(equity=100_000, fill_model=FillModel(slippage_bps=100))
        eng.submit("GLD", {"final_fraction": 0.10}, 100.0, "bullish")
        fill = eng.exit_position("GLD", 110.0, reason="signal")
        assert fill is not None
        assert fill.price == pytest.approx(110.0 * 0.99, rel=1e-6)


class TestSimulateFills:
    # flat, then a breakout ramp that never breaches the stop
    _RAMP = [100.0] * 10 + [105.0, 110.0, 115.0, 120.0, 126.0, 133.0]

    def test_default_sim_has_no_frictions(self):
        res = simulate_symbol(
            "GLD", _frame(self._RAMP), warmup=6, signal="breakout", entry_window=5, exit_window=3
        )
        assert res.partial_fills == 0
        assert res.rejected_orders == 0

    def test_rejection_blocks_all_entries(self):
        res = simulate_symbol(
            "GLD", _frame(self._RAMP), warmup=6, signal="breakout",
            entry_window=5, exit_window=3, reject_probability=1.0, fill_seed=1,
        )
        assert res.entries == 0
        assert res.rejected_orders > 0

    def test_partial_fills_are_recorded(self):
        res = simulate_symbol(
            "GLD", _frame(self._RAMP, volume=100.0), warmup=6, signal="breakout",
            entry_window=5, exit_window=3, allocation_fraction=0.05,
            equity=100_000.0, participation_rate=0.001,
        )
        assert res.entries >= 1
        assert res.partial_fills >= 1