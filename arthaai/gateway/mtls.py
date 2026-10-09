"""mTLS termination awareness (ARTHA-110).

mTLS is terminated by the upstream API gateway / service mesh (Envoy, nginx, a
cloud load balancer), not inside this process — the HLD defers it to deploy
infrastructure. This module lets the app *require* proof that upstream
termination actually happened, so a misconfigured deployment that strips mTLS
fails closed instead of silently accepting plaintext.

When ``mtls_required`` is set (and ``dev_mode`` is False), a protected request
must (a) originate from a **trusted proxy** listed in ``mtls_trusted_proxies``
and (b) carry a trusted-proxy header showing the client certificate was verified.

The source-address check is the part that makes this safe: a bare
``X-Forwarded-Client-Cert`` header is client-suppliable, so it is honored only
when the peer address is a known terminator. If no trusted proxies are
configured, enforcement fails closed rather than trusting the header.
"""

from __future__ import annotations

import ipaddress

from fastapi import HTTPException, Request, status

from arthaai.config import get_settings

# Headers a TLS terminator uses to attest client-cert verification.
_XFCC_HEADER = "x-forwarded-client-cert"          # Envoy
_VERIFY_HEADERS = ("x-ssl-client-verify", "x-client-cert-verified")  # nginx / others
_TRUTHY = {"1", "true", "yes", "on", "ok", "success", "verified"}


def _trusted_networks(spec: str) -> list[ipaddress._BaseNetwork]:
    networks = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return networks


def _peer_is_trusted(request: Request, networks: list[ipaddress._BaseNetwork]) -> bool:
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in networks)


def client_cert_verified(request: Request, trusted_proxies: str = "") -> bool:
    """True when a *trusted* proxy attests a verified client certificate.

    Returns False when ``trusted_proxies`` is empty, regardless of headers — an
    untrusted client can always forge the header.
    """
    networks = _trusted_networks(trusted_proxies)
    if not networks or not _peer_is_trusted(request, networks):
        return False
    xfcc = request.headers.get(_XFCC_HEADER)
    if xfcc and xfcc.strip():
        return True  # Envoy populates XFCC only for mTLS connections
    for header in _VERIFY_HEADERS:
        value = request.headers.get(header)
        if value and value.strip().lower() in _TRUTHY:
            return True
    return False


def require_mtls(request: Request) -> None:
    """FastAPI dependency: enforce upstream mTLS when configured.

    No-op unless ``mtls_required`` is set and the app is not in dev mode.
    """
    settings = get_settings()
    if not getattr(settings, "mtls_required", False) or getattr(settings, "dev_mode", False):
        return
    trusted = getattr(settings, "mtls_trusted_proxies", "")
    if not _trusted_networks(trusted):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="mTLS is required but no trusted proxy is configured (fail-closed).",
        )
    if not client_cert_verified(request, trusted):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client certificate required (mTLS is terminated upstream).",
        )