"""SEC EDGAR point-in-time fundamentals (value/quality axis)."""

import numpy as np
import pandas as pd

from arthaai.data import fundamentals_pit as fp


def _obs(rows):
    frame = pd.DataFrame(rows, columns=["end", "val", "filed", "form"])
    frame["filed"] = pd.to_datetime(frame["filed"], utc=True)
    frame["end"] = pd.to_datetime(frame["end"], utc=True)
    return frame


def test_pit_latest_uses_only_filed_facts():
    obs = _obs(
        [
            ("2019-12-31", 100.0, "2020-02-15", "10-K"),
            ("2020-03-31", 120.0, "2020-05-01", "10-Q"),
        ]
    )
    dates = pd.to_datetime(["2020-03-01", "2020-06-01"], utc=True)
    s = fp.pit_latest(obs, dates)
    assert s.iloc[0] == 100.0  # only the February filing is available
    assert s.iloc[1] == 120.0  # the May filing is now available


def test_pit_latest_prefers_annual():
    obs = _obs(
        [
            ("2019-12-31", 100.0, "2020-02-15", "10-K"),
            ("2020-03-31", 30.0, "2020-05-01", "10-Q"),
        ]
    )
    dates = pd.to_datetime(["2020-06-01"], utc=True)
    assert fp.pit_latest(obs, dates, prefer_annual=True).iloc[0] == 100.0
    assert fp.pit_latest(obs, dates, prefer_annual=False).iloc[0] == 30.0


def test_pit_latest_empty_is_nan():
    s = fp.pit_latest(pd.DataFrame(columns=["end", "val", "filed", "form"]), ["2020-06-01"])
    assert np.isnan(s.iloc[0])


def _fetcher(cik, tag, taxonomy="us-gaap"):
    value = {
        "StockholdersEquity": 100.0,
        "NetIncomeLoss": 10.0,
        "EntityCommonStockSharesOutstanding": 5.0,
    }[tag]
    return _obs([("2019-12-31", value, "2019-06-01", "10-K")])


def test_value_signal_map_builds_binary_signals(monkeypatch):
    idx = pd.date_range("2020-01-01", periods=10, freq="MS", tz="UTC")
    close = pd.DataFrame(
        {"AAA": np.linspace(10, 20, 10), "BBB": np.linspace(20, 10, 10)}, index=idx
    )
    monkeypatch.setattr(
        "arthaai.factors.panel.build_panel_from_symbols",
        lambda syms, limit=520: {"close": close},
    )
    signals = fp.value_signal_map(
        ["AAA", "BBB"],
        cik_map={"AAA": "0000000001", "BBB": "0000000002"},
        concept_fetcher=_fetcher,
        top_quantile=0.5,
    )
    assert set(signals) == {"AAA", "BBB"}
    for series in signals.values():
        assert set(series.dropna().unique()).issubset({0.0, 1.0})


def test_value_signal_map_skips_symbols_without_cik(monkeypatch):
    idx = pd.date_range("2020-01-01", periods=5, freq="MS", tz="UTC")
    close = pd.DataFrame({"AAA": np.linspace(10, 20, 5)}, index=idx)
    monkeypatch.setattr(
        "arthaai.factors.panel.build_panel_from_symbols",
        lambda syms, limit=520: {"close": close},
    )
    signals = fp.value_signal_map(["AAA"], cik_map={}, concept_fetcher=_fetcher)
    assert signals == {}
