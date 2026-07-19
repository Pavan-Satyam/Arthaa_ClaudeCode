"""Policy enforcement seam (SPIFFE identity + OPA policy-as-code).

`authorize_tool` now consults the live OPA server (via security.opa) which
evaluates policy/arthaai.rego. If OPA is unreachable it falls back to the
in-process least-privilege map, so enforcement never silently disappears.
Production identity is a SPIFFE ID bound to a short-lived JWT issued by SPIRE;
here AgentIdentity carries the SPIFFE ID string.
"""

from __future__ import annotations

from dataclasses import dataclass

from arthaai.security import opa

# Re-exported so callers/tests can reference the canonical scope map.
ALLOWED = opa.ALLOWED


@dataclass(frozen=True)
class AgentIdentity:
    """Stand-in for a SPIFFE ID bound to a short-lived JWT."""

    agent: str
    spiffe_id: str


class PolicyViolation(RuntimeError):
    pass


def authorize_tool(identity: AgentIdentity, tool: str) -> None:
    """Raise PolicyViolation if `identity` may not invoke `tool` (OPA-backed)."""
    if not opa.is_allowed(identity.agent, tool):
        scope = sorted(ALLOWED.get(identity.agent, set()))
        raise PolicyViolation(
            f"{identity.spiffe_id} is not authorised for tool '{tool}' "
            f"(scope: {scope or 'none'})"
        )
