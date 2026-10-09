"""Portfolio-level Kelly (ARTHA-309) and dynamic Kelly fraction (ARTHA-311)."""

import numpy as np
import pandas as pd
import pytest

from arthaai.agents import asset_manager as am


class _Settings:
    kelly_fraction = 0.25
    max_single_instrument = 0.05
    risk_free_rate = 0.04
    max_portfolio_exposure = 1.0
    dynamic_kelly = False
    dynamic_kelly_target_vol = 0.15
    kelly_fraction_min = 0.10
    kelly_fraction_max = 0.50
    vol_target = 0.0
    vol_max_leverage = 1.0
    factor_gate = False
    factor_epsilon = 0.0
    factor_dampening = 0.5


def _quant(sigma=0.20):
    return {"mu": 0.10, "variance": 0.04, "sigma": sigma, "win_prob": 0.55, "win_loss_ratio": 1.1}


def _returns(seed=0, n=300, identical=False):
    rng = np.random.default_rng(seed)
    a = rng.normal(0, 0.01, n)
    b = a.copy() if identical else rng.normal(0, 0.01, n)
    idx = pd.date_range("2023-01-01", periods=n, freq="B", tz="UTC")
    return pd.DataFrame({"A": a, "B": b}, index=idx)


class TestDynamicKelly:
    def test_high_vol_shrinks_fraction(self, monkeypatch):
        stub = _Settings()
        stub.dynamic_kelly = True
        monkeypatch.setattr(am, "get_settings", lambda: stub)
        high = am.size(_quant(sigma=0.30))
        low = am.size(_quant(sigma=0.15))
        assert high.kelly_fraction_used < low.kelly_fraction_used
        assert high.final_fraction < low.final_fraction

    def test_fraction_bounded_by_floor_and_ceiling(self, monkeypatch):
        stub = _Settings()
        stub.dynamic_kelly = True
        monkeypatch.setattr(am, "get_settings", lambda: stub)
        assert am.size(_quant(sigma=1.0)).kelly_fraction_used == pytest.approx(0.10)
        assert am.size(_quant(sigma=0.01)).kelly_fraction_used == pytest.approx(0.50)

    def test_disabled_uses_static_fraction(self, monkeypatch):
        monkeypatch.setattr(am, "get_settings", lambda: _Settings())
        assert am.size(_quant()).kelly_fraction_used == pytest.approx(0.25)

    def test_helper_falls_back_without_sigma(self):
        assert am.dynamic_kelly_fraction(None, base=0.25, target_vol=0.15, floor=0.1, ceil=0.5) == 0.25
        assert am.dynamic_kelly_fraction(0.0, base=0.25, target_vol=0.15, floor=0.1, ceil=0.5) == 0.25


class TestPortfolioKelly:
    def test_independent_assets_barely_de_risked(self, monkeypatch):
        monkeypatch.setattr(am, "get_settings", lambda: _Settings())
        alloc = am.portfolio_size({"A": _quant(), "B": _quant()}, _returns(identical=False))
        assert alloc.correlation_multiplier > 0.95
        assert set(alloc.fractions) == {"A", "B"}

    def test_correlated_assets_de_risked(self, monkeypatch):
        monkeypatch.setattr(am, "get_settings", lambda: _Settings())
        alloc = am.portfolio_size({"A": _quant(), "B": _quant()}, _returns(identical=True))
        assert alloc.correlation_multiplier < 0.80
        for sym in ("A", "B"):
            assert alloc.fractions[sym] < alloc.standalone_fractions[sym]

    def test_per_asset_cap_respected(self, monkeypatch):
        monkeypatch.setattr(am, "get_settings", lambda: _Settings())
        alloc = am.portfolio_size({"A": _quant()}, _returns())
        assert alloc.fractions["A"] <= 0.05 + 1e-9

    def test_total_exposure_cap_applied(self, monkeypatch):
        stub = _Settings()
        stub.max_portfolio_exposure = 0.05
        monkeypatch.setattr(am, "get_settings", lambda: stub)
        alloc = am.portfolio_size({"A": _quant(), "B": _quant()}, _returns(identical=False))
        assert alloc.total_exposure <= 0.05 + 1e-9
        assert alloc.capped_by_policy is True

    def test_symbols_without_returns_skipped(self, monkeypatch):
        monkeypatch.setattr(am, "get_settings", lambda: _Settings())
        alloc = am.portfolio_size({"A": _quant(), "ZZ": _quant()}, _returns())
        assert set(alloc.fractions) == {"A"}

    def test_no_assets_returns_empty(self, monkeypatch):
        monkeypatch.setattr(am, "get_settings", lambda: _Settings())
        alloc = am.portfolio_size({"ZZ": _quant()}, _returns())
        assert alloc.fractions == {}
        assert alloc.total_exposure == 0.0