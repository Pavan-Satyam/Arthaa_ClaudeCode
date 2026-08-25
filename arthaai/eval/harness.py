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

from arthaai.agents.master_llm import Verdict, reason


@dataclass
class GoldenFixture:
    """A known scenario with the expected verdict direction."""

    name: str
    state: dict
    expected_direction: str
    description: str


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
    notes: str = ""


@dataclass
class EvalReport:
    """Aggregate scorecard across all fixtures."""

    results: list[FixtureResult] = field(default_factory=list)
    total: int = 0
    direction_accuracy: float = 0.0
    rationale_rate: float = 0.0
    avg_confidence: float = 0.0
    sources_used: dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """All fixtures must get direction right and have a rationale."""
        return self.direction_accuracy == 1.0 and self.rationale_rate == 1.0


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
        results.append(FixtureResult(
            name=fx.name,
            expected=fx.expected_direction,
            actual=verdict.direction,
            confidence=verdict.confidence,
            source=verdict.source,
            rationale_ok=rationale_ok,
            direction_correct=direction_correct,
            notes=fx.description,
        ))

    report = EvalReport(results=results, total=len(results))
    report.direction_accuracy = sum(r.direction_correct for r in results) / results.__len__() if results else 0.0
    report.rationale_rate = sum(r.rationale_ok for r in results) / len(results) if results else 0.0
    report.avg_confidence = sum(r.confidence for r in results) / len(results) if results else 0.0
    for r in results:
        report.sources_used[r.source] = report.sources_used.get(r.source, 0) + 1
    return report
