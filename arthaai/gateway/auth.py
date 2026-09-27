"""MCP Authentication / OAuth 2.1 (Tier 1).

Blueprint: ingress negotiates machine-to-machine trust dynamically via OAuth 2.1,
eliminating static long-lived keys. This module implements two verification
modes, selected by configuration:

1. **OAuth 2.1 / JWT** (``ARTHAAI_OAUTH_JWKS_URL`` set): the bearer token is a
   short-lived access token validated against the identity provider's JWKS —
   signature, expiry (``exp`` is required), issuer and audience. Requires the
   optional ``auth`` extra (``pip install -e ".[auth]"``).
2. **Static token** (``ARTHAAI_GATEWAY_TOKEN`` set): constant-time comparison,
   for local/CI use.

If neither is configured: dev mode accepts any non-empty bearer (so the service
is runnable locally); **production (``dev_mode=False``) refuses** rather than
silently accepting arbitrary tokens.

mTLS is terminated at the gateway ahead of this check (blueprint §6).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from fastapi import Cookie, Header, HTTPException, status

from arthaai.config import get_settings
from arthaai.security import vault


@dataclass(frozen=True)
class Principal:
    subject: str
    scopes: tuple[str, ...]


def _extract_token(authorization: str | None, cookie: str | None) -> str | None:
    """Bearer header (API clients) first, then the httpOnly dashboard cookie."""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token:
            return token
    return cookie or None


def client_key(request) -> str:
    """Rate-limit key: a hash of the bearer token, else the client IP.

    Keying on the credential (not the IP) means a shared NAT doesn't pool limits
    across users, while the raw token is never stored — only a short hash.
    """
    auth = request.headers.get("authorization", "")
    token: str | None = None
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    if not token:
        token = request.cookies.get("arthaai_token")
    if token:
        return "token:" + hashlib.sha256(token.encode()).hexdigest()[:16]
    return request.client.host if request.client else "unknown"


def _verify_jwt(token: str, s) -> Principal:
    """Validate an OAuth 2.1 access token against the configured IdP JWKS."""
    try:
        import jwt
        from jwt import PyJWKClient
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT validation requires the 'auth' extra: pip install -e '.[auth]'.",
        ) from exc

    algorithms = [a.strip() for a in str(getattr(s, "oauth_algorithms", "RS256")).split(",") if a.strip()]
    try:
        signing_key = PyJWKClient(s.oauth_jwks_url).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=algorithms,
            audience=getattr(s, "oauth_audience", "") or None,
            issuer=getattr(s, "oauth_issuer", "") or None,
            options={"require": ["exp"]},  # expiry is mandatory
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - any decode failure is an auth failure
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid access token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    subject = str(claims.get("sub") or "unknown")
    scopes = tuple(str(claims.get("scope", "")).split())
    return Principal(subject=subject, scopes=scopes)


def require_principal(
    authorization: str | None = Header(default=None),
    arthaai_token: str | None = Cookie(default=None),
) -> Principal:
    """Authenticate via bearer header (API clients) or httpOnly cookie (dashboard)."""
    token = _extract_token(authorization, arthaai_token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token (OAuth 2.1 / MCP access token).",
            headers={"WWW-Authenticate": "Bearer"},
        )

    s = get_settings()

    # 1) OAuth 2.1 / JWT against the IdP.
    if getattr(s, "oauth_jwks_url", ""):
        return _verify_jwt(token, s)

    # 2) Static token (constant-time compare).
    expected = vault.get_secret("arthaai", "gateway_token", env="ARTHAAI_GATEWAY_TOKEN")
    if expected:
        if not secrets.compare_digest(token, expected):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token.")
        return Principal(subject="investor", scopes=("analyze:read",))

    # 3) Nothing configured.
    if getattr(s, "dev_mode", False):
        return Principal(subject="dev", scopes=("analyze:read",))
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="No authentication configured: set ARTHAAI_GATEWAY_TOKEN or ARTHAAI_OAUTH_JWKS_URL.",
    )
