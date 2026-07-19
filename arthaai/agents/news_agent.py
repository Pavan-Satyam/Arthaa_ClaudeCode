"""News_Agent — live ingestion & sentiment (unstructured domain).

Retrieves semantically clustered, source-attributed news from Qdrant using
hybrid search (hard ticker filter, then similarity). Qdrant access is wrapped in
a circuit breaker with a neutral fallback so a store outage degrades gracefully.
"""

from __future__ import annotations

from arthaai.db import qdrant
from arthaai.resiliency import guarded
from arthaai.security import AgentIdentity, authorize_tool

IDENTITY = AgentIdentity("news_agent", "spiffe://arthaai/agent/news_agent")


def run(symbol: str) -> dict:
    authorize_tool(IDENTITY, "hybrid_search")
    query = f"{symbol} price outlook demand supply sentiment"

    def _search() -> list[qdrant.NewsHit]:
        return qdrant.hybrid_search(symbol, query, limit=5)

    hits = guarded("qdrant", _search, fallback=list)
    if not hits:
        return {"available": False, "reason": "no attributed news for ticker.", "items": []}
    avg = sum(h.sentiment for h in hits) / len(hits)
    label = "bullish" if avg > 0.1 else "bearish" if avg < -0.1 else "mixed"
    return {
        "available": True,
        "count": len(hits),
        "avg_sentiment": round(avg, 3),
        "label": label,
        "items": [{"headline": h.headline, "source": h.source, "sentiment": h.sentiment} for h in hits],
    }
