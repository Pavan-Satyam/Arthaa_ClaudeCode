"""Bar-loop paper simulation — stop-loss enforcement and look-ahead safety."""

import pandas as pd

from arthaai.execution.simulate import simulate_symbol


def _frame(closes, wick=0.01):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B", tz="UTC")
    return pd.DataFrame({
        "ts": idx,
        "open": closes,
        "high": [c * (1 + wick) for c in closes],
        "low": [c * (1 - wick) for c in closes],
        "close": closes,
        "volume": 1e6,
    })


# flat, then a breakout ramp, then a crash through the 8% stop
_BREAKOUT_THEN_CRASH = [100.0] * 10 + [105.0, 110.0, 115.0, 120.0] + [90.0, 91.0, 92.0, 93.0]
# flat, then a breakout ramp that never breaches the stop
_BREAKOUT_RAMP = [100.0] * 10 + [105.0, 110.0, 115.0, 120.0, 126.0, 133.0]


class TestSimulateSymbol:
    def test_stop_loss_actually_fires(self):
        res = simulate_symbol(
            "GLD", _frame(_BREAKOUT_THEN_CRASH),
            warmup=6, signal="breakout", entry_window=5, exit_window=3,
            allocation_fraction=0.05, equity=100_000.0, stop_loss_pct=0.08,
        )
        assert res.entries == 1
        assert res.stops_hit == 1
        assert res.targets_hit == 0
        assert res.realised_pnl < 0  # bought ~105, stopped ~96.6

    def test_no_stop_in_calm_ramp(self):
        res = simulate_symbol(
            "GLD", _frame(_BREAKOUT_RAMP),
            warmup=6, signal="breakout", entry_window=5, exit_window=3,
            stop_loss_pct=0.08,
        )
        assert res.entries >= 1
        assert res.stops_hit == 0
        assert res.targets_hit == 0

    def test_equity_curve_length_matches_bars(self):
        df = _frame(_BREAKOUT_RAMP)
        res = simulate_symbol("GLD", df, warmup=6, signal="breakout", entry_window=5, exit_window=3)
        assert len(res.equity_curve) == res.bars - 6

    def test_empty_frame_raises(self):
        import pytest

        with pytest.raises(ValueError):
            simulate_symbol("GLD", pd.DataFrame(columns=["ts", "open", "high", "low", "close"]))

    def test_no_lookahead_prefix_matches_full_run(self):
        """Truncating later bars must not change earlier decisions."""
        df = _frame(_BREAKOUT_THEN_CRASH)
        full = simulate_symbol("GLD", df, warmup=6, signal="breakout", entry_window=5, exit_window=3)
        k = 15
        prefix = simulate_symbol(
            "GLD", df.iloc[:k].reset_index(drop=True),
            warmup=6, signal="breakout", entry_window=5, exit_window=3,
        )
        assert prefix.fills == full.fills[: len(prefix.fills)]
