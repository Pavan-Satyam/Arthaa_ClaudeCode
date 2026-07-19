"""MCP Authentication / OAuth 2.1 seam (Tier 1).

Blueprint: ingress negotiates machine-to-machine trust dynamically via OAuth 2.1,
eliminating static long-lived keys. Here we model that as a bearer-token
dependency returning an authenticated Principal. In production this validates a
short-lived OAuth 2.1 / MCP access token against the identity provider; mTLS is
terminated at the gateway (Apigee-style) ahead of this check.

Dev default: if ARTHAAI_GATEWAY_TOKEN is unset, any non-empty bearer is accepted
so the service is runnable locally. Set the env var to require a specific token.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException, status

from arthaai.security import vault


@dataclass(frozen=True)
class Principal:
    subject: str
    scopes: tuple[str, ...]


def require_principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token (OAuth 2.1 / MCP access token).",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    # Credential comes from Vault (falls back to env if Vault is unavailable).
    expected = vault.get_secret("arthaai", "gateway_token", env="ARTHAAI_GATEWAY_TOKEN")
    if expected and token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token.")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Empty token.")
    return Principal(subject="investor", scopes=("analyze:read",))
