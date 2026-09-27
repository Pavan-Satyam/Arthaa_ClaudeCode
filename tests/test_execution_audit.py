"""Audit-log persistence, kill switch, and day-reset for the paper engine."""

import pandas as pd
import pytest

from arthaai.execution import (
    ExecutionEngine,
    Fill,
    PortfolioState,
    Position,
    PositionState,
    read_audit,
)


def _bar(ts, o, h, l, c):
    return pd.Series({"ts": pd.Timestamp(ts), "open": o, "high": h, "low": l, "close": c})


def _fill(ts, price=100.0, qty=10.0, sym="GLD"):
    return Fill(ts=pd.Timestamp(ts), symbol=sym, side="buy", quantity=qty, price=price)


class TestAuditLogPersistence:
    def test_order_is_persisted_and_survives_restart(self, tmp_path):
        log = tmp_path / "audit.jsonl"
        e = ExecutionEngine(initial_equity=100_000.0, audit=log)
        e.submit(
            "GLD", {"final_fraction": 0.05}, last_price=100.0, direction="bullish",
            ts=pd.Timestamp("2025-01-01"),
        )
        records = read_audit(log)  # a fresh reader == a process restart
        assert len(records) == 1
        assert records[0]["event"] == "order"
        assert records[0]["symbol"] == "GLD"
        assert records[0]["side"] == "buy"
        assert records[0]["paper"] is True

    def test_audit_log_is_append_only_across_sessions(self, tmp_path):
        log = tmp_path / "audit.jsonl"
        ExecutionEngine(initial_equity=100_000.0, audit=log).submit(
            "GLD", {"final_fraction": 0.05}, last_price=100.0, direction="bullish",
            ts=pd.Timestamp("2025-01-01"),
        )
        ExecutionEngine(initial_equity=100_000.0, audit=log).submit(
            "SLV", {"final_fraction": 0.05}, last_price=50.0, direction="bullish",
            ts=pd.Timestamp("2025-01-02"),
        )
        assert [r["symbol"] for r in read_audit(log)] == ["GLD", "SLV"]

    def test_fill_is_logged_with_stop_reason(self, tmp_path):
        log = tmp_path / "audit.jsonl"
        e = ExecutionEngine(initial_equity=100_000.0, audit=log)
        e.submit(
            "GLD", {"final_fraction": 0.10}, last_price=100.0, direction="bullish",
            ts=pd.Timestamp("2025-01-01"),
        )
        e.step(_bar("2025-01-02", 100, 102, 90, 95))  # low 90 <= stop 92 -> stop out
        fills = [r for r in read_audit(log) if r["event"] == "fill"]
        assert fills and fills[0]["reason"] == "stop_loss"

    def test_breaker_trip_is_logged(self, tmp_path):
        log = tmp_path / "audit.jsonl"
        e = ExecutionEngine(
            initial_equity=100_000.0, drawdown_trigger=0.10, drawdown_lookback=2, audit=log
        )
        e.portfolio.positions["GLD"] = Position(symbol="GLD")
        e.portfolio.positions["GLD"].open(_fill("2025-01-01", qty=1000.0), stop_price=50.0)
        e.portfolio.record_entry_equity(1000.0, 100.0)
        e.mark_equity(80_000.0)  # -20% peak-to-trough -> trip
        assert e.portfolio.state == PortfolioState.DRAWDOWN_BREAKER
        assert any(r["event"] == "breaker" for r in read_audit(log))

    def test_no_audit_means_no_files_written(self, tmp_path):
        e = ExecutionEngine(initial_equity=100_000.0)
        e.submit(
            "GLD", {"final_fraction": 0.05}, last_price=100.0, direction="bullish",
            ts=pd.Timestamp("2025-01-01"),
        )
        assert list(tmp_path.iterdir()) == []


class TestEngineKillSwitch:
    def test_kill_switch_flattens_and_locks(self, tmp_path):
        log = tmp_path / "audit.jsonl"
        e = ExecutionEngine(initial_equity=100_000.0, audit=log)
        e.submit(
            "GLD", {"final_fraction": 0.10}, last_price=100.0, direction="bullish",
            ts=pd.Timestamp("2025-01-01"),
        )
        fills = e.kill_switch({"GLD": 105.0})
        assert "GLD" in fills
        assert e.portfolio.positions["GLD"].state == PositionState.CLOSED
        assert e.portfolio.state == PortfolioState.SYSTEM_LOCKED
        assert not e.portfolio.is_buyable()
        assert any(r["event"] == "kill_switch" for r in read_audit(log))

    def test_kill_switch_blocks_new_orders_until_unlock(self):
        e = ExecutionEngine(initial_equity=100_000.0)
        e.submit(
            "GLD", {"final_fraction": 0.05}, last_price=100.0, direction="bullish",
            ts=pd.Timestamp("2025-01-01"),
        )
        e.kill_switch({"GLD": 100.0})
        from arthaai.execution import TradingHalted

        with pytest.raises(TradingHalted):
            e.submit(
                "SLV", {"final_fraction": 0.05}, last_price=50.0, direction="bullish",
                ts=pd.Timestamp("2025-01-02"),
            )
        e.unlock()
        order = e.submit(
            "SLV", {"final_fraction": 0.05}, last_price=50.0, direction="bullish",
            ts=pd.Timestamp("2025-01-03"),
        )
        assert order.symbol == "SLV"


class TestSignalExit:
    def test_exit_position_credits_proceeds_and_logs(self, tmp_path):
        log = tmp_path / "audit.jsonl"
        e = ExecutionEngine(initial_equity=100_000.0, audit=log)
        e.submit(
            "GLD", {"final_fraction": 0.10}, last_price=100.0, direction="bullish",
            ts=pd.Timestamp("2025-01-01"),
        )
        cash_after_entry = e.portfolio.cash
        fill = e.exit_position("GLD", 110.0, ts=pd.Timestamp("2025-01-02"), reason="signal")
        assert fill is not None
        assert e.portfolio.positions["GLD"].state == PositionState.CLOSED
        assert e.portfolio.cash > cash_after_entry
        rec = [r for r in read_audit(log) if r["event"] == "fill"][-1]
        assert rec["reason"] == "signal"

    def test_exit_position_noop_when_flat(self):
        e = ExecutionEngine(initial_equity=100_000.0)
        assert e.exit_position("GLD", 110.0) is None
