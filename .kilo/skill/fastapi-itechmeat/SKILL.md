---
name: fastapi-itechmeat
description: FastAPI + Pydantic + OAuth2/JWT patterns and security. Use for the ArthaAI gateway (arthaai/gateway/app.py, auth.py, mtls.py), rate limiting, and authenticated endpoints.
---

# FastAPI in ArthaAI

The gateway is `arthaai/gateway/app.py` (FastAPI + uvicorn) with `slowapi` rate limiting,
`auth.py` (bearer header or httpOnly cookie; JWT via IdP JWKS, or a constant-time static token),
and `mtls.py` (fail-closed XFCC check gated on trusted proxies).

## Conventions in this repository
- Every non-public route declares `principal: Principal = Depends(require_principal)` and, where
  mTLS applies, `_mtls: None = Depends(require_mtls)`.
- **Fail closed**: unconfigured + `dev_mode=False` → `503`, never "accept anything".
- JWT must require `exp` (`options={"require": ["exp"]}`) and verify `iss`/`aud` when configured.
- The rate-limit key is a **hash of the bearer token** (falling back to client IP) — never the raw token.
- Prefer `response_model=` Pydantic models; keep `/` and `/health` unauthenticated.
- Avoid blocking calls in handlers; DB work goes through `arthaai.db.timescale`.

## Testing
- Use `fastapi.testclient.TestClient`. Note a dashboard `GET /` sets an httpOnly cookie **on the
  shared client**, so an auth test that expects `401` must use a fresh `TestClient(app)`.
