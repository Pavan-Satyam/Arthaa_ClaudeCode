"""Qdrant narrative store with hybrid search (metadata filter + vector similarity).

Embeddings: uses fastembed if installed (fully local ONNX), otherwise a deterministic
hash-based fallback so the pipeline runs offline with zero extra downloads. The
fallback is not semantically meaningful — install the `embed` extra for real vectors.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from arthaai.config import get_settings

_DIM = 384  # matches fastembed BAAI/bge-small-en-v1.5


@dataclass
class NewsHit:
    headline: str
    source: str
    sentiment: float  # -1 bearish .. +1 bullish
    score: float


def _client() -> QdrantClient:
    s = get_settings()
    return QdrantClient(host=s.qdrant_host, port=s.qdrant_port)


def _fallback_embed(text: str) -> list[float]:
    """Deterministic pseudo-embedding from a hash — offline, non-semantic."""
    h = hashlib.sha256(text.lower().encode()).digest()
    raw = (h * ((_DIM // len(h)) + 1))[:_DIM]
    return [(b / 255.0) * 2 - 1 for b in raw]


try:  # prefer real local embeddings when available
    from fastembed import TextEmbedding  # type: ignore

    _model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

    def embed(text: str) -> list[float]:
        return list(next(iter(_model.embed([text]))))
except Exception:  # noqa: BLE001

    def embed(text: str) -> list[float]:
        return _fallback_embed(text)


def ensure_collection() -> None:
    client, name = _client(), get_settings().news_collection
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(name, vectors_config=VectorParams(size=_DIM, distance=Distance.COSINE))


def upsert_news(docs: list[dict]) -> int:
    """docs: [{id, headline, source, ticker, sentiment, ts}]. Payload holds hard filters."""
    ensure_collection()
    client, name = _client(), get_settings().news_collection
    points = [
        PointStruct(
            id=d["id"],
            vector=embed(d["headline"]),
            payload={
                "headline": d["headline"],
                "source": d["source"],
                "ticker": d["ticker"],
                "sentiment": d["sentiment"],
                "ts": d.get("ts"),
            },
        )
        for d in docs
    ]
    client.upsert(collection_name=name, points=points)
    return len(points)


def hybrid_search(ticker: str, query: str, limit: int = 5) -> list[NewsHit]:
    """Hard metadata filter on ticker FIRST, then semantic similarity — the
    blueprint's contamination-free retrieval."""
    client, name = _client(), get_settings().news_collection
    flt = Filter(must=[FieldCondition(key="ticker", match=MatchValue(value=ticker.upper()))])
    res = client.query_points(
        collection_name=name, query=embed(query), query_filter=flt, limit=limit
    ).points
    return [
        NewsHit(
            headline=p.payload["headline"],
            source=p.payload["source"],
            sentiment=float(p.payload["sentiment"]),
            score=float(p.score),
        )
        for p in res
    ]
