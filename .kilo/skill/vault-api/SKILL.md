---
name: vault-api
description: HashiCorp Vault KV v2 REST API — read/write secrets, health, token ops. Use for the Vault client in arthaai/security/vault.py and when debugging secret paths or 404s.
---

# HashiCorp Vault KV v2 REST API

ArthaAI talks to Vault over HTTP (`arthaai/security/vault.py`, `httpx`, KV v2 at `secret/`).

## Endpoints used in this repo
- **Read**: `GET {VAULT_ADDR}/v1/secret/data/{path}` with header `X-Vault-Token: <token>`
  → the value is at `resp.json()["data"]["data"][key]`.
- **Write**: `POST {VAULT_ADDR}/v1/secret/data/{path}` with JSON `{ "data": { ... } }`.
- **Health**: `GET {VAULT_ADDR}/v1/sys/health`.
- **Dev seed**: `VAULT_DEV_ROOT_TOKEN_ID` (compose default `arthaai-root`); seed with `arthaai seed-secrets`.

## Rules for this repository
- The **env fallback is intentional**: `get_secret(path, key, env=...)` returns the environment
  variable when Vault is unreachable *or* the secret is absent. Do not remove it.
- Wrap calls in the circuit breaker (`guarded("vault", ...)`) so a Vault outage degrades, never crashes.
- Never commit a real token. A `404` on `secret/data/arthaai` is expected until seeded — not a bug.
- Keys used here: `gateway_token`, `anthropic_api_key`, `gemini_api_key`, `local_api_key`.
