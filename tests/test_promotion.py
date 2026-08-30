"""Tests for signal promotion gate."""


from arthaai.backtest.promotion import (
    MAX_DD,
    MIN_SHARPE,
    check_criteria,
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
        assert "oos_return" in failures[0]


class TestOosSlice:
    def test_default_30_percent(self):
        from arthaai.backtest.engine import oos_slice

        in_end, n_total = oos_slice(100)
        assert in_end == 70
        assert n_total == 100

    def test_minimum_one_bar(self):
        from arthaai.backtest.engine import oos_slice

        in_end, n_total = oos_slice(3)
        assert in_end == 2
        assert n_total == 3

    def test_empty_returns_last_bar(self):
        from arthaai.backtest.engine import oos_slice

        in_end, n_total = oos_slice(0)
        assert in_end == 0
        assert n_total == 0


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
        assert "oos_return" in ev.reason

    def test_min_sharpe_and_max_dd_are_exposed(self):
        assert MIN_SHARPE == 1.0
        assert MAX_DD == 0.20
