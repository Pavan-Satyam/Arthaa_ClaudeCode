"""Volatility targeting (C) in the deterministic sizing layer."""

import pytest

from arthaai.agents import asset_manager as am

_LONG = {"mu": 0.10, "variance": 0.04, "sigma": 0.20, "win_prob": 0.55, "win_loss_ratio": 1.1}


def test_disabled_by_default_leaves_size_unchanged():
    base = am.size(_LONG)
    off = am.size(_LONG, vol_target=0.0)
    assert off.vol_multiplier == 1.0
    assert off.final_fraction == pytest.approx(base.final_fraction)


def test_high_vol_is_de_risked_toward_target():
    base = am.size(_LONG, vol_target=0.0)
    targeted = am.size(_LONG, vol_target=0.10, vol_max_leverage=1.0)
    assert targeted.vol_multiplier == pytest.approx(0.5)  # 0.10 / 0.20
    assert targeted.final_fraction == pytest.approx(base.final_fraction * 0.5, abs=1e-4)
    assert "vol target" in targeted.rationale


def test_low_vol_does_not_lever_by_default():
    q = {**_LONG, "sigma": 0.05}
    a = am.size(q, vol_target=0.10, vol_max_leverage=1.0)
    assert a.vol_multiplier == pytest.approx(1.0)  # ratio 2.0 capped at 1.0


def test_low_vol_levers_when_configured():
    q = {**_LONG, "sigma": 0.05}
    a = am.size(q, vol_target=0.10, vol_max_leverage=2.0)
    assert a.vol_multiplier == pytest.approx(2.0)


def test_no_sigma_disables_scaling():
    q = {"mu": 0.10, "variance": 0.04, "win_prob": 0.55, "win_loss_ratio": 1.1}
    a = am.size(q, vol_target=0.10)
    assert a.vol_multiplier == 1.0


def test_scaled_size_still_respects_policy_cap():
    strong = {"mu": 0.5, "variance": 0.01, "sigma": 0.10,
              "win_prob": 0.9, "win_loss_ratio": 5}
    a = am.size(strong, vol_target=0.05, vol_max_leverage=1.0)
    assert a.final_fraction <= 0.05 + 1e-9
