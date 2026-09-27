"""Tests for signal promotion gate."""

from arthaai.backtest.engine import oos_slice, oos_windows
from arthaai.backtest.promotion import (
    MAX_DD,
    MIN_SHARPE,
    check_criteria,
    combine_windows,
    evaluate_promotion,
)


class TestCheckCriteria:
    def test_all_pass_qualified(self):
        qualified, sharpe_ok, dd_ok, bh_ok, failures = check_criteria(
            sharpe=1.5, max_drawdown=-0.10, oos_return=0.30, buy_hold_return=0.20
        )
        assert qualified
        assert sharpe_ok
        assert dd_ok
        assert bh_ok
        assert failures == []

    def test_low_sharpe_rejected(self):
        qualified, sharpe_ok, dd_ok, bh_ok, failures = check_criteria(  # noqa: RUF059
            sharpe=0.5, max_drawdown=-0.10, oos_return=0.30, buy_hold_return=0.20
        )
        assert not qualified
        assert not sharpe_ok
        assert failures == [f"sharpe 0.50 < {MIN_SHARPE}"]

    def test_high_drawdown_rejected(self):
        qualified, sharpe_ok, dd_ok, bh_ok, failures = check_criteria(  # noqa: RUF059
            sharpe=1.5, max_drawdown=-0.30, oos_return=0.30, buy_hold_return=0.20
        )
        assert not qualified
        assert not dd_ok
        assert failures == [f"max_drawdown -30.0% exceeds {MAX_DD:.0%} cap"]

    def test_loses_to_buy_hold_rejected(self):
        qualified, sharpe_ok, dd_ok, bh_ok, failures = check_criteria(  # noqa: RUF059
            sharpe=1.5, max_drawdown=-0.10, oos_return=0.15, buy_hold_return=0.20
        )
        assert not qualified
        assert not bh_ok
        assert "long_only" in failures[0]

    def test_bh_uses_exposure_matched_long_only_when_supplied(self):
        # Kelly return (0.15) loses to B&H, but the 100%-exposure long-only (0.25) wins.
        qualified, _, _, bh_ok, _ = check_criteria(
            sharpe=1.5, max_drawdown=-0.10, oos_return=0.15,
            buy_hold_return=0.20, oos_long_only_return=0.25,
        )
        assert bh_ok and qualified

    def test_custom_min_sharpe(self):
        qualified, sharpe_ok, _, _, _ = check_criteria(
            sharpe=1.5, max_drawdown=-0.10, oos_return=0.30, buy_hold_return=0.20,
            min_sharpe=2.0,
        )
        assert not qualified and not sharpe_ok


class TestOosSlice:
    def test_default_30_percent(self):
        in_end, n_total = oos_slice(100)
        assert in_end == 70
        assert n_total == 100

    def test_minimum_one_bar(self):
        in_end, n_total = oos_slice(3)
        assert in_end == 2
        assert n_total == 3

    def test_empty_returns_last_bar(self):
        in_end, n_total = oos_slice(0)
        assert in_end == 0
        assert n_total == 0


class TestOosWindows:
    def test_two_non_overlapping_windows_most_recent_first(self):
        wins = oos_windows(500, oos_pct=0.30, count=2)
        assert wins == [(350, 500), (200, 350)]

    def test_stops_when_not_enough_bars(self):
        wins = oos_windows(100, oos_pct=0.30, count=3)
        assert wins == [(70, 100), (40, 70), (10, 40)]

    def test_count_one_is_just_the_last_window(self):
        assert oos_windows(100, oos_pct=0.30, count=1) == [(70, 100)]

    def test_zero_total(self):
        assert oos_windows(0, count=2) == []


class TestEvaluatePromotion:
    def test_qualified_when_all_three_pass(self):
        ev = evaluate_promotion(1.5, -0.10, 0.30, 0.20)
        assert ev.qualified
        assert ev.sharpe_ok
        assert ev.dd_ok
        assert ev.bh_ok
        assert ev.reason == "qualified"

    def test_rejected_when_sharpe_fails(self):
        ev = evaluate_promotion(0.5, -0.10, 0.30, 0.20)
        assert not ev.qualified
        assert not ev.sharpe_ok
        assert "sharpe" in ev.reason

    def test_rejected_when_dd_fails(self):
        ev = evaluate_promotion(1.5, -0.30, 0.30, 0.20)
        assert not ev.qualified
        assert not ev.dd_ok
        assert "drawdown" in ev.reason

    def test_rejected_when_buy_hold_fails(self):
        ev = evaluate_promotion(1.5, -0.10, 0.15, 0.20)
        assert not ev.qualified
        assert not ev.bh_ok
        assert "long_only" in ev.reason

    def test_records_long_only_and_kelly_separately(self):
        ev = evaluate_promotion(1.5, -0.10, 0.15, 0.20, oos_long_only_return=0.25)
        assert ev.oos_return == 0.15
        assert ev.long_only_return == 0.25
        assert ev.qualified

    def test_min_sharpe_and_max_dd_are_exposed(self):
        assert MIN_SHARPE == 1.0
        assert MAX_DD == 0.20


class TestCombineWindows:
    def test_all_pass(self):
        evs = [evaluate_promotion(1.5, -0.10, 0.30, 0.20) for _ in range(2)]
        ok, note = combine_windows(evs)
        assert ok and "all 2 windows" in note

    def test_one_failure_rejects(self):
        evs = [
            evaluate_promotion(1.5, -0.10, 0.30, 0.20),
            evaluate_promotion(0.2, -0.10, 0.05, 0.20),
        ]
        ok, note = combine_windows(evs)
        assert not ok and "1/2" in note

    def test_empty(self):
        ok, note = combine_windows([])
        assert not ok and "no windows" in note
