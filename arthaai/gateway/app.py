"""Tier 1 FastAPI gateway — the secure entry point to the ArthaAI pipeline.

Applies token-bucket rate limiting (slowapi), OAuth 2.1 / MCP bearer auth, and
dispatches authenticated requests into the Tier 2 LangGraph orchestrator. In
production this sits behind an mTLS-terminating API gateway (blueprint §6).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from arthaai import __version__
from arthaai.gateway.auth import Principal, require_principal

_DASHBOARD = Path(__file__).parent / "static" / "dashboard.html"

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


@app.get("/", response_class=HTMLResponse)
def dashboard(response: Response) -> str:
    """Tier 1 UI — asset page with price, candles, verdict and allocation.

    The gateway sets the bearer token as an httpOnly cookie so the browser
    session is trusted without exposing the credential in the page source.
    JavaScript never touches the token; fetch() sends the cookie automatically.
    """
    from arthaai.config import get_settings
    from arthaai.security import vault

    s = get_settings()
    token = vault.get_secret("arthaai", "gateway_token", env="ARTHAAI_GATEWAY_TOKEN")
    if not token:
        if s.dev_mode:
            token = "dev-token"
        else:
            raise RuntimeError(
                "ARTHAAI_GATEWAY_TOKEN is not set and dev_mode is False — "
                "refusing to serve the dashboard with a guessable fallback credential."
            )
    response.set_cookie(
        key="arthaai_token", value=token, httponly=True, samesite="strict",
        secure=not s.dev_mode,  # True in production (requires TLS)
    )
    return _DASHBOARD.read_text(encoding="utf-8")


@app.get("/ohlcv/{symbol}")
def ohlcv(
    symbol: str,
    limit: int = 120,
    principal: Principal = Depends(require_principal),
) -> dict:
    """Recent OHLCV bars for the dashboard chart; ingests on demand if missing.

    Requires a bearer token (same as /analyze). The dashboard's httpOnly cookie
    is sent automatically by the browser, so the chart loads without the user
    handling a credential.
    """
    from arthaai.data import ingest as ingest_mod
    from arthaai.db import timescale

    symbol = symbol.strip().strip(".").upper()
    df = timescale.load_ohlcv(symbol, limit=limit)
    if df.empty:
        ingest_mod.ingest(symbol)
        df = timescale.load_ohlcv(symbol, limit=limit)
    bars = [
        {"ts": str(r.ts), "open": r.open, "high": r.high, "low": r.low, "close": r.close}
        for r in df.itertuples(index=False)
    ]
    return {"symbol": symbol.upper(), "bars": bars}


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
