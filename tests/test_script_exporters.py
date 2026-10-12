"""Signal script exporters (ARTHA-412)."""

import pytest

from arthaai.export import PLATFORMS, SignalSpec, render


def test_pine_trend_contains_windows_and_symbol():
    text = render(SignalSpec("GLD", "trend", fast=20, slow=50, long_filter=200), "pine")
    assert "//@version=5" in text
    assert "GLD" in text
    assert "ta.sma(close, 20)" in text
    assert "ta.sma(close, 200)" in text


def test_pine_breakout_has_donchian_and_adx():
    spec = SignalSpec("XOM", "breakout", entry_window=20, exit_window=10, adx_threshold=25.0)
    text = render(spec, "pine")
    assert "ta.highest(high, 20)" in text
    assert "ta.lowest(low, 10)" in text
    assert "ta.dmi(14, 14)" in text


def test_tsmom_renders_on_all_platforms():
    for platform in PLATFORMS:
        text = render(SignalSpec("AAPL", "tsmom", lookback=126), platform)
        assert "AAPL" in text
        assert "126" in text


def test_unknown_platform_and_kind_raise():
    with pytest.raises(ValueError):
        render(SignalSpec("GLD"), "ninjatrader")
    with pytest.raises(ValueError):
        render(SignalSpec("GLD", "magic"), "pine")


def test_platform_name_is_case_insensitive():
    assert render(SignalSpec("GLD"), "PINE") == render(SignalSpec("GLD"), "pine")
