"""HashiCorp Vault secrets client (blueprint §6).

Agents request credentials from Vault using their identity rather than reading
env vars or config files. This uses the KV v2 engine mounted at `secret/`. If
Vault is unreachable the loader falls back to the process environment, so local
runs work with or without Vault. Circuit-broken to fail fast on outage.

    put_secret("arthaai", {"gateway_token": "…"})
    get_secret("arthaai", "gateway_token", env="ARTHAAI_GATEWAY_TOKEN")
"""

from __future__ import annotations

import os

import httpx

from arthaai.config import get_settings
from arthaai.resiliency import guarded


def _headers() -> dict[str, str]:
    return {"X-Vault-Token": get_settings().vault_token}


def put_secret(path: str, data: dict[str, str]) -> None:
    """Write a secret to secret/data/<path> (KV v2)."""
    url = f"{get_settings().vault_addr}/v1/secret/data/{path}"
    httpx.post(url, headers=_headers(), json={"data": data}, timeout=3.0).raise_for_status()


def get_secret(path: str, key: str, *, env: str | None = None) -> str | None:
    """Read secret/data/<path>[key]; fall back to `env` if Vault is unavailable."""

    def _read() -> str | None:
        url = f"{get_settings().vault_addr}/v1/secret/data/{path}"
        resp = httpx.get(url, headers=_headers(), timeout=3.0)
        resp.raise_for_status()
        return resp.json()["data"]["data"].get(key)

    def _fallback() -> str | None:
        return os.environ.get(env) if env else None

    value = guarded("vault", _read, fallback=_fallback)
    # If Vault returned nothing (secret absent) still honour the env fallback.
    return value if value is not None else (os.environ.get(env) if env else None)
