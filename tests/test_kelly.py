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
