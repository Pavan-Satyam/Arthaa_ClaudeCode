"""Persistent position ledger + live stop/target enforcement (ARTHA-4xx)."""

import pandas as pd
import pytest

from arthaai.execution import PositionLedger
from arthaai.execution.ledger import evaluate_exit, unrealized_pnl


def _bar(low, high, close=None, ts="2025-01-02"):
    close = low if close is None else close
    return pd.Series({"ts": pd.Timestamp(ts, tz="UTC"), "open": close,
                      "high": high, "low": low, "close": close})


class TestLedger:
    def test_open_close_and_replay(self, tmp_path):
        path = tmp_path / "led.jsonl"
        led = PositionLedger(path)
        p = led.open(symbol="gld", side="buy", quantity=10, entry_price=100.0,
                     stop_price=92.0, target_price=115.0)
        assert p.symbol == "GLD"
        assert [x.id for x in led.open_positions()] == [p.id]

        led.close(p.id, exit_price=92.0, reason="stop_loss")
        assert led.open_positions() == []
        # A new instance replays the same state from disk.
        assert PositionLedger(path).get(p.id).status == "closed"

    def test_cache_invalidated_on_new_open(self, tmp_path):
        led = PositionLedger(tmp_path / "led.jsonl")
        first = led.open(symbol="GLD", side="buy", quantity=1, entry_price=100.0, stop_price=95.0)
        assert led.open_positions() == [led.load()[first.id]]
        led.open(symbol="SLV", side="buy", quantity=1, entry_price=10.0, stop_price=9.0)
        assert len(led.open_positions()) == 2

    def test_cannot_close_twice(self, tmp_path):
        led = PositionLedger(tmp_path / "led.jsonl")
        p = led.open(symbol="GLD", side="buy", quantity=1, entry_price=100.0, stop_price=95.0)
        led.close(p.id, exit_price=95.0, reason="stop_loss")
        with pytest.raises(ValueError, match="already closed"):
            led.close(p.id, exit_price=95.0, reason="stop_loss")


class TestEvaluateExit:
    def test_stop_fires(self, tmp_path):
        from arthaai.execution.ledger import OpenPosition

        p = OpenPosition(id="x", symbol="GLD", side="buy", quantity=10,
                         entry_price=100.0, stop_price=92.0, target_price=115.0)
        fill = evaluate_exit(p, _bar(low=90.0, high=101.0))
        assert fill is not None and fill.reason == "stop_loss" and fill.price == 92.0

    def test_target_fires(self, tmp_path):
        from arthaai.execution.ledger import OpenPosition

        p = OpenPosition(id="x", symbol="GLD", side="buy", quantity=10,
                         entry_price=100.0, stop_price=92.0, target_price=115.0)
        fill = evaluate_exit(p, _bar(low=99.0, high=116.0))
        assert fill is not None and fill.reason == "target" and fill.price == 115.0

    def test_held_when_no_breach(self):
        from arthaai.execution.ledger import OpenPosition

        p = OpenPosition(id="x", symbol="GLD", side="buy", quantity=10,
                         entry_price=100.0, stop_price=92.0, target_price=115.0)
        assert evaluate_exit(p, _bar(low=99.0, high=101.0)) is None

    def test_unrealized_pnl(self):
        from arthaai.execution.ledger import OpenPosition

        p = OpenPosition(id="x", symbol="GLD", side="buy", quantity=10,
                         entry_price=100.0, stop_price=92.0)
        assert unrealized_pnl(p, 105.0) == pytest.approx(50.0)


class TestExecuteExposureGuard:
    def _stub_analyze(self):
        return {
            "verdict": {"direction": "bullish"},
            "allocation": {"final_fraction": 0.05, "rationale": "test"},
            "db": {"last_close": 100.0},
        }

    def test_exposure_cap_blocks_when_exceeded(self, monkeypatch, tmp_path):
        from typer.testing import CliRunner

        from arthaai.cli import app

        led = tmp_path / "led.jsonl"
        PositionLedger(led).open(symbol="SPY", side="buy", quantity=990,
                                  entry_price=100.0, stop_price=90.0)  # $99k open
        monkeypatch.setattr(
            "arthaai.orchestration.analyze", lambda symbol, skip_ingest=False: self._stub_analyze()
        )
        result = CliRunner().invoke(
            app, ["execute", "GLD", "--equity", "100000", "--ledger", str(led)]
        )
        assert result.exit_code == 1
        assert "exposure" in result.output.lower()

    def test_exposure_cap_force_overrides(self, monkeypatch, tmp_path):
        from typer.testing import CliRunner

        from arthaai.cli import app

        led = tmp_path / "led.jsonl"
        PositionLedger(led).open(symbol="SPY", side="buy", quantity=990,
                                  entry_price=100.0, stop_price=90.0)
        monkeypatch.setattr(
            "arthaai.orchestration.analyze", lambda symbol, skip_ingest=False: self._stub_analyze()
        )
        result = CliRunner().invoke(
            app, ["execute", "GLD", "--equity", "100000", "--ledger", str(led), "--force"]
        )
        assert result.exit_code == 0


class TestMarkCli:
    def test_mark_fires_stop_via_price_override(self, tmp_path):
        from typer.testing import CliRunner

        from arthaai.cli import app

        path = tmp_path / "led.jsonl"
        PositionLedger(path).open(symbol="GLD", side="buy", quantity=10,
                                  entry_price=100.0, stop_price=95.0)
        result = CliRunner().invoke(app, ["mark", str(path), "--price", "GLD=94"])
        assert result.exit_code == 0
        assert PositionLedger(path).open_positions() == []

    def test_mark_holds_when_no_breach(self, tmp_path):
        from typer.testing import CliRunner

        from arthaai.cli import app

        path = tmp_path / "led.jsonl"
        PositionLedger(path).open(symbol="GLD", side="buy", quantity=10,
                                  entry_price=100.0, stop_price=95.0)
        result = CliRunner().invoke(app, ["mark", str(path), "--price", "GLD=101"])
        assert result.exit_code == 0
        assert len(PositionLedger(path).open_positions()) == 1