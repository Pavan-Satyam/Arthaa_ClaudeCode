"""GraphState — the shared, appendable state every node reads and writes.

Mirrors the blueprint's LangGraph GraphState primitive: worker agents converge
their refined context here, the Master LLM reads the union, and the Asset Manager
appends the allocation.
"""

from __future__ import annotations

from typing import TypedDict


class GraphState(TypedDict, total=False):
    symbol: str
    skip_ingest: bool
    db: dict          # DB_Agent — technical indicators
    quant: dict       # Quant Agent — return/variance stats + Kelly inputs
    news: dict        # News_Agent — sentiment
    alt: dict         # Alt_Agent — physical/alt data (stub)
    verdict: dict     # Master Reasoning LLM — direction/confidence/rationale
    allocation: dict  # Asset Manager — Kelly-sized fraction
