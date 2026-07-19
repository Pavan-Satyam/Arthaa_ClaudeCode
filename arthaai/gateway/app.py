"""Tier 1 FastAPI gateway — the secure entry point to the ArthaAI pipeline.

Applies token-bucket rate limiting (slowapi), OAuth 2.1 / MCP bearer auth, and
dispatches authenticated requests into the Tier 2 LangGraph orchestrator. In
production this sits behind an mTLS-terminating API gateway (blueprint §6).
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from arthaai import __version__
from arthaai.gateway.auth import Principal, require_principal

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="ArthaAI Gateway", version=__version__, description="Tier 1 secure ingress.")
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Try again shortly."})


class AnalyzeResponse(BaseModel):
    symbol: str
    verdict: dict
    allocation: dict
    evidence: dict


@app.get("/health")
def health() -> dict:
    from arthaai.db import timescale

    out = {"service": "arthaai-gateway", "version": __version__}
    try:
        out["timescaledb"] = timescale.ping()
        out["status"] = "ok"
    except Exception as exc:  # noqa: BLE001
        out["status"] = "degraded"
        out["error"] = str(exc)
    return out


@app.post("/analyze/{symbol}", response_model=AnalyzeResponse)
@limiter.limit("10/minute")
def analyze(
    symbol: str,
    request: Request,
    skip_ingest: bool = False,
    principal: Principal = Depends(require_principal),
) -> AnalyzeResponse:
    """Run the full multi-agent analysis for an asset. Requires a bearer token."""
    from arthaai.orchestration import analyze as run_analyze

    state = run_analyze(symbol, skip_ingest=skip_ingest)
    return AnalyzeResponse(
        symbol=symbol.upper(),
        verdict=state.get("verdict", {}),
        allocation=state.get("allocation", {}),
        evidence={k: state.get(k, {}) for k in ("db", "quant", "news", "alt")},
    )
