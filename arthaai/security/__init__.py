"""Zero-trust security interfaces (blueprint §6).

INTERFACE STUBS ONLY. Production zero-trust requires infrastructure that cannot
run meaningfully on a single dev machine — SPIFFE/SPIRE identity, HashiCorp Vault,
OPA/Rego sidecars, mTLS via an API gateway, Kubernetes micro-segmentation. These
functions define the seams where that enforcement plugs in and apply a permissive
local default, so application code can already call them and be hardened later
(deployment Sprint 5) without refactoring.
"""

from arthaai.security.policy import authorize_tool, AgentIdentity

__all__ = ["authorize_tool", "AgentIdentity"]
