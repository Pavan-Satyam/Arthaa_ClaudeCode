"""Zero-trust security seam (blueprint §6).

``authorize_tool`` is **real**: it consults the live OPA server
(``security.opa.is_allowed`` → ``policy/arthaai.rego``) and falls back to the
in-process least-privilege map when OPA is unreachable, so enforcement never
silently disappears. ``AgentIdentity`` carries a SPIFFE-ID string.

What remains deploy-infrastructure (not app code): SPIFFE/SPIRE identity issuance,
short-lived JWT binding, mTLS termination at the gateway, and Kubernetes
micro-segmentation. Those plug into the same seam without refactoring callers.
"""

from arthaai.security.policy import AgentIdentity, authorize_tool

__all__ = ["AgentIdentity", "authorize_tool"]
