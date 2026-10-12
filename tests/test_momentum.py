"""Classic momentum signal family (tsmom / xsmom)."""

import numpy as np
import pandas as pd
import pytest

from arthaai.factors import momentum
from arthaai.factors import panel as panel_mod


def _close() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=4, freq="B", tz="UTC")
    return pd.DataFrame(
        {"AAA": [100.0, 110.0, 121.0, 133.1], "BBB": [100.0, 99.0, 98.01, 97.03]},
        index=idx,
    )


def test_trailing_return():
    tr = momentum.trailing_return(_close(), 1)
    assert np.isnan(tr["AAA"].iloc[0])
    assert tr["AAA"].iloc[1] == pytest.approx(0.10)
    assert tr["BBB"].iloc[1] == pytest.approx(-0.01)


def test_time_series_momentum_signal():
    sig = momentum.time_series_momentum_signal(_close(), 1)
    assert np.isnan(sig["AAA"].iloc[0])  # undefined before the lookback
    assert sig["AAA"].iloc[1:].tolist() == [1.0, 1.0, 1.0]
    assert sig["BBB"].iloc[1:].tolist() == [0.0, 0.0, 0.0]


def test_cross_sectional_momentum_signal_top_quantile():
    sig = momentum.cross_sectional_momentum_signal(_close(), 1, top_quantile=0.5)
    assert np.isnan(sig["AAA"].iloc[0])
    assert sig["AAA"].iloc[1:].tolist() == [1.0, 1.0, 1.0]  # top performer
    assert sig["BBB"].iloc[1:].tolist() == [0.0, 0.0, 0.0]


def test_cross_sectional_momentum_signal_rejects_bad_quantile():
    with pytest.raises(ValueError):
        momentum.cross_sectional_momentum_signal(_close(), 1, top_quantile=0.0)


def test_momentum_signal_map_bridges_panel(monkeypatch):
    monkeypatch.setattr(panel_mod, "build_panel_from_symbols", lambda syms, limit=520: {"close": _close()})
    signals = momentum.momentum_signal_map(["AAA", "BBB"], kind="tsmom", lookback=1, limit=100)
    assert set(signals) == {"AAA", "BBB"}
    assert signals["AAA"].iloc[-1] == 1.0


def test_momentum_signal_map_rejects_unknown_kind():
    with pytest.raises(ValueError):
        momentum.momentum_signal_map(["AAA"], kind="nope", lookback=1)
