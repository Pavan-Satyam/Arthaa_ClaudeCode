"""Golden-fixture eval harness for the Master Reasoning LLM.

Runs the LLM (or offline fallback) against a set of known GraphState scenarios
and scores the verdicts. This measures synthesis quality — does the LLM agree
with the deterministic evidence blend on clear-cut cases, and does it produce
well-formed verdicts (valid direction, sane confidence, rationale present)?

Fixtures are designed so the offline reasoner passes 100% (it IS the scoring
baseline), and any LLM provider can be measured against it. Run via:

    arthaai eval                  # score the active provider chain
    arthaai eval --provider offline   # score only the offline reasoner

Metrics:
  - direction_accuracy: verdict direction matches expected
  - confidence_sanity: confidence in [0,1] and high for clear signals
  - rationale_quality: rationale exists and ends with "I choose this because"
  - source: which provider produced each verdict
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arthaai.agents.master_llm import reason


@dataclass
class GoldenFixture:
    """A known scenario with the expected verdict direction and confidence band."""

    name: str
    state: dict
    expected_direction: str
    description: str
    expected_confidence_band: str = "medium"  # high (>0.7) | medium (0.5-0.7) | low (<0.5)


@dataclass
class FixtureResult:
    """The outcome of running one fixture."""

    name: str
    expected: str
    actual: str
    confidence: float
    source: str
    rationale_ok: bool
    direction_correct: bool
    confidence_band_ok: bool = False
    notes: str = ""


@dataclass
class EvalReport:
    """Aggregate scorecard across all fixtures."""

    results: list[FixtureResult] = field(default_factory=list)
    total: int = 0
    direction_accuracy: float = 0.0
    rationale_rate: float = 0.0
    avg_confidence: float = 0.0
    confidence_band_accuracy: float = 0.0  # fraction where confidence falls in expected band
    calibration_score: float = 0.0  # rank correlation: correct verdicts should have higher confidence
    sources_used: dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """All fixtures must get direction right, have a rationale, and be calibrated."""
        return (
            self.direction_accuracy == 1.0
            and self.rationale_rate == 1.0
            and self.confidence_band_accuracy >= 0.8
        )


def golden_fixtures() -> list[GoldenFixture]:
    """Curated scenarios where the evidence clearly points one way.

    Each fixture is a GraphState dict (the same shape master_llm.reason()
    consumes). The expected_direction is what the deterministic weighted-score
    blend produces — the baseline the LLM is measured against.
    """
    return [
        GoldenFixture(
            name="strong_bullish",
            description="All signals aligned bullish: strong trend, positive news, positive alt",
            expected_direction="bullish",
            expected_confidence_band="high",
            state={
                "symbol": "GLD",
                "db": {"available": True, "trend": "bullish", "trend_score": 0.65, "rsi14": 58, "adx14": 28.0, "regime": "trending"},
                "quant": {"available": True, "mu": 0.12, "variance": 0.03, "sigma": 0.17, "win_prob": 0.58, "win_loss_ratio": 1.3},
                "news": {"available": True, "label": "positive", "avg_sentiment": 0.45, "count": 12},
                "alt": {"available": True, "physical_score": 0.3, "note": "real yields falling"},
            },
        ),
        GoldenFixture(
            name="strong_bearish",
            description="All signals aligned bearish: downtrend, negative news, negative alt",
            expected_direction="bearish",
            expected_confidence_band="high",
            state={
                "symbol": "XOM",
                "db": {"available": True, "trend": "bearish", "trend_score": -0.55, "rsi14": 32, "adx14": 27.0, "regime": "trending"},
                "quant": {"available": True, "mu": -0.08, "variance": 0.04, "sigma": 0.20, "win_prob": 0.42, "win_loss_ratio": 0.85},
                "news": {"available": True, "label": "negative", "avg_sentiment": -0.40, "count": 8},
                "alt": {"available": True, "physical_score": -0.25, "note": "inventory buildup"},
            },
        ),
        GoldenFixture(
            name="conflicting_neutral",
            description="Mixed signals: bullish trend but negative news and flat alt",
            expected_direction="neutral",
            expected_confidence_band="medium",
            state={
                "symbol": "AAPL",
                "db": {"available": True, "trend": "bullish", "trend_score": 0.35, "rsi14": 62, "adx14": 18.0, "regime": "weak-trend"},
                "quant": {"available": True, "mu": 0.05, "variance": 0.02, "sigma": 0.14, "win_prob": 0.52, "win_loss_ratio": 1.05},
                "news": {"available": True, "label": "negative", "avg_sentiment": -0.30, "count": 5},
                "alt": {"available": False},
            },
        ),
        GoldenFixture(
            name="no_data",
            description="No evidence available at all",
            expected_direction="neutral",
            expected_confidence_band="low",
            state={
                "symbol": "UNKNOWN",
                "db": {"available": False},
                "quant": {"available": False},
                "news": {"available": False},
                "alt": {"available": False},
            },
        ),
        GoldenFixture(
            name="technical_only_bullish",
            description="Only technical signal available, strongly bullish, no news/alt",
            expected_direction="bullish",
            expected_confidence_band="high",
            state={
                "symbol": "SLV",
                "db": {"available": True, "trend": "bullish", "trend_score": 0.50, "rsi14": 55, "adx14": 30.0, "regime": "trending"},
                "quant": {"available": True, "mu": 0.10, "variance": 0.05, "sigma": 0.22, "win_prob": 0.55, "win_loss_ratio": 1.2},
                "news": {"available": False},
                "alt": {"available": False},
            },
        ),
        GoldenFixture(
            name="news_driven_bearish",
            description="Weak trend but strongly negative news dominates",
            expected_direction="bearish",
            expected_confidence_band="medium",
            state={
                "symbol": "TSLA",
                "db": {"available": True, "trend": "neutral", "trend_score": -0.05, "rsi14": 48, "adx14": 15.0, "regime": "choppy"},
                "quant": {"available": True, "mu": 0.01, "variance": 0.06, "sigma": 0.24, "win_prob": 0.49, "win_loss_ratio": 0.95},
                "news": {"available": True, "label": "very_negative", "avg_sentiment": -0.65, "count": 15},
                "alt": {"available": False},
            },
        ),
    ]


def _check_rationale(rationale: str) -> bool:
    """Rationale must be non-empty and contain the audit-trail phrase.

    The system prompt asks for a sentence starting 'I choose this because';
    the offline reasoner says 'I choose a {direction} stance because'. Accept
    both patterns — the key audit requirement is that the model explicitly
    states WHY it chose its direction.
    """
    if not rationale or len(rationale.strip()) < 10:
        return False
    low = rationale.lower()
    return "i choose" in low and "because" in low


def _confidence_band(conf: float) -> str:
    """Map a confidence value to its band: high (>0.7) | medium (0.5-0.7) | low (<0.5).

    Note: the offline reasoner's formula (0.5 + abs(score)/2) structurally
    produces confidence >= 0.5, so "low" only appears when an LLM provider
    returns sub-0.5 confidence — a sign of genuine uncertainty.
    """
    if conf > 0.7:
        return "high"
    if conf > 0.5:
        return "medium"
    return "low"


def _calibration_score(results: list[FixtureResult]) -> float | None:
    """Kendall tau-style rank correlation between confidence and correctness.

    A well-calibrated model assigns higher confidence to correct verdicts.
    Returns a value in [-1, 1]: 1 = perfectly calibrated, 0 = no relationship,
    -1 = anti-calibrated. Returns ``None`` when correctness has no variance
    (all verdicts correct or all wrong) — the metric is degenerate in that case
    and reporting 0.0 ("random") would be misleading.
    """
    if len(results) < 2:
        return None
    # If all verdicts have the same correctness, calibration is undefined.
    correctness_values = [int(r.direction_correct) for r in results]
    if len(set(correctness_values)) < 2:
        return None
    concordant = 0
    discordant = 0
    for i in range(len(results)):
        for j in range(i + 1, len(results)):
            ci, cj = results[i].confidence, results[j].confidence
            ki, kj = correctness_values[i], correctness_values[j]
            if ci == cj or ki == kj:
                continue  # tie in confidence or correctness — no signal
            if (ci > cj) == (ki > kj):
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    return concordant / total - discordant / total if total > 0 else 0.0


def run_eval(provider: str | None = None) -> EvalReport:
    """Run all golden fixtures and return a scorecard.

    Args:
        provider: If given, force a specific provider (e.g. "offline").
                  If None, uses the configured provider chain.
    """
    import os

    if provider:
        os.environ["ARTHAAI_LLM_CHAIN"] = provider
        from arthaai.config import get_settings
        get_settings.cache_clear()

    fixtures = golden_fixtures()
    results: list[FixtureResult] = []

    for fx in fixtures:
        verdict = reason(fx.state, fx.state.get("symbol", "UNKNOWN"))
        direction_correct = verdict.direction == fx.expected_direction
        rationale_ok = _check_rationale(verdict.rationale)
        actual_band = _confidence_band(verdict.confidence)
        band_ok = actual_band == fx.expected_confidence_band
        results.append(FixtureResult(
            name=fx.name,
            expected=fx.expected_direction,
            actual=verdict.direction,
            confidence=verdict.confidence,
            source=verdict.source,
            rationale_ok=rationale_ok,
            direction_correct=direction_correct,
            confidence_band_ok=band_ok,
            notes=fx.description,
        ))

    report = EvalReport(results=results, total=len(results))
    report.direction_accuracy = sum(r.direction_correct for r in results) / len(results) if results else 0.0
    report.rationale_rate = sum(r.rationale_ok for r in results) / len(results) if results else 0.0
    report.avg_confidence = sum(r.confidence for r in results) / len(results) if results else 0.0
    report.confidence_band_accuracy = sum(r.confidence_band_ok for r in results) / len(results) if results else 0.0
    report.calibration_score = _calibration_score(results)
    for r in results:
        report.sources_used[r.source] = report.sources_used.get(r.source, 0) + 1
    return report
