"""Alpha-Zoo factor gate (E2) — deterministic, dampen-only sizing coupling."""

import pytest

from arthaai.agents import asset_manager as am


# d_kelly = 0.55 - 0.45/1.1 = 0.1409 -> quarter-Kelly = 0.03523 (below the 5% cap)
_LONG_QUANT = {"mu": 0.10, "variance": 0.04, "win_prob": 0.55, "win_loss_ratio": 1.1}


def _with_signal(signal, **extra):
    return {**_LONG_QUANT, "factor_signal": signal, **extra}


def test_absent_factor_signal_leaves_size_unchanged():
    ungated = am.size(_LONG_QUANT)
    gated = am.size(_LONG_QUANT, factor_gate=True)
    assert gated.final_fraction == pytest.approx(ungated.final_fraction)
    assert gated.factor_multiplier == 1.0
    assert gated.factor_signal is None


def test_conflicting_factor_dampens_long():
    ungated = am.size(_LONG_QUANT)
    gated = am.size(_with_signal(-1.0))
    assert gated.factor_multiplier == pytest.approx(0.5)
    assert gated.final_fraction == pytest.approx(ungated.final_fraction * 0.5, abs=1e-4)
    assert "conflicts" in gated.rationale


def test_confirming_factor_never_amplifies():
    ungated = am.size(_LONG_QUANT)
    gated = am.size(_with_signal(+1.0))
    assert gated.factor_multiplier == 1.0
    assert gated.final_fraction == pytest.approx(ungated.final_fraction)
    assert "confirms" in gated.rationale


def test_gate_can_be_disabled_explicitly():
    ungated = am.size(_LONG_QUANT)
    off = am.size(_with_signal(-1.0), factor_gate=False)
    assert off.final_fraction == pytest.approx(ungated.final_fraction)
    assert off.factor_multiplier == 1.0


def test_dampened_size_still_respects_policy_cap():
    # Wildly strong edge: ungated would hit the 5% cap; dampening keeps it <= cap.
    strong = {"mu": 0.5, "variance": 0.01, "win_prob": 0.9, "win_loss_ratio": 5,
              "factor_signal": -1.0}
    alloc = am.size(strong)
    assert alloc.final_fraction <= 0.05 + 1e-9


def test_nan_factor_signal_is_ignored():
    ungated = am.size(_LONG_QUANT)
    handled = am.size(_with_signal(float("nan")))
    assert handled.final_fraction == pytest.approx(ungated.final_fraction)
    assert handled.factor_signal is None


def test_non_numeric_factor_signal_is_ignored():
    ungated = am.size(_LONG_QUANT)
    handled = am.size(_with_signal("not-a-number"))
    assert handled.final_fraction == pytest.approx(ungated.final_fraction)
    assert handled.factor_multiplier == 1.0


def test_zero_signal_is_neutral():
    ungated = am.size(_LONG_QUANT)
    handled = am.size(_with_signal(0.0))
    assert handled.final_fraction == pytest.approx(ungated.final_fraction)
