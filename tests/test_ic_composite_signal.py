"""IC-weighted cross-sectional composite signal wiring (ARTHA-219 / E3 step 2)."""

import pandas as pd
import pytest
from typer.testing import CliRunner

from arthaai import cli
from arthaai.backtest.engine import BacktestResult
from arthaai.factors import composite as composite_mod
from arthaai.factors import panel as panel_mod


def _wide() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=4, freq="B", tz="UTC")
    return pd.DataFrame(
        {"AAA": [1.0, 2.0, None, 4.0], "BBB": [4.0, 3.0, 2.0, 1.0]}, index=idx
    )


def test_per_symbol_signals_splits_and_drops_nan():
    signals = composite_mod.per_symbol_signals(_wide())
    assert set(signals) == {"AAA", "BBB"}
    assert len(signals["AAA"]) == 3  # the None row is dropped
    assert list(signals["BBB"]) == [4.0, 3.0, 2.0, 1.0]


def test_per_symbol_signals_empty_is_safe():
    assert composite_mod.per_symbol_signals(pd.DataFrame()) == {}


def test_cross_sectional_signal_map_bridges_panel(monkeypatch):
    monkeypatch.setattr(panel_mod, "build_panel_from_symbols", lambda syms, limit=520: {"close": _wide()})
    monkeypatch.setattr(composite_mod, "ic_weighted_composite", lambda panel, *a, **k: _wide())
    signals = composite_mod.cross_sectional_signal_map(["AAA", "BBB"], limit=100)
    assert set(signals) == {"AAA", "BBB"}


def test_align_signal_to_ohlcv_reindexes_to_loaded_rows(monkeypatch):
    df = pd.DataFrame(
        {
            "ts": pd.date_range("2024-01-01", periods=5, freq="B", tz="UTC"),
            "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
        }
    )
    monkeypatch.setattr("arthaai.db.timescale.load_ohlcv", lambda *a, **k: df)
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=df["ts"].dt.normalize())
    aligned = panel_mod.align_signal_to_ohlcv(series, "AAA", limit=5)
    assert list(aligned.index) == [0, 1, 2, 3, 4]
    assert list(aligned) == [1.0, 2.0, 3.0, 4.0, 5.0]


def _result() -> BacktestResult:
    return BacktestResult("GLD", 200, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def test_promote_windows_passes_signal_series(monkeypatch):
    df = pd.DataFrame(
        {
            "ts": pd.date_range("2024-01-01", periods=200, freq="B", tz="UTC"),
            "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
        }
    )
    monkeypatch.setattr("arthaai.db.timescale.load_ohlcv", lambda *a, **k: df)
    captured = {}

    def fake_run_backtest(symbol, **kwargs):
        captured["signal_series"] = kwargs.get("signal_series")
        return _result()

    monkeypatch.setattr("arthaai.backtest.run_backtest", fake_run_backtest)
    series = pd.Series([1.0] * 200, index=df["ts"].dt.normalize())
    result = cli._promote_windows(
        "GLD", signal="ic_composite", warmup=20, limit=200, adx_threshold=0.0,
        cost_bps=0.0, vol_target=0.0, windows=2, signal_map={"GLD": series},
    )
    assert result is not None
    assert captured["signal_series"] is not None
    assert len(captured["signal_series"]) == 200


def test_validate_signal_accepts_ic_composite():
    assert cli._validate_signal("IC_Composite") == "ic_composite"


def test_promote_cli_passes_ic_composite_signal(monkeypatch):
    captured = {}

    class _Eval:
        qualified = False
        reason = "test"

    def fake_map(symbols, *, limit):
        captured["symbols"] = symbols
        return {"GLD": pd.Series([1.0] * 200)}

    def fake_promote_windows(symbol, *, signal, signal_map=None, **kwargs):
        captured["signal"] = signal
        captured["signal_map"] = signal_map
        return False, "note", [(200, 350, _result(), _Eval())], [_Eval()]

    monkeypatch.setattr(cli, "_ic_composite_signal_map", fake_map)
    monkeypatch.setattr(cli, "_promote_windows", fake_promote_windows)
    result = CliRunner().invoke(
        cli.app, ["promote", "GLD", "--signal", "ic_composite", "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert captured["signal"] == "ic_composite"
    assert captured["signal_map"] is not None


def test_backtest_cli_rejects_unknown_signal_still():
    result = CliRunner().invoke(cli.app, ["backtest", "GLD", "--signal", "nope"])
    assert result.exit_code == 2
