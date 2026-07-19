"""OPA client — evaluates agent tool calls against the live Rego policy.

Queries the OPA server's data API. Wrapped in a circuit breaker: if OPA is
unreachable the decision falls back to the in-process ALLOWED map (fail-safe to
the same least-privilege scopes), so the pipeline keeps running while still
denying out-of-scope tools. Decisions are cached per (agent, tool) to avoid a
network round-trip on every call.
"""

from __future__ import annotations

import httpx

from arthaai.config import get_settings
from arthaai.resiliency import guarded

# In-process mirror of policy/arthaai.rego — the fail-safe when OPA is down.
ALLOWED: dict[str, set[str]] = {
    "db_agent": {"sql_query", "load_ohlcv"},
    "quant_agent": {"load_ohlcv", "compute_stats"},
    "news_agent": {"hybrid_search"},
    "alt_agent": {"external_api"},
    "asset_manager": {"compute_stats", "kelly"},
    "master_llm": {"llm_complete"},
}

_cache: dict[tuple[str, str], bool] = {}


def _query_opa(agent: str, tool: str) -> bool:
    url = f"{get_settings().opa_url}/v1/data/arthaai/allow"
    resp = httpx.post(url, json={"input": {"agent": agent, "tool": tool}}, timeout=2.0)
    resp.raise_for_status()
    return bool(resp.json().get("result", False))


def is_allowed(agent: str, tool: str) -> bool:
    key = (agent, tool)
    if key in _cache:
        return _cache[key]
    decision = guarded(
        "opa",
        lambda: _query_opa(agent, tool),
        fallback=lambda: tool in ALLOWED.get(agent, set()),
    )
    _cache[key] = decision
    return decision
