"""LLM eval harness — golden fixtures and scoring logic."""

import pytest

from arthaai.eval.harness import (
    EvalReport,
    FixtureResult,
    golden_fixtures,
    run_eval,
    _check_rationale,
)


def test_golden_fixtures_cover_key_scenarios():
    fixtures = golden_fixtures()
    assert len(fixtures) >= 5
    directions = {f.expected_direction for f in fixtures}
    assert {"bullish", "bearish", "neutral"} <= directions
    names = {f.name for f in fixtures}
    assert "no_data" in names
    assert "strong_bullish" in names


def test_check_rationale_accepts_audit_trail():
    assert _check_rationale("The signals net positive. I choose this because the trend is strong.")
    assert _check_rationale("Evidence is mixed. i choose this because the news dominates.")


def test_check_rationale_rejects_missing_or_short():
    assert not _check_rationale("")
    assert not _check_rationale("short")
    assert not _check_rationale("This rationale lacks the required audit trail phrase.")


def test_run_eval_offline_passes_all_fixtures():
    """The offline reasoner must score 100% — it IS the baseline."""
    report = run_eval(provider="offline")
    assert report.total == len(golden_fixtures())
    assert report.direction_accuracy == 1.0
    assert report.rationale_rate == 1.0
    assert report.passed is True
    assert "offline-fallback" in report.sources_used


def test_eval_report_aggregates_correctly():
    results = [
        FixtureResult("a", "bullish", "bullish", 0.7, "offline", True, True),
        FixtureResult("b", "bearish", "neutral", 0.4, "offline", True, False),
    ]
    report = EvalReport(results=results, total=2)
    report.direction_accuracy = sum(r.direction_correct for r in results) / len(results)
    report.rationale_rate = sum(r.rationale_ok for r in results) / len(results)
    report.avg_confidence = sum(r.confidence for r in results) / len(results)
    for r in results:
        report.sources_used[r.source] = report.sources_used.get(r.source, 0) + 1

    assert report.direction_accuracy == 0.5
    assert report.rationale_rate == 1.0
    assert report.avg_confidence == pytest.approx(0.55)
    assert report.passed is False  # 50% direction accuracy
    assert report.sources_used == {"offline": 2}
