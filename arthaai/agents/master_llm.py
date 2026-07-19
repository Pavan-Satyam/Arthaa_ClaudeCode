"""Master Reasoning LLM (the "Brain") — Tier 2 apex aggregator.

Ingests the unified GraphState (quant + sentiment + physical) and synthesises a
probabilistically weighted forecast with an explicit, auditable rationale ending
in "I choose this because…".

Resilience: the Claude call is wrapped in a circuit breaker. If no API key is set
or the provider is unavailable, it falls back to a deterministic offline reasoner
— mirroring the blueprint's "fallback to an internally-hosted open-weight model".
Either way it emits the same structured verdict, so nothing downstream changes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from arthaai.config import get_settings
from arthaai.resiliency import guarded
from arthaai.security import AgentIdentity, authorize_tool

IDENTITY = AgentIdentity("master_llm", "spiffe://arthaai/agent/master_llm")


@dataclass
class Verdict:
    direction: str        # bullish | bearish | neutral
    confidence: float     # 0..1
    rationale: str
    source: str           # "claude" | "offline-fallback"


def _weighted_score(state: dict) -> tuple[float, list[str]]:
    """Deterministic evidence blend, also used as the offline fallback."""
    signals, notes = [], []
    db = state.get("db", {})
    if db.get("available"):
        signals.append(("technical", db["trend_score"], 0.45))
        notes.append(f"technical trend {db['trend']} ({db['trend_score']:+.2f})")
    news = state.get("news", {})
    if news.get("available"):
        signals.append(("sentiment", news["avg_sentiment"], 0.30))
        notes.append(f"news sentiment {news['label']} ({news['avg_sentiment']:+.2f})")
    alt = state.get("alt", {})
    if alt.get("available"):
        signals.append(("physical", alt["physical_score"], 0.25))
        notes.append(f"physical/alt signal {alt['physical_score']:+.2f}")
    if not signals:
        return 0.0, ["no evidence available"]
    wsum = sum(w for _, _, w in signals)
    score = sum(v * w for _, v, w in signals) / wsum
    return score, notes


def _offline(state: dict, symbol: str) -> Verdict:
    score, notes = _weighted_score(state)
    direction = "bullish" if score > 0.12 else "bearish" if score < -0.12 else "neutral"
    conf = min(1.0, 0.5 + abs(score) / 2)
    joined = "; ".join(notes)
    rationale = (
        f"Weighing the evidence for {symbol}: {joined}. The signals net to "
        f"{score:+.2f}. I choose a {direction} stance because the weighted "
        f"balance of technical, sentiment, and physical evidence points that way."
    )
    return Verdict(direction, round(conf, 3), rationale, "offline-fallback")


def _claude(state: dict, symbol: str) -> Verdict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("no ANTHROPIC_API_KEY")
    from anthropic import Anthropic

    client = Anthropic()
    system = (
        "You are the Master Reasoning LLM of a financial multi-agent system. You do "
        "NOT compute numbers; you synthesise the deterministic evidence provided by "
        "sub-agents and explain conflicts. Return ONLY compact JSON with keys "
        "direction (bullish|bearish|neutral), confidence (0..1 float), rationale "
        "(string ending with a sentence starting 'I choose this because'). Warn of "
        "conflicting signals in the rationale."
    )
    prompt = f"Asset: {symbol}\nAgent evidence (GraphState):\n{json.dumps(state, indent=2)}"
    msg = client.messages.create(
        model=get_settings().llm_model,
        max_tokens=700,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    data = json.loads(text)
    return Verdict(
        direction=str(data["direction"]),
        confidence=float(data["confidence"]),
        rationale=str(data["rationale"]),
        source="claude",
    )


def reason(state: dict, symbol: str) -> Verdict:
    authorize_tool(IDENTITY, "llm_complete")
    return guarded("master_llm", lambda: _claude(state, symbol), fallback=lambda: _offline(state, symbol))
