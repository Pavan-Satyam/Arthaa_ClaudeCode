"""Every CLI signal must reach the gate as itself — never as a silent trend fallback."""

import pandas as pd
import pytest
from typer.testing import CliRunner

from arthaai import cli
from arthaai.backtest import engine
from arthaai.backtest.engine import ENGINE_SIGNALS, BacktestResult

PANEL_SIGNALS = [s for s in cli.VALID_SIGNALS if s not in ENGINE_SIGNALS]

_BUILDERS = [
    "arthaai.factors.composite.cross_sectional_signal_map",
    "arthaai.factors.momentum.momentum_signal_map",
    "arthaai.factors.regime.regime_signal_map",
    "arthaai.data.fundamentals_pit.value_signal_map",
    "arthaai.factors.macro_regime.macro_signal_map",
    "arthaai.factors.exogenous.cftc_signal_map",
    "arthaai.factors.exogenous.eia_signal_map",
    "arthaai.factors.exogenous.insider_signal_map",
    "arthaai.factors.exogenous.vix_regime_signal_map",
    "arthaai.factors.xgb_signal.xgb_signal_map",
]


def _result(sharpe: float = 1.0) -> BacktestResult:
    return BacktestResult(
        symbol="GLD", bars=150, trades=10, total_return=0.1, buy_hold_return=0.2,
        sharpe=sharpe, max_drawdown=-0.1, hit_rate=0.5, long_short_return=0.1,
        long_only_return=0.1,
    )


class _Eval:
    qualified = False
    reason = "test"


def _fake_windows(captured: dict):
    def fake(symbol, *, signal, signal_map=None, **kwargs):
        captured["signal"] = signal
        captured["signal_map"] = signal_map
        rows = [(350, 500, _result(2.0), _Eval()), (200, 350, _result(-0.5), _Eval())]
        return False, "note", rows, [_Eval(), _Eval()]

    return fake


def test_engine_and_panel_signals_partition_valid_signals():
    assert set(ENGINE_SIGNALS) <= set(cli.VALID_SIGNALS)
    assert PANEL_SIGNALS, "expected panel signals beyond the engine's own"


@pytest.mark.parametrize("signal", PANEL_SIGNALS)
def test_signal_map_for_routes_every_panel_signal(monkeypatch, signal):
    monkeypatch.setattr(cli, "_expand_universe", lambda symbols: list(symbols))
    for path in _BUILDERS:
        monkeypatch.setattr(path, lambda *a, **k: {"GLD": pd.Series([1.0])})
    assert cli._signal_map_for(signal, ["GLD"], limit=10) is not None


@pytest.mark.parametrize("signal", PANEL_SIGNALS)
def test_promote_sweep_builds_a_map_for_every_panel_signal(monkeypatch, signal):
    captured: dict = {}
    monkeypatch.setattr(cli, "_signal_map_for", lambda *a, **k: {"GLD": pd.Series([1.0])})
    monkeypatch.setattr(cli, "_promote_windows", _fake_windows(captured))
    result = CliRunner().invoke(
        cli.app, ["promote-sweep", "--symbols", "GLD", "--signal", signal, "--no-save"]
    )
    assert result.exit_code == 0, result.output
    assert captured["signal_map"] is not None


@pytest.mark.parametrize("signal", ENGINE_SIGNALS)
def test_promote_sweep_leaves_engine_signals_to_the_engine(monkeypatch, signal):
    captured: dict = {}
    monkeypatch.setattr(cli, "_promote_windows", _fake_windows(captured))
    result = CliRunner().invoke(
        cli.app, ["promote-sweep", "--symbols", "GLD", "--signal", signal, "--no-save"]
    )
    assert result.exit_code == 0, result.output
    assert captured["signal_map"] is None


