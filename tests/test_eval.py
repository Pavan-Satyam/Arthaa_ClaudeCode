"""LLM eval harness — golden fixtures and scoring logic."""

import pytest

from arthaai.eval.harness import (
    EvalReport,
    FixtureResult,
    _calibration_score,
    _check_rationale,
    _confidence_band,
    golden_fixtures,
    run_eval,
)


def test_golden_fixtures_cover_key_scenarios():
    fixtures = golden_fixtures()
    assert len(fixtures) >= 5
    directions = {f.expected_direction for f in fixtures}
    assert {"bullish", "bearish", "neutral"} <= directions
    bands = {f.expected_confidence_band for f in fixtures}
    assert {"high", "medium", "low"} <= bands
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


def test_confidence_band_thresholds():
    assert _confidence_band(0.9) == "high"
    assert _confidence_band(0.75) == "high"
    assert _confidence_band(0.6) == "medium"
    assert _confidence_band(0.51) == "medium"
    assert _confidence_band(0.5) == "low"  # exactly 0.5 = no edge = low
    assert _confidence_band(0.3) == "low"
    assert _confidence_band(0.45) == "low"


def test_calibration_score_perfect():
    # Correct verdicts have higher confidence than incorrect ones.
    results = [
        FixtureResult("a", "bullish", "bullish", 0.9, "offline", True, True),
        FixtureResult("b", "bearish", "bearish", 0.8, "offline", True, True),
        FixtureResult("c", "neutral", "neutral", 0.4, "offline", True, True),
    ]
    # All correct, no discordant pairs with different correctness -> 0 (no signal)
    # But if we mix correct/incorrect:
    results = [
        FixtureResult("a", "bullish", "bullish", 0.9, "offline", True, True),  # correct, high conf
        FixtureResult("b", "bearish", "neutral", 0.3, "offline", True, False),  # wrong, low conf
    ]
    assert _calibration_score(results) == 1.0  # correct has higher conf -> concordant


def test_calibration_score_anti_calibrated():
    # Wrong verdicts have HIGHER confidence — anti-calibrated.
    results = [
        FixtureResult("a", "bullish", "neutral", 0.9, "offline", True, False),  # wrong, high conf
        FixtureResult("b", "bearish", "bearish", 0.3, "offline", True, True),  # correct, low conf
    ]
    assert _calibration_score(results) == -1.0


def test_calibration_score_no_signal():
    # All same correctness — calibration is undefined (None).
    results = [
        FixtureResult("a", "bullish", "bullish", 0.9, "offline", True, True),
        FixtureResult("b", "bearish", "bearish", 0.3, "offline", True, True),
    ]
    assert _calibration_score(results) is None  # no variance in correctness


def test_calibration_score_too_few():
    assert _calibration_score([FixtureResult("a", "x", "x", 0.5, "s", True, True)]) is None


def test_run_eval_offline_passes_all_fixtures():
    """The offline reasoner must score 100% — it IS the baseline."""
    report = run_eval(provider="offline")
    assert report.total == len(golden_fixtures())
    assert report.direction_accuracy == 1.0
    assert report.rationale_rate == 1.0
    assert report.confidence_band_accuracy >= 0.8
    assert report.calibration_score is None  # all-correct -> undefined (no variance)
    assert report.passed is True
    assert "offline-fallback" in report.sources_used


def test_eval_report_aggregates_correctly():
    results = [
        FixtureResult("a", "bullish", "bullish", 0.7, "offline", True, True, True),
        FixtureResult("b", "bearish", "neutral", 0.4, "offline", True, False, False),
    ]
    report = EvalReport(results=results, total=2)
    report.direction_accuracy = sum(r.direction_correct for r in results) / len(results)
    report.rationale_rate = sum(r.rationale_ok for r in results) / len(results)
    report.avg_confidence = sum(r.confidence for r in results) / len(results)
    report.confidence_band_accuracy = sum(r.confidence_band_ok for r in results) / len(results)
    report.calibration_score = _calibration_score(results)
    for r in results:
        report.sources_used[r.source] = report.sources_used.get(r.source, 0) + 1

    assert report.direction_accuracy == 0.5
    assert report.rationale_rate == 1.0
    assert report.avg_confidence == pytest.approx(0.55)
    assert report.confidence_band_accuracy == 0.5
    assert report.calibration_score == 1.0  # correct has higher conf
    assert report.passed is False  # 50% direction accuracy
