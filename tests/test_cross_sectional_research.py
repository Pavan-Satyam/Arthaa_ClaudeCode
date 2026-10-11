"""Research-only cross-sectional walk-forward validation tests."""

import numpy as np
import pandas as pd
import pytest

from arthaai.research import cross_sectional
from arthaai.research.cross_sectional import evaluate_cross_sectional_scores


def _research_inputs(n=30):
    dates = pd.date_range("2025-01-01", periods=n, freq="B", tz="UTC")
    close = pd.DataFrame(
        {
            "AAA": 100.0 * 1.01 ** np.arange(n),
            "BBB": 100.0 * 0.99 ** np.arange(n),
            "CCC": np.full(n, 100.0),
        },
        index=dates,
    )
    scores = pd.DataFrame(
        {"AAA": 1.0, "BBB": 0.0, "CCC": -1.0}, index=dates
    )
    return close, scores


def test_scores_are_lagged_and_oos_report_is_diagnostic_only():
    close, scores = _research_inputs()
    latest_window_start = 24
    current_day = close.index[latest_window_start]
    scores.loc[current_day] = {"AAA": -1.0, "BBB": 2.0, "CCC": 0.0}

    report = evaluate_cross_sectional_scores(
        close, scores, top_quantile=0.33, cost_bps=0.0, windows=2, oos_pct=0.20
    )

    assert len(report.windows) == 2
    latest = report.windows[-1]
    assert latest.total_return > 0.0
    assert latest.benchmark_return < latest.total_return
    assert latest.complete_assets == 3
    assert "equal-weight same-universe" in report.benchmark
    assert "qualified" not in report.as_dict()


def test_turnover_costs_reduce_strategy_return():
    close, scores = _research_inputs()
    scores.loc[close.index[24:]] = scores.loc[close.index[24:]].iloc[::-1].to_numpy()

    no_cost = evaluate_cross_sectional_scores(
        close, scores, top_quantile=0.33, cost_bps=0.0, windows=1, oos_pct=0.20
    ).windows[0]
    with_cost = evaluate_cross_sectional_scores(
        close, scores, top_quantile=0.33, cost_bps=25.0, windows=1, oos_pct=0.20
    ).windows[0]

    assert with_cost.total_return < no_cost.total_return
    assert with_cost.average_turnover > 0.0
    assert with_cost.benchmark_average_turnover > 0.0


def test_rebalancing_turnover_includes_price_weight_drift():
    close, scores = _research_inputs()
    result = evaluate_cross_sectional_scores(
        close, scores, top_quantile=0.67, cost_bps=0.0, windows=1, oos_pct=0.20
    ).windows[0]

    assert result.average_turnover > 1.0 / 6.0


def test_incomplete_common_calendar_is_reported_as_skipped():
    close, scores = _research_inputs()
    close.loc[close.index[24], "CCC"] = np.nan
    close.loc[close.index[25], "CCC"] = np.nan

    report = evaluate_cross_sectional_scores(
        close, scores, windows=1, oos_pct=0.20, min_assets=3
    )

    assert report.windows == []
    assert len(report.skipped_windows) == 1


def test_single_missing_exchange_session_is_carried_at_last_close():
    close, scores = _research_inputs()
    close.loc[close.index[24], "CCC"] = np.nan

    report = evaluate_cross_sectional_scores(
        close, scores, windows=1, oos_pct=0.20, min_assets=3
    )

    assert len(report.windows) == 1
    assert report.windows[0].complete_assets == 3


def test_invalid_research_parameters_are_rejected():
    close, scores = _research_inputs()
    with pytest.raises(ValueError, match="top_quantile"):
        evaluate_cross_sectional_scores(close, scores, top_quantile=0.0)


def test_factor_research_records_default_factor_universe(monkeypatch):
    close, _ = _research_inputs()
    scores = pd.DataFrame(1.0, index=close.index, columns=close.columns)
    monkeypatch.setattr(cross_sectional, "ic_weighted_composite", lambda *args, **kwargs: scores)
    panel = {"close": close}

    report = cross_sectional.run_factor_research(
        panel, windows=1, oos_pct=0.20, min_assets=3
    )

    assert report.factor_ids == [
        "alpha101_024", "alpha101_009", "alpha101_012", "alpha101_023", "alpha101_031"
    ]