def test_promote_sweep_shows_bars_evaluated_and_limit(monkeypatch):
    monkeypatch.setattr(cli, "_promote_windows", _fake_windows({}))
    result = CliRunner().invoke(
        cli.app,
        ["promote-sweep", "--symbols", "GLD", "--signal", "trend", "--limit", "500", "--no-save"],
    )
    assert result.exit_code == 0, result.output
    assert "Bars" in result.output and "500" in result.output
    assert "--limit 500" in result.output


@pytest.mark.parametrize("signal", PANEL_SIGNALS)
def test_backtest_cli_passes_a_series_for_every_panel_signal(monkeypatch, signal):
    captured: dict = {}
    series = pd.Series([1.0, -1.0])
    monkeypatch.setattr(cli, "_signal_map_for", lambda *a, **k: {"GLD": series})
    monkeypatch.setattr(
        "arthaai.factors.panel.align_signal_to_ohlcv", lambda column, symbol, limit: column
    )

    def fake_run_backtest(symbol, **kwargs):
        captured.update(kwargs)
        return _result()

    monkeypatch.setattr("arthaai.backtest.run_backtest", fake_run_backtest)
    result = CliRunner().invoke(cli.app, ["backtest", "GLD", "--signal", signal])
    assert result.exit_code == 0, result.output
    assert captured["signal_series"] is not None


@pytest.mark.parametrize("command", [["promote-sweep", "--symbols", "GLD", "--no-save"],
                                     ["backtest", "GLD"], ["promote", "GLD", "--dry-run"]])
def test_missing_signal_inputs_fail_with_a_clear_message(monkeypatch, command):
    def missing(*a, **k):
        raise ValueError("regime basket missing from panel: ['SPY']")

    monkeypatch.setattr(cli, "_signal_map_for", missing)
    result = CliRunner().invoke(cli.app, [*command, "--signal", "regime"])
    assert result.exit_code == 1
    assert "regime signal unavailable" in result.output
    assert "Traceback" not in result.output


def test_backtest_cli_reports_unavailable_when_no_map(monkeypatch):
    monkeypatch.setattr(cli, "_signal_map_for", lambda *a, **k: None)
    result = CliRunner().invoke(cli.app, ["backtest", "GLD", "--signal", "regime"])
    assert result.exit_code == 1
    assert "regime unavailable" in result.output


@pytest.mark.parametrize("signal", PANEL_SIGNALS)
def test_run_backtest_refuses_panel_signal_without_series(monkeypatch, signal):
    def no_db(*a, **k):
        raise AssertionError("must fail before loading data")

    monkeypatch.setattr(engine.timescale, "load_ohlcv", no_db)
    with pytest.raises(ValueError, match="needs a precomputed signal_series"):
        engine.run_backtest("GLD", signal=signal)


def test_promote_reports_and_persists_the_most_recent_window(monkeypatch):
    persisted: dict = {}
    monkeypatch.setattr(cli, "_promote_windows", _fake_windows({}))
    monkeypatch.setattr(
        "arthaai.db.timescale.upsert_signal_promotion", lambda **k: persisted.update(k)
    )
    result = CliRunner().invoke(cli.app, ["promote", "GLD"])
    assert result.exit_code == 0, result.output
    assert "most recent window 350–500" in result.output
    assert persisted["sharpe"] == 2.0


def test_warn_short_history_helper_thresholds():
    assert cli._warn_short_history(cli.E3_MIN_BARS - 1, 3100, context="GLD") is True
    assert cli._warn_short_history(cli.E3_MIN_BARS, 3100, context="GLD") is False


def test_promote_sweep_warns_on_short_stored_history(monkeypatch):
    # _fake_windows tops out at 500 bars (< the ~10y E3 minimum), so the sweep must
    # warn even though --limit is large: load_ohlcv cannot pad a shallow table.
    monkeypatch.setattr(cli, "_promote_windows", _fake_windows({}))
    result = CliRunner().invoke(
        cli.app, ["promote-sweep", "--symbols", "GLD", "--signal", "trend", "--no-save"]
    )
    assert result.exit_code == 0, result.output
    assert "warning" in result.output.lower()
    assert str(cli.E3_MIN_BARS) in result.output
