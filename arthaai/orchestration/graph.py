"""LangGraph macro-orchestrator.

Topology (Tier 2 -> Tier 3):

    ingest ─▶ ┌ db_agent ┐
              │ quant     │  (fan-out, async workers)
              │ news      │
              │ alt       │
              │ corr      │
              └──────────┘ ─▶ master_llm ─▶ asset_manager ─▶ END

The fan-out models the blueprint's Kafka dispatch to decoupled agents; the join
at master_llm is the State Store convergence. LangGraph runs the workers
concurrently and merges their partial-state updates into the shared GraphState.
"""

from __future__ import annotations

from dataclasses import asdict

from langgraph.graph import END, START, StateGraph

from arthaai.agents import (
    alt_agent,
    asset_manager,
    correlation_regime,
    db_agent,
    master_llm,
    news_agent,
    quant_agent,
)
from arthaai.data.provider import ingest_resilient
from arthaai.orchestration.state import GraphState


# --- nodes ---------------------------------------------------------------
def _ingest(state: GraphState) -> dict:
    if state.get("skip_ingest"):
        return {}
    ingest_resilient(state["symbol"])
    _refresh_news(state["symbol"])
    return {}


def _refresh_news(symbol: str) -> None:
    """Opt-in live-news refresh (ARTHA-216); network failure must not break analyze."""
    from arthaai.config import get_settings

    settings = get_settings()
    if not getattr(settings, "news_auto_ingest", False):
        return
    feeds = [u.strip() for u in getattr(settings, "news_feeds", "").split(",") if u.strip()]
    if not feeds:
        return
    from arthaai.data.news_feed import ingest_news

    try:
        ingest_news(symbol, feeds)
    except Exception:  # noqa: BLE001 - news is best-effort
        pass


def _db(state: GraphState) -> dict:
    return {"db": db_agent.run(state["symbol"])}


def _quant(state: GraphState) -> dict:
    return {"quant": quant_agent.run(state["symbol"])}


def _news(state: GraphState) -> dict:
    return {"news": news_agent.run(state["symbol"])}


def _alt(state: GraphState) -> dict:
    return {"alt": alt_agent.run(state["symbol"])}


def _correlation(state: GraphState) -> dict:
    return {"correlation": correlation_regime.run(state["symbol"])}


def _master(state: GraphState) -> dict:
    verdict = master_llm.reason(dict(state), state["symbol"])
    return {"verdict": asdict(verdict)}


def _asset_manager(state: GraphState) -> dict:
    quant = state.get("quant", {})
    conf = state.get("verdict", {}).get("confidence")
    alloc = asset_manager.size(quant, confidence=conf)
    return {"allocation": asdict(alloc)}


def build_graph():
    g = StateGraph(GraphState)
    g.add_node("ingest", _ingest)
    g.add_node("db_agent", _db)
    g.add_node("quant_agent", _quant)
    g.add_node("news_agent", _news)
    g.add_node("alt_agent", _alt)
    g.add_node("correlation_agent", _correlation)
    g.add_node("master_llm", _master)
    g.add_node("asset_manager", _asset_manager)

    g.add_edge(START, "ingest")
    for worker in ("db_agent", "quant_agent", "news_agent", "alt_agent", "correlation_agent"):
        g.add_edge("ingest", worker)          # fan-out
        g.add_edge(worker, "master_llm")      # converge at the State Store / Brain
    g.add_edge("master_llm", "asset_manager")
    g.add_edge("asset_manager", END)
    return g.compile()


def analyze(symbol: str, *, skip_ingest: bool = False) -> dict:
    """Run the full pipeline for `symbol` and return the final GraphState."""
    graph = build_graph()
    initial: GraphState = {"symbol": symbol.strip().strip(".").upper(), "skip_ingest": skip_ingest}
    result = graph.invoke(initial)
    return dict(result)
