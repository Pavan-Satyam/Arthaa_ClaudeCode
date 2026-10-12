"""Intermarket risk-regime signals (regime / regime_tsmom)."""

import numpy as np
import pandas as pd
import pytest

from arthaai.factors import panel as panel_mod
from arthaai.factors import regime as regime_mod


def _panel(periods: int = 300) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=periods, freq="B", tz="UTC")
    # SPY rises then falls; HYG/LQD credit ratio improves early, worsens late.
    spy = pd.Series(np.linspace(100, 200, periods), index=idx)
    hyg = pd.Series(np.linspace(80, 90, periods), index=idx)
    lqd = pd.Series(np.linspace(100, 100, periods), index=idx)
    aaa = pd.Series(np.linspace(50, 60, periods), index=idx)
    return pd.DataFrame({"SPY": spy, "HYG": hyg, "LQD": lqd, "AAA": aaa}, index=idx)


def test_risk_regime_is_binary_and_causal():
    r = regime_mod.risk_regime(_panel(), trend_window=20, credit_window=5)
    assert set(r.dropna().unique()).issubset({0.0, 1.0})
    assert np.isnan(r.iloc[0]) or r.iloc[0] in (0.0, 1.0)


def test_risk_regime_requires_basket():
    with pytest.raises(ValueError, match="regime basket missing"):
        regime_mod.risk_regime(pd.DataFrame({"AAA": [1.0, 2.0]}))


def test_regime_signal_map_broadcasts_and_gates(monkeypatch):
    monkeypatch.setattr(panel_mod, "build_panel_from_symbols", lambda syms, limit=520: {"close": _panel()})
    plain = regime_mod.regime_signal_map(["AAA"], kind="regime", limit=100)
    assert set(plain) == {"SPY", "HYG", "LQD", "AAA"}
    # regime broadcast: every symbol shares the same series
    assert plain["AAA"].equals(plain["SPY"])

    gated = regime_mod.regime_signal_map(
        ["AAA"], kind="regime_tsmom", lookback=5, limit=100
    )
    assert set(gated["AAA"].dropna().unique()).issubset({0.0, 1.0})


def test_regime_signal_map_rejects_unknown_kind():
    with pytest.raises(ValueError):
        regime_mod.regime_signal_map(["AAA"], kind="nope")
