"""Macro term-spread regime signals and keyless FRED CSV parsing."""

import numpy as np
import pandas as pd
import pytest

from arthaai.data import macro_series
from arthaai.factors import macro_regime as mr
from arthaai.factors import panel as panel_mod


def _close(periods: int = 60) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=periods, freq="B", tz="UTC")
    return pd.DataFrame(
        {"AAA": np.linspace(10, 20, periods), "BBB": np.linspace(20, 10, periods)}, index=idx
    )


def test_macro_regime_is_binary_and_uses_spread_sign():
    idx = pd.date_range("2020-01-01", periods=5, freq="B", tz="UTC")
    ts = pd.Series([-1.0, -0.5, 0.1, 0.5, 1.0], index=idx)
    regime = mr.macro_regime(idx, term_spread=ts)
    assert regime.tolist() == [0.0, 0.0, 1.0, 1.0, 1.0]


def test_macro_regime_ffills_onto_business_dates():
    idx = pd.date_range("2020-01-01", periods=4, freq="B", tz="UTC")
    ts = pd.Series([0.2], index=pd.DatetimeIndex(["2020-01-01"], tz="UTC"))
    regime = mr.macro_regime(idx, term_spread=ts)
    assert regime.tolist() == [1.0, 1.0, 1.0, 1.0]  # carried forward


def test_macro_signal_map_broadcasts(monkeypatch):
    close = _close()
    monkeypatch.setattr(
        panel_mod, "build_panel_from_symbols", lambda syms, limit=520: {"close": close}
    )
    ts = pd.Series(np.linspace(-1, 1, len(close)), index=close.index)
    signals = mr.macro_signal_map(["AAA"], kind="macro", term_spread=ts, limit=60)
    assert set(signals) == {"AAA", "BBB"}
    assert signals["AAA"].equals(signals["BBB"])
    assert set(signals["AAA"].unique()).issubset({0.0, 1.0})


def test_macro_signal_map_gates_tsmom(monkeypatch):
    close = _close()
    monkeypatch.setattr(
        panel_mod, "build_panel_from_symbols", lambda syms, limit=520: {"close": close}
    )
    ts = pd.Series(np.linspace(-1, 1, len(close)), index=close.index)
    signals = mr.macro_signal_map(["AAA"], kind="macro_tsmom", lookback=5, term_spread=ts, limit=60)
    assert set(signals["AAA"].dropna().unique()).issubset({0.0, 1.0})


def test_macro_signal_map_rejects_unknown_kind():
    with pytest.raises(ValueError):
        mr.macro_signal_map(["AAA"], kind="nope")


def test_fred_series_parses_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(macro_series, "_CACHE", tmp_path)
    (tmp_path / "T10Y2Y.csv").write_text(
        "observation_date,T10Y2Y\n2020-01-01,0.10\n2020-01-02,.\n2020-01-03,0.20\n",
        encoding="utf-8",
    )
    series = macro_series.fred_series("T10Y2Y")
    assert list(series.values) == [0.10, 0.20]
    assert series.index[0] == pd.Timestamp("2020-01-01", tz="UTC")


_MAINTENANCE_PAGE = "<!doctype html>\n<html><title>Site Maintenance | St. Louis Fed</title></html>\n"
_VALID_CSV = "observation_date,T10Y2Y\n2020-01-01,0.10\n2020-01-03,0.20\n"


class _Resp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


def test_fred_series_rejects_html_and_caches_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(macro_series, "_CACHE", tmp_path)
    monkeypatch.setattr(macro_series.httpx, "get", lambda *a, **k: _Resp(_MAINTENANCE_PAGE))
    with pytest.raises(ValueError, match="non-CSV"):
        macro_series.fred_series("T10Y2Y")
    assert not (tmp_path / "T10Y2Y.csv").exists()


def test_fred_series_discards_a_poisoned_cache_and_refetches(monkeypatch, tmp_path):
    monkeypatch.setattr(macro_series, "_CACHE", tmp_path)
    (tmp_path / "T10Y2Y.csv").write_text(_MAINTENANCE_PAGE, encoding="utf-8")
    monkeypatch.setattr(macro_series.httpx, "get", lambda *a, **k: _Resp(_VALID_CSV))
    series = macro_series.fred_series("T10Y2Y")
    assert list(series.values) == [0.10, 0.20]
    assert (tmp_path / "T10Y2Y.csv").read_text(encoding="utf-8") == _VALID_CSV
