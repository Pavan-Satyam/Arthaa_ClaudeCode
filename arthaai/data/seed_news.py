"""Seed a small set of illustrative, source-attributed news into Qdrant.

Stands in for the Live Ingestion Agent's real feeds (Permutable / LSEG / S&P).
Sentiment is pre-scored here; in production it comes from the embedding + scoring
pipeline described in the blueprint.
"""

from __future__ import annotations

from arthaai.db import qdrant

_SEED: list[dict] = [
    # GLD — gold
    {"id": 1, "ticker": "GLD", "source": "LSEG", "sentiment": 0.6,
     "headline": "Safe-haven demand lifts gold as real yields ease and dollar softens."},
    {"id": 2, "ticker": "GLD", "source": "S&P Global", "sentiment": 0.3,
     "headline": "Central-bank gold buying stays robust into the quarter, underpinning prices."},
    {"id": 3, "ticker": "GLD", "source": "Permutable", "sentiment": -0.2,
     "headline": "Gold theme momentum fades as risk appetite returns to equities."},
    # USO — oil
    {"id": 4, "ticker": "USO", "source": "Permutable", "sentiment": -0.5,
     "headline": "Crude sentiment turns bearish on demand-growth downgrades and rising inventories."},
    {"id": 5, "ticker": "USO", "source": "LSEG", "sentiment": 0.4,
     "headline": "OPEC+ signals extended supply discipline, offering a floor under oil prices."},
    # AAPL
    {"id": 6, "ticker": "AAPL", "source": "S&P Global", "sentiment": 0.5,
     "headline": "Apple services growth beats estimates; margin outlook raised for the year."},
    {"id": 7, "ticker": "AAPL", "source": "Permutable", "sentiment": -0.3,
     "headline": "Hardware demand narrative softens on cautious China channel checks."},
    # XOM
    {"id": 8, "ticker": "XOM", "source": "LSEG", "sentiment": 0.2,
     "headline": "Exxon buybacks continue as cash flow stays strong despite softer crude."},
]


def seed() -> int:
    return qdrant.upsert_news(_SEED)
