"""Policy-as-code seam (OPA/Rego stand-in) + agent identity (SPIFFE/SPIRE stand-in).

The blueprint evaluates every tool call against an immutable per-agent tool scope
before it fires. Here we enforce that scope in-process with a static allow-map;
in production this delegates to an OPA sidecar and the identity is a SPIFFE ID
bound to a JWT. Least-privilege is expressed by the ALLOWED map (e.g. the data
agent has no path to execution).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentIdentity:
    """Stand-in for a SPIFFE ID bound to a short-lived JWT."""

    agent: str          # e.g. "db_agent"
    spiffe_id: str      # e.g. "spiffe://arthaai/agent/db_agent"


# Immutable per-agent tool scope (least privilege). Real deployment = Rego policy.
ALLOWED: dict[str, set[str]] = {
    "db_agent": {"sql_query", "load_ohlcv"},
    "quant_agent": {"load_ohlcv", "compute_stats"},
    "news_agent": {"hybrid_search"},
    "alt_agent": {"external_api"},
    "asset_manager": {"compute_stats", "kelly"},
    "master_llm": {"llm_complete"},
}


class PolicyViolation(RuntimeError):
    pass


def authorize_tool(identity: AgentIdentity, tool: str) -> None:
    """Raise PolicyViolation if `identity` may not invoke `tool`. (OPA seam.)"""
    scope = ALLOWED.get(identity.agent, set())
    if tool not in scope:
        raise PolicyViolation(
            f"{identity.spiffe_id} is not authorised for tool '{tool}' "
            f"(scope: {sorted(scope) or 'none'})"
        )
