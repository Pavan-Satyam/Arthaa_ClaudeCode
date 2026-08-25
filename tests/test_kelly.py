"""Asset Manager — Kelly math and the deterministic policy override."""

import pytest

from arthaai.agents import asset_manager as am


def test_discrete_kelly_matches_formula():
    # f = W - (1-W)/R ; W=0.6, R=2 -> 0.6 - 0.4/2 = 0.4
    assert am.discrete_kelly(0.6, 2.0) == pytest.approx(0.4)


def test_continuous_kelly_matches_formula():
    # f* = (mu - r)/sigma^2 ; (0.10-0.04)/0.04 = 1.5
    assert am.continuous_kelly(0.10, 0.04, 0.04) == pytest.approx(1.5)


def test_negative_edge_yields_zero_discrete():
    assert am.discrete_kelly(0.3, 1.0) <= 0  # losing edge


def test_policy_cap_overrides_model(monkeypatch):
    # A wildly favourable stat set would size huge; the 5% cap must win.
    quant = {"mu": 0.5, "variance": 0.01, "win_prob": 0.9, "win_loss_ratio": 5}
    alloc = am.size(quant)
    assert alloc.final_fraction <= 0.05 + 1e-9
    assert alloc.capped_by_policy is True


def test_fraction_never_exceeds_policy_even_at_confidence_1():
    quant = {"mu": 1.0, "variance": 0.02, "win_prob": 0.8, "win_loss_ratio": 3}
    alloc = am.size(quant, confidence=1.0)
    assert 0.0 <= alloc.final_fraction <= 0.05 + 1e-9


def test_discrete_kelly_drives_sizing_under_cap():
    # A realistic directional edge: W=0.55, R=1.1 -> discrete f=0.141, quarter=0.035.
    # Continuous Kelly with these annualised stats would be huge, but it must NOT
    # drive sizing — discrete Kelly alone sets the sub-cap fraction.
    quant = {"mu": 0.10, "variance": 0.04, "win_prob": 0.55, "win_loss_ratio": 1.1}
    alloc = am.size(quant)
    expected = am.discrete_kelly(0.55, 1.1) * 0.25  # quarter-Kelly, no cap
    assert alloc.final_fraction == pytest.approx(expected, abs=1e-4)  # rounded to 4dp
    assert alloc.capped_by_policy is False
    # Continuous Kelly is large but informational only — it did not set the size.
    assert alloc.continuous_kelly > alloc.final_fraction


def test_no_edge_sizes_zero():
    # W=0.5, R=1.0 -> discrete f = 0.5 - 0.5/1.0 = 0. Position is flat even though
    # continuous Kelly (mu=0.5, var=0.01 -> 46) would have pumped leverage.
    quant = {"mu": 0.5, "variance": 0.01, "win_prob": 0.5, "win_loss_ratio": 1.0}
    alloc = am.size(quant)
    assert alloc.final_fraction == pytest.approx(0.0, abs=1e-9)
    assert alloc.continuous_kelly > 1.0  # would have dominated under the old logic


def test_negative_edge_sizes_zero():
    # A losing signal (W=0.4, R=0.8) -> negative discrete Kelly -> flat, no shorting.
    quant = {"mu": 0.2, "variance": 0.03, "win_prob": 0.4, "win_loss_ratio": 0.8}
    alloc = am.size(quant)
    assert alloc.final_fraction == pytest.approx(0.0, abs=1e-9)
