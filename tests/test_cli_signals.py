"""CLI signal selection: composite exposure and validation (ARTHA-219)."""

import pytest
from typer.testing import CliRunner

from arthaai import cli
from arthaai.backtest.engine import BacktestResult


def _result() -> BacktestResult:
    return BacktestResult("GLD", 100, 10, 0.1, 0.2, 1.0, -0.1, 0.5, 0.1, 0.1)


def test_validate_signal_accepts_known_and_normalizes():
    assert cli._validate_signal("trend") == "trend"
    assert cli._validate_signal("Breakout") == "breakout"
    assert cli._validate_signal(" composite ") == "composite"


def test_validate_signal_rejects_unknown():
    with pytest.raises(cli.typer.Exit):
        cli._validate_signal("momentum")


def test_backtest_cli_passes_composite_signal(monkeypatch):
    captured = {}

    def fake_run_backtest(symbol, **kwargs):
        captured["symbol"] = symbol
        captured.update(kwargs)
        return _result()

    monkeypatch.setattr("arthaai.backtest.run_backtest", fake_run_backtest)
    result = CliRunner().invoke(cli.app, ["backtest", "GLD", "--signal", "composite"])
    assert result.exit_code == 0, result.output
    assert captured["symbol"] == "GLD"
    assert captured["signal"] == "composite"


def test_backtest_cli_rejects_unknown_signal():
    result = CliRunner().invoke(cli.app, ["backtest", "GLD", "--signal", "momentum"])
    assert result.exit_code == 2


def test_backtest_cli_reports_composite_unavailable(monkeypatch):
    def fake_run_backtest(symbol, **kwargs):
        raise ValueError("composite signal unavailable for GLD: no factor series computed")

    monkeypatch.setattr("arthaai.backtest.run_backtest", fake_run_backtest)
    result = CliRunner().invoke(cli.app, ["backtest", "GLD", "--signal", "composite"])
    assert result.exit_code == 1
    assert "composite signal unavailable" in result.output


def test_promote_cli_passes_composite_signal(monkeypatch):
    captured = {}

    class _Eval:
        qualified = False
        reason = "test"

    def fake_promote_windows(symbol, *, signal, **kwargs):
        captured["signal"] = signal
        return False, "note", [(200, 350, _result(), _Eval())], [_Eval()]

    monkeypatch.setattr(cli, "_promote_windows", fake_promote_windows)
    result = CliRunner().invoke(
        cli.app, ["promote", "GLD", "--signal", "composite", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert captured["signal"] == "composite"


def test_promote_cli_rejects_unknown_signal():
    result = CliRunner().invoke(cli.app, ["promote", "GLD", "--signal", "momentum"])
    assert result.exit_code == 2
