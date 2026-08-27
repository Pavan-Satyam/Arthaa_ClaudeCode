# ArthaAI — Architecture Status Report

> Last updated: 2026-08-25 · Branch: `feat/arthaai-core` · 57 DB-independent tests passing in 6s

---

## Table of Contents

- [Tier 1 — Interface & Ingress](#tier-1--interface--ingress)
- [Tier 2 — Intelligence Core](#tier-2--intelligence-core)
- [Tier 3 — Oversight & Sizing](#tier-3--oversight--sizing)
- [Tier 4 — Action](#tier-4--action)
- [Overall System Summary](#overall-system-summary)
  - [What was added on 2026-08-25](#what-was-added-on-2026-08-25)
  - [Commits](#commits-5-total-unpushed)
  - [Test count](#test-count-57-db-independent-tests-pass-in-6s)

---

## Tier 1 — Interface & Ingress

### What the blueprint planned

The architecture specifies Tier 1 as the secure entry point — how a request gets in safely. Three components:

1. **Web Dashboard** — type a ticker, see verdict + sizing + chart
2. **FastAPI Gateway** — entry point with token auth + rate limiting
3. **mTLS + OAuth 2.1** — encrypted service mesh, deploy-time hardening

The design rules for Tier 1:
- Every endpoint behind bearer-token authentication (OAuth 2.1 / MCP access token)
- Token-bucket rate limiting (slowapi)
- In production, mTLS is terminated at the gateway (Apigee-style) ahead of the auth check
- Secrets fetched from Vault (falls back to env if Vault is down)
- Dashboard serves a browser session without the user handling a credential

### What's implemented (today)

#### Gateway (`gateway/app.py` — 129 lines)

| Feature | Implementation | Status |
|---------|---------------|--------|
| FastAPI app with rate limiting | `slowapi` token-bucket, 10/min on `/analyze` | ✅ |
| `/analyze/{symbol}` | Auth-required POST; dispatches to Tier 2 LangGraph orchestrator; returns verdict + allocation + evidence | ✅ |
| `/ohlcv/{symbol}` | Auth-required GET; loads from TimescaleDB, ingests on demand if missing; returns candlestick bars | ✅ ← fixed this session |
| `/health` | Open; pings TimescaleDB; reports degraded if down | ✅ |
| `/` (dashboard) | Sets httpOnly cookie with gateway token; serves HTML dashboard | ✅ ← fixed this session |

#### Auth (`gateway/auth.py` — 54 lines)

| Feature | Implementation | Status |
|---------|---------------|--------|
| `require_principal` dependency | Checks `Authorization: Bearer` header (API clients) **and** `arthaai_token` httpOnly cookie (dashboard browser sessions) | ✅ ← new this session |
| Token validation | Compares against Vault secret (falls back to `ARTHAAI_GATEWAY_TOKEN` env) | ✅ |
| 401 on missing token | `HTTPException` with `WWW-Authenticate: Bearer` header | ✅ |
| 403 on invalid token | Separate HTTPException for bad credential | ✅ |
| `Principal` dataclass | Carries `subject` + `scopes` (currently `("analyze:read",)`) | ✅ |

#### Dashboard (`gateway/static/dashboard.html` — 155 lines)

| Feature | Implementation | Status |
|---------|---------------|--------|
| Candlestick chart | Canvas-based, renders OHLCV bars with green/red coloring | ✅ |
| Symbol input + Analyze button | Calls `/analyze/{symbol}`, renders verdict + allocation + evidence | ✅ |
| Token handling | No token in JS — `fetch()` sends `credentials: "same-origin"` (httpOnly cookie) | ✅ ← fixed this session |
| Verdict display | Direction (color-coded), confidence %, LLM source, rationale text | ✅ |
| Allocation display | Kelly fraction %, policy-cap note, evidence table | ✅ |
| Evidence table | Per-agent rows: technical trend, μ/σ, news sentiment, physical/alt | ✅ |

#### Config (`config.py` — 83 lines)

| Feature | Implementation | Status |
|---------|---------------|--------|
| `dev_mode` setting | Controls cookie `secure` flag and dev-token fallback behavior | ✅ ← new this session |
| `dev_mode=True` (default) | `secure=False` (HTTP ok), `dev-token` fallback allowed | ✅ |
| `dev_mode=False` (production) | `secure=True` (requires TLS), refuses to serve with `dev-token` fallback | ✅ |
| Vault integration | Gateway token fetched via `vault.get_secret()` with env fallback | ✅ |

#### Test coverage (`test_gateway.py` — 7 tests, 83 lines)

| Test | What it verifies |
|------|-----------------|
| `test_analyze_requires_bearer` | 401 without auth |
| `test_analyze_rejects_non_bearer` | 401 on `Basic` scheme |
| `test_health_is_open` | Health check works without auth |
| `test_ohlcv_requires_auth` | 401 without auth (was open before) |
| `test_ohlcv_rejects_non_bearer` | 401 on `Basic` scheme |
| `test_dashboard_sets_httponly_cookie` | Cookie is set, `httponly` flag present, no token in HTML |
| `test_dashboard_cookie_authenticates_ohlcv` | Cookie from dashboard authenticates `/ohlcv` |
| `test_dashboard_refuses_dev_token_in_production` | `dev_mode=False` + no token → 500 (refuses to serve) |

### What was fixed this session

Two security holes were closed:

1. **`/ohlcv/{symbol}` was unauthenticated** — anyone could fetch OHLCV data and trigger ingestion. Now requires `Depends(require_principal)`.

2. **Token was injected into HTML** — the dashboard replaced `__ARTHAAI_TOKEN__` in the page source with the actual bearer token, visible in browser devtools / page source / any proxy cache. Now the dashboard sets an httpOnly cookie (`arthaai_token`) with `samesite="strict"`, and the JS never touches the token — `fetch()` with `credentials: "same-origin"` sends the cookie automatically.

Two production-hardening gaps were also closed:

3. **`secure=False` was hardcoded** — now derived from `dev_mode` config: `secure=not s.dev_mode`. Production (`dev_mode=False`) enforces TLS-only cookies.

4. **`dev-token` fallback was unconditional** — now refused when `dev_mode=False` and no real token is available from Vault/env. The dashboard raises `RuntimeError` instead of serving with a guessable credential.

A serialization bug was fixed on 2026-08-25:

5. **`numpy.bool_` serialization crash** — the `/analyze` endpoint returned 500 for all assets because `Allocation.capped_by_policy` was a `numpy.bool_` that Pydantic couldn't serialize to JSON. Fixed by wrapping with `float()` and `bool()` in `asset_manager.size()` so all Allocation fields are native Python types.

### What can be improved

#### Authentication & Identity

| Gap | Impact | Effort |
|-----|--------|--------|
| **No real OAuth 2.1 / OIDC integration** — currently a static bearer token compared against a Vault secret. The blueprint calls for short-lived OAuth 2.1 / MCP access tokens validated against an identity provider (Keycloak / Auth0 / Okta). | A stolen token is valid indefinitely (no expiry, no refresh, no revocation). Single-tenant — no per-user identity, no RBAC beyond `analyze:read`. | Medium — wire `require_principal` to validate a JWT against a JWKS endpoint, add token refresh + revocation |
| **No token expiry or rotation** — the gateway token is static. | Compromised tokens never expire. | Low — add `exp` claim validation + periodic Vault rotation |
| **No per-user identity** — `Principal.subject` is always `"investor"`. | No audit trail per user; no RBAC beyond the single `analyze:read` scope. | Medium — parse JWT `sub` claim into `Principal.subject`, add scope-based access control |
| **mTLS not implemented** — deferred to deployment infrastructure. The blueprint specifies mTLS termination at the gateway. | Traffic between client and gateway is not mutually authenticated in dev. In production this is handled by the API gateway / load balancer. | High — this is infra (Istio / Linkerd / nginx), not application code |

#### Rate Limiting

| Gap | Impact | Effort |
|-----|--------|--------|
| **Rate limit only on `/analyze`** — `/ohlcv` and `/health` have no rate limit. | A malicious session could hammer `/ohlcv` to trigger repeated ingest calls (yfinance rate limits) or exhaust DB connections. | Low — add `@limiter.limit` to `/ohlcv` |
| **Rate limit is per-IP, not per-token** — `slowapi` uses `get_remote_address`. Behind a NAT/load balancer, all users share one IP. | A single noisy user can exhaust the limit for everyone; or conversely, many users behind one NAT can exceed limits individually. | Low — change `key_func` to use the authenticated `Principal.subject` |
| **No burst capacity** — flat 10/min. | No headroom for legitimate burst traffic (e.g., loading a dashboard with chart + analysis). | Low — switch to a two-tier limit (e.g., 10/min sustained + 30 burst) |

#### Dashboard UX

| Gap | Impact | Effort |
|-----|--------|--------|
| **No real-time updates** — the dashboard is a one-shot fetch. The blueprint implies a live console. | User must click Analyze each time; no streaming price updates, no live verdict refresh. | Medium — add WebSocket or SSE for streaming OHLCV + verdict updates |
| **No multi-asset view** — single symbol at a time. The `arthaai compare` command exists in CLI but not in the dashboard. | No way to compare signals across assets from the UI. | Medium — add a comparison table view |
| **No error retry or loading state** — the "running multi-agent pipeline…" text is the only feedback. | LLM calls can take 10-30s with no progress indicator. | Low — add a progress bar or per-agent status stream |
| **Chart is Canvas-based, not interactive** — no zoom, pan, tooltip, or crosshair. | Limited chart interaction; hard to inspect specific candles. | Medium — replace with lightweight charting lib (e.g., lightweight-charts) |
| **No allocation history or backtest view** — the backtest engine exists but isn't exposed in the dashboard. | No way to see historical performance or signal edge from the UI. | Medium — add a backtest panel |

#### API Surface

| Gap | Impact | Effort |
|-----|--------|--------|
| **No WebSocket streaming** — the blueprint implies real-time data flow, but the gateway is request-response only. | No push updates; client must poll. | Medium — add WebSocket endpoint for streaming verdicts / OHLCV |
| **No `/backtest` endpoint** — the backtest engine is only accessible via CLI. | Can't run backtests from the gateway / dashboard. | Low — add POST `/backtest/{symbol}` endpoint |
| **No `/eval` endpoint** — the LLM eval harness is only accessible via CLI. | Can't evaluate LLM quality from the gateway. | Low — add GET `/eval` endpoint |
| **No `/compare` endpoint** — the signal comparison is only in CLI. | Can't compare signals from the gateway. | Low — add GET `/compare?symbols=...` endpoint |
| **No OpenAPI customization** — the FastAPI auto-docs are default. | No custom schemas, examples, or response models beyond `AnalyzeResponse`. | Low — add response models for all endpoints |

#### Security Hardening

| Gap | Impact | Effort |
|-----|--------|--------|
| **No CORS policy** — the FastAPI app has no CORS middleware. | Browser clients from other origins can't call the API; or in production, all origins are allowed by default (no explicit deny). | Low — add `CORSMiddleware` with explicit allowed origins |
| **No CSRF protection for cookie auth** — `samesite="strict"` mitigates most CSRF, but not same-site subdomain attacks. | A malicious subdomain could potentially craft requests that send the cookie. | Low — add CSRF token header validation for state-changing endpoints |
| **No request signing / replay protection** — every request is a fresh call. | No way to detect replay attacks or tampered requests. | Medium — add HMAC request signing |
| **No audit log** — auth decisions (allow/deny) are not logged. | No trail of who called what and when. | Low — add structlog audit entries in `require_principal` |

### Tier 1 Summary

| Area | Planned | Implemented | Gaps |
|------|---------|-------------|------|
| FastAPI gateway | ✅ | ✅ | — |
| Token auth (bearer) | ✅ | ✅ | No real OAuth 2.1 / JWT validation |
| Cookie auth (dashboard) | ✅ | ✅ ← fixed | — |
| Rate limiting | ✅ | ✅ (partial) | Only `/analyze`, per-IP not per-token |
| Dashboard UI | ✅ | ✅ | No real-time, no multi-asset, no backtest view |
| mTLS + OAuth 2.1 | ✅ (deferred) | ○ seam ready | Deployment infra — needs k8s / service mesh |
| Vault secrets | ✅ | ✅ | — |
| Production hardening | ✅ | ✅ ← fixed | `dev_mode` config, secure cookies, dev-token refusal |

**Implementation: ~85% of the Tier 1 blueprint.**

---

## Tier 2 — Intelligence Core

### What the blueprint planned

Tier 2 is where analysis and data live — the brain of the system. The architecture specifies:

**Orchestration:**
1. **LangGraph Orchestrator** — deterministic DAG with shared GraphState; same path every run
2. **Kafka/Redpanda Bus** — event bus for fan-out and ingestion decoupling
3. **StateStore** — GraphState where every agent's findings converge

**Agents (fan-out workers):**
4. **DB_Agent** — deterministic indicators (SMA/RSI/trend)
5. **Quant_Agent ★** — "Alpha-Zoo factor engine → tabular signal model. The edge lives here." This was flagged as "build next" in the architecture doc.
6. **News_Agent** — Qdrant hybrid search with "real embeddings + live feed" (was partial)
7. **Alt_Agent** — satellite/cargo data (Kpler, Ursa) — paid feeds, deferred
8. **Correlation Regime** — detects "risk-off fusion"; risk context to the Brain — "build next"

**Master LLM:**
9. **Master Reasoning LLM** — explains and resolves conflicts. Chain: Gemini → local → Claude → offline. **Never predicts a number.**

**Data layer:**
10. **yfinance → TimescaleDB** — OHLCV hypertable, SQL-native aggregates
11. **Qdrant** — news vectors, per-asset filtered

**Design rules:**
- Deterministic quant layer computes all numbers; LLM only synthesises
- Kelly sizing runs on statistics, never on LLM-invented probabilities
- Circuit breakers on every external dependency
- OPA policy enforcement on every agent tool call

### What's implemented (today)

#### LangGraph Orchestrator (`orchestration/graph.py` — 86 lines)

| Feature | Implementation | Status |
|---------|---------------|--------|
| StateGraph with GraphState | `StateGraph(GraphState)` — TypedDict with `db`, `quant`, `news`, `alt`, `verdict`, `allocation` | ✅ |
| Fan-out: ingest → 4 agents | Edges from `ingest` to `db_agent`, `quant_agent`, `news_agent`, `alt_agent` | ✅ |
| Converge: agents → master_llm | Each agent edge → `master_llm` (the State Store join) | ✅ |
| Sequential: master_llm → asset_manager → END | Edge chain after the join | ✅ |
| `analyze(symbol)` entry point | Builds graph, invokes with initial state, returns final GraphState | ✅ |
| `skip_ingest` flag | Skips yfinance fetch when data already in TimescaleDB | ✅ |

#### GraphState (`orchestration/state.py` — 21 lines)

| Field | Written by | Read by |
|-------|-----------|---------|
| `symbol` | initial state | all agents |
| `skip_ingest` | initial state | `_ingest` node |
| `db` | `db_agent.run()` | `master_llm`, dashboard |
| `quant` | `quant_agent.run()` | `master_llm`, `asset_manager` |
| `news` | `news_agent.run()` | `master_llm`, dashboard |
| `alt` | `alt_agent.run()` | `master_llm`, dashboard |
| `verdict` | `master_llm.reason()` | `asset_manager`, dashboard |
| `allocation` | `asset_manager.size()` | dashboard |

#### DB_Agent (`agents/db_agent.py` — 68 lines)

| Feature | Implementation | Status |
|---------|---------------|--------|
| OHLCV load from TimescaleDB | `timescale.load_ohlcv(symbol)` | ✅ |
| SMA-20, SMA-50, RSI-14 (Wilder) | `indicators.sma()`, `indicators.rsi()` | ✅ ← fixed |
| ADX-14 regime classification | `indicators.adx(high, low, close)` → trending / weak-trend / choppy | ✅ ← new |
| Signal selector (ADX-driven) | ADX ≥ 25 → `breakout_signal`; else → `trend_signal` | ✅ ← new |
| `signal_class` in output | Reports "trend" or "breakout" so downstream agents match | ✅ ← new |
| OPA authorization | `authorize_tool(IDENTITY, "load_ohlcv")` | ✅ |
| Empty-data fallback | Returns `{"available": False, "reason": ...}` | ✅ |

#### Quant Agent (`agents/quant_agent.py` — 50 lines)

| Feature | Implementation | Status |
|---------|---------------|--------|
| Annualised return/variance/volatility | `indicators.annualised_stats(close)` | ✅ |
| Signal-conditioned Kelly inputs (W, R) | `indicators.signal_kelly_stats()` — the signal's actual hit rate and payoff, not the asset's unconditional daily win rate | ✅ ← new |
| Signal class matches db_agent | Uses same `BREAKOUT_ADX_THRESHOLD` from `indicators.py`; breakout path uses `breakout_positions` (O(n)) | ✅ ← new |
| `signal_class` in output | So the Asset Manager knows which signal produced the Kelly stats | ✅ ← new |
| OPA authorization | `authorize_tool(IDENTITY, "compute_stats")` | ✅ |

#### News Agent (`agents/news_agent.py` — 35 lines)

| Feature | Implementation | Status |
|---------|---------------|--------|
| Qdrant hybrid search | Hard ticker filter → semantic similarity via `qdrant.hybrid_search()` | ✅ |
| Embeddings | `fastembed BAAI/bge-small-en-v1.5` (local ONNX, 384-dim); falls back to deterministic hash if fastembed is not installed | ✅ ← fixed |
| Sentiment aggregation | Average sentiment across top-5 hits; label = bullish/bearish/mixed | ✅ |
| Circuit breaker | `guarded("qdrant", _search, fallback=list)` — degrades to empty on outage | ✅ |
| OPA authorization | `authorize_tool(IDENTITY, "hybrid_search")` | ✅ |

#### Alt Agent (`agents/alt_agent.py` — 38 lines)

| Feature | Implementation | Status |
|---------|---------------|--------|
| Synthetic physical signals | Hardcoded per-commodity ETF stubs (USO, GLD, SLV, DBC) | ○ stub |
| Equity abstention | Returns `{"available": False}` for non-commodity ETFs | ✅ |
| OPA authorization | `authorize_tool(IDENTITY, "external_api")` | ✅ |

#### Master Reasoning LLM (`agents/master_llm.py` — 226 lines)

| Feature | Implementation | Status |
|---------|---------------|--------|
| Provider chain | `anthropic → gemini → local → offline` (configurable via `ARTHAAI_LLM_CHAIN`) | ✅ |
| Circuit breaker per provider | `guarded(f"llm:{name}", ...)` — trips after 3 failures, resets in 30s | ✅ |
| Offline deterministic reasoner | Weighted evidence blend: technical (0.45) + news (0.30) + alt (0.25); direction threshold ±0.12; confidence = 0.5 + abs(score)/2 | ✅ |
| Claude provider | Anthropic SDK; model `claude-sonnet-5`; vault-keyed | ✅ |
| Gemini provider | Google REST API; model `gemini-2.5-flash`; thinkingBudget=0 to avoid JSON truncation | ✅ |
| Local provider | OpenAI-compatible endpoint (Ollama/LM Studio/vLLM); model `llama3.1` | ✅ |
| Verdict parsing | Lenient JSON extraction (fenced code blocks, surrounding prose); confidence clamped [0,1]; bad direction → neutral | ✅ |
| System prompt | "You do NOT compute numbers; you synthesise… Return ONLY compact JSON…" | ✅ |
| Rationale audit trail | Requires "I choose this because…" sentence | ✅ |
| OPA authorization | `authorize_tool(IDENTITY, "llm_complete")` | ✅ |
| `provider_status()` | Probes each provider in the chain for reachability | ✅ |

#### Data Layer

**TimescaleDB (`db/timescale.py` — 100 lines)**

| Feature | Implementation | Status |
|---------|---------------|--------|
| Connection pooling | `@contextmanager` connection factory | ✅ |
| `ensure_asset()` | Auto-registers any ticker (FK constraint) | ✅ |
| `upsert_ohlcv()` | INSERT ON CONFLICT DO UPDATE; idempotent re-ingest | ✅ |
| `load_ohlcv()` | Recent N bars ascending by time | ✅ |
| `asset_meta()` | Returns name, asset_class, exchange | ✅ |
| `latest_ts()` | Last bar timestamp (for incremental ingest) | ✅ |
| `ping()` | Returns TimescaleDB extension version | ✅ |

**Qdrant (`db/qdrant.py` — 106 lines)**

| Feature | Implementation | Status |
|---------|---------------|--------|
| Collection creation | `ensure_collection()` with cosine distance, 384-dim | ✅ |
| `upsert_news()` | Embeds headlines, stores with ticker/sentiment/source payload | ✅ |
| `hybrid_search()` | Hard ticker filter (must) → semantic similarity query | ✅ |
| Embedding model | `fastembed BAAI/bge-small-en-v1.5` (local ONNX); hash fallback | ✅ ← fixed |
| `NewsHit` dataclass | headline, source, sentiment, score | ✅ |

**yfinance ingest (`data/ingest.py` — 74 lines)**

| Feature | Implementation | Status |
|---------|---------------|--------|
| 2-year lookback, daily bars | `yf.download(symbol, start=start, interval="1d")` | ✅ |
| MultiIndex column handling | Flattens yfinance's nested columns | ✅ |
| Auto-registration | `ensure_asset()` before upsert so any ticker works | ✅ |
| Kafka event publish | Best-effort, never blocks ingestion | ✅ |
| Friendly metadata | yfinance `shortName` + `quoteType` → asset class | ✅ |

**London Strategic Edge (LSE) provider (`data/lse.py` — 118 lines)** ← new 2026-08-25

| Feature | Implementation | Status |
|---------|---------------|--------|
| API candle fetch | `GET /v1/candles` with `X-API-Key` header; timeframes: 1m, 5m, 1h, 1d | ✅ ← new |
| DataFrame conversion | LSE JSON → `ts, open, high, low, close, volume` (same schema as yfinance) | ✅ ← new |
| Incremental ingest | Uses `latest_ts()` to fetch only new bars; off-by-one guard fixed | ✅ ← new |
| 404 handling | Symbols not on LSE (e.g. USO) return empty → caller falls back to yfinance | ✅ ← new |
| Asset auto-registration | `ensure_asset()` with friendly name + asset class before upsert | ✅ ← new |
| API key security | Key in `.env` (gitignored), read via `os.environ.get`; never in code or URLs | ✅ ← new |
| `arthaai ingest-lse` CLI | `arthaai ingest-lse GLD --days 730 --timeframe 1d` | ✅ ← new |

**Kafka/Redpanda (`data/consumer.py` — 49 lines)**

| Feature | Implementation | Status |
|---------|---------------|--------|
| Consumer group | `arthaai-ingest-worker`, earliest offset | ✅ |
| Event logging | structlog per-event | ✅ |
| `consume(max_messages)` | Polled loop with configurable message count | ✅ |

#### Test coverage for Tier 2

| Test file | Tests | What it covers |
|-----------|-------|---------------|
| `test_llm.py` | 5 | Verdict parsing (fenced JSON, bad direction, surrounding prose), chain fallback to offline, chain always ends offline |
| `test_indicators.py` | 15 | SMA, RSI bounds, annualised stats, trend signal labels, signal Kelly stats (trend, random walk, bearish wins, insufficient history), wr_from_tallies, vectorization equivalence, breakout path |
| `test_eval.py` | 10 | Golden fixtures, rationale check, confidence bands, calibration score (perfect, anti, no-signal, too-few), offline passes all, aggregation |
| `test_backtest.py` | 3 | Drawdown, monotonic, serialization |
| `test_lse.py` | 4 | 404 returns empty, candle response parsing, missing API key raises, friendly meta mapping ← new |

### What was fixed/upgraded this session

| Component | Before | After |
|-----------|--------|-------|
| RSI | Plain rolling mean (wrong) | Wilder smoothing via `_wilder_rma()` |
| `trend_signal` | Bare SMA-20/50 cross (whipsaws) | Multi-timeframe: SMA-20/50 + SMA-200 filter + ROC + RSI exhaustion + asymmetric shorts + flat-on-disagreement |
| Signal Kelly stats | Asset's unconditional daily win rate | Signal-conditioned (W, R) — the signal's actual hit rate and payoff |
| `_trend_signal_series` | O(n²) per-bar recomputation | O(n) vectorized; `trend_signal` delegates to it |
| `breakout_signal` | No runtime caller (dead code) | Wired into `db_agent.run()` via ADX selector |
| `breakout_positions` | — | Stateful O(n), look-ahead-safe, ADX gate |
| ADX regime | — | `_adx_series()` + `adx()`; wired into db_agent + breakout gate |
| Shared constants | Threshold/window duplicated per-agent | `BREAKOUT_ADX_THRESHOLD`, `BREAKOUT_ENTRY_WINDOW`, `BREAKOUT_EXIT_WINDOW` in `indicators.py` |
| Embeddings | Hash fallback (cosine 0.22) | `fastembed BAAI/bge-small-en-v1.5` (cosine 0.98) |
| Signed-return bug | `win_sum += rt` (bearish wins corrupt R) | `win_sum += abs(rt)` (direction-agnostic) |
| LSE data provider | — (yfinance only) | `arthaai/data/lse.py` — LSE API provider with incremental ingest, 404 fallback, `ingest-lse` CLI command |
| numpy serialization | `/analyze` crashed with 500 (`numpy.bool_` not JSON-serializable) | `float()` / `bool()` wrappers in `asset_manager.size()` — native Python types throughout |
| Off-by-one in LSE incremental | — | Fixed: guard checks `last.date() >= now.date()` not `start.date() >= now.date()` |

### What can be improved

#### Quant Agent — "The edge lives here" (blueprint's words)

This is the highest-priority area. The blueprint calls Quant_Agent the ★ star component with an "Alpha-Zoo factor engine" and "tabular signal model." Currently it only computes basic annualised stats + signal Kelly W/R.

| Gap | Impact | Effort |
|-----|--------|--------|
| **No multi-factor model** — the blueprint specifies an "Alpha-Zoo factor engine" with a tabular signal model. Currently Quant_Agent computes μ, σ², W, R and nothing else. | The quant layer is thin — no factor exposure analysis, no alpha decomposition, no cross-sectional ranking. Kelly sizing is based on a single signal's hit rate, not a factor portfolio's edge. | High — implement factor model: momentum, mean-reversion, volatility, value, quality factors; combine into a tabular signal with factor weights; compute Sharpe per factor |
| **No correlation/regime detection** — the blueprint specifies a "Correlation Regime" agent that detects "risk-off fusion" and provides risk context to the Brain. | No regime-aware position sizing; no cross-asset correlation matrix; no tail-risk adjustment; the system doesn't know when correlations break down (2008, COVID, etc.) | High — add correlation regime agent: rolling correlation matrix, hierarchical clustering for regime detection, tail-risk overlay |
| **No portfolio-level Kelly** — Kelly sizing is per-asset, not portfolio-aware. | Two perfectly correlated assets each get 5% → 10% correlated exposure, not 5% portfolio-level. No diversification benefit in sizing. | Medium — implement Kelly portfolio: covariance matrix → optimal weights → policy cap per-asset + portfolio cap |
| **No volatility regime** — the quant layer computes σ but doesn't classify volatility regimes (low-vol, high-vol, crisis). | Kelly fraction doesn't adjust for regime; same 0.25x in calm and turbulent markets | Medium — add volatility regime: GARCH or rolling-vol percentile; adjust Kelly fraction by regime |
| **No covariance estimation** — no rolling covariance between assets for portfolio construction. | Can't compute portfolio Kelly; can't detect diversification opportunities; can't hedge | Medium — add rolling covariance matrix (shrinkage estimator: Ledoit-Wolf) |
| **No alpha decay tracking** — signals don't track how their edge decays over time. | A signal that worked 6 months ago may be stale; no mechanism to detect or retire it | Medium — add signal decay tracking: rolling hit rate over time windows; auto-retire signals with decayed edge |

#### DB_Agent — technical indicators

| Gap | Impact | Effort |
|-----|--------|--------|
| **Limited indicator set** — only SMA, RSI, ADX. No MACD, Bollinger Bands, ATR, OBV, VWAP, Ichimoku, Parabolic SAR. | The technical layer misses common indicators that traders use for confirmation and regime detection | Medium — add indicator library: MACD (momentum), Bollinger Bands (volatility), ATR (risk sizing), OBV/VWAP (volume), Ichimoku (trend) |
| **No volume analysis** — volume is loaded but never used in any signal. | Breakouts on low volume are less reliable; no volume confirmation for any signal | Low — add volume analysis: OBV, VWAP, volume-weighted breakout confirmation |
| **No multi-timeframe analysis** — signals use only daily bars. No weekly/monthly cross-reference. | A daily bullish signal may contradict a weekly bearish trend; no multi-timeframe confluence check | Medium — add multi-timeframe: load weekly + monthly bars, compute signals on each, confluence score |
| **No support/resistance detection** — no automated S/R levels. | Breakout entries are Donchian-only; no dynamic S/R-based entry/exit | Medium — add S/R detection: pivot points, prior swing highs/lows, volume-profile levels |
| **No candlestick patterns** — no pattern recognition (doji, engulfing, hammer, etc.). | Patterns are the most common technical confirmation traders use; completely absent | Medium — add pattern library: engulfing, doji, hammer, shooting star, three white soldiers |

#### News Agent — "needs real embeddings + live feed"

| Gap | Impact | Effort |
|-----|--------|--------|
| **No live news ingestion** — only 8 hardcoded seed articles in Qdrant. The blueprint calls for live feeds from Permutable / LSEG / S&P. | News sentiment is static; no real-time news flow; the "live" analysis uses stale data | High — add live news ingestion: RSS/API feeds from financial news sources (Reuters, Bloomberg API, Finnhub, NewsAPI); real-time embedding + scoring pipeline |
| **No web scraping** — no crawling of financial news sites, SEC filings, earnings transcripts, analyst reports. | The system can't access the vast majority of unstructured financial data available on the web | High — add web scraping: BeautifulSoup/Scrapy for financial news sites; SEC EDGAR for filings; earnings call transcripts from Motley Fool/Seeking Alpha |
| **No real-time sentiment scoring** — sentiment is pre-scored in seed data. In production, it should come from the embedding + scoring pipeline. | No live sentiment classification; no NLP model for bullish/bearish/neutral scoring | Medium — add sentiment classifier: fine-tuned FinBERT or use LLM for zero-shot sentiment on each headline; store sentiment in Qdrant payload |
| **No entity extraction** — no NER for companies, people, events, commodities mentioned in news. | Can't link news to specific assets programmatically; can't detect causal relationships | Medium — add NER: spaCy or LLM for entity extraction; link entities to ticker symbols |
| **No event detection** — no classification of news events (earnings, M&A, regulatory, macro, etc.). | Can't weight news by event type (earnings beats matter more than general market commentary) | Medium — add event classification: fine-tuned classifier or LLM for event type; weight by event importance |
| **No news decay** — all news is treated equally regardless of age. | A 2-week-old article has the same weight as today's breaking news | Low — add time-decay: exponential weighting by age; half-life configurable per event type |
| **No source credibility scoring** — all sources weighted equally. | A Reddit post and a Reuters article have the same weight | Low — add source credibility: per-source weight; Reuters/Bloomberg > anonymous blogs |

#### Alt Agent — "satellite / cargo (paid feeds)"

| Gap | Impact | Effort |
|-----|--------|--------|
| **Completely stubbed** — hardcoded synthetic scores for 4 commodity ETFs. | No real physical data; the Alt_Agent contributes nothing real to the pipeline | High — requires commercial contracts (Kpler, Ursa, Vortexa); not a code gap but a procurement one |
| **No alternative data sources** — no satellite imagery, no supply chain data, no ESG metrics, no social media sentiment (Reddit, Twitter/X). | Missing the "alternative data" edge that the blueprint specifies | High — integrate free alternative data: Google Trends (demand), satellite imagery (Sentinel/Copernicus), port/ship tracking (AIS) |
| **No macro overlay** — no interest rates, yield curve, inflation, GDP, unemployment data. | The system can't see the macro environment; no regime context from economic data | Medium — add macro data: FRED API (free) for Treasury yields, CPI, unemployment; yield curve inversion as a regime signal |

#### Master Reasoning LLM

| Gap | Impact | Effort |
|-----|--------|--------|
| **No fine-tuning** — the LLM uses a generic system prompt. No domain-specific fine-tuning for financial reasoning. | The LLM may hallucinate financial concepts; no guarantee it understands the evidence correctly; no measured quality on financial decision-making | High — fine-tune on golden fixtures: few-shot examples of correct evidence synthesis; RLHF on rationale quality; financial-specific prompt engineering |
| **No chain-of-thought reasoning** — the prompt asks for JSON output directly. No structured reasoning before the verdict. | The LLM may jump to conclusions without showing its work; harder to audit | Medium — add CoT: ask the LLM to reason step-by-step before producing the verdict; parse the reasoning chain for audit |
| **No confidence calibration training** — confidence is whatever the LLM says. No training to make it match actual accuracy. | The LLM may be overconfident (says 90% but is right 60% of the time) or underconfident; the eval harness measures this but doesn't fix it | Medium — add calibration training: Platt scaling or isotonic regression on the eval harness results; adjust confidence post-hoc |
| **No multi-LLM ensemble** — only one LLM runs at a time (first in chain that works). No voting or aggregation. | No diversity of opinion; no error detection through disagreement; one LLM's bias dominates | Medium — add ensemble: run 2-3 LLMs in parallel, vote on direction, average confidence, flag disagreements in rationale |
| **No streaming** — the LLM call blocks until complete. No streaming for long-running analysis. | Dashboard shows "running…" for 10-30s with no intermediate feedback | Medium — add SSE streaming: stream the LLM's reasoning as it generates; show per-agent status as it completes |
| **No context window management** — the entire GraphState is sent as one prompt. No chunking or RAG for large states. | Large states may exceed context limits; the LLM may lose track of earlier evidence | Low — add context management: summarize each agent's output; truncate or compress; manage token budget per agent |
| **No hallucination guard** — the LLM could invent indicators or numbers not in the evidence. | The "never predicts a number" rule is enforced by prompt, not by code | Medium — add output validation: check that the verdict references only evidence in the GraphState; reject hallucinated numbers |

#### Data Layer

| Gap | Impact | Effort |
|-----|--------|--------|
| **No real-time data** — yfinance provides daily bars with a 1-day delay. LSE provides intraday (1m/5m/1h) but not via WebSocket. No live tick data. | The system is always one day behind on daily signals; can't react to intraday moves; no live signal generation | High — add real-time data: WebSocket feed (Alpaca, Polygon, IEX) or LSE WebSocket (paid plan); streaming ingest pipeline |
| **No incremental ingest (yfinance)** — `ingest()` fetches 730 days every time. No upsert-only-new-bars. | Re-downloading 2 years of data every analyze is wasteful; yfinance rate limits kick in | Low — add incremental to yfinance path: use `latest_ts()` to fetch only bars after the last known timestamp. (LSE provider already has incremental ingest.) |
| **No data quality checks** — no validation for gaps, outliers, splits, adjusted prices. | Bad data silently corrupts signals; stock splits produce false breakouts | Medium — add data quality: gap detection, split adjustment verification, outlier flagging, volume sanity checks |
| **No provider failover chain** — LSE and yfinance are separate commands, not a chain. If LSE doesn't have a symbol (e.g. USO), the user must manually use yfinance. | No automatic failover; user must know which provider has which symbol | Low — add provider seam: try LSE first, fall back to yfinance on 404; single `ingest` command that auto-selects |
| **No caching layer** — every analyze call re-loads from TimescaleDB. No Redis/memcached. | DB hit on every request; slow for high-frequency dashboard refreshes | Low — add caching: TTL cache on `load_ohlcv` (60s for daily bars); invalidation on ingest |
| **No timeseries compression** — TimescaleDB hypertable but no compression policy. | Storage grows unbounded; old data is rarely accessed but takes full space | Low — add compression: TimescaleDB native compression on chunks older than 30 days |

#### Latency

| Component | Current latency | Bottleneck | Improvement |
|-----------|----------------|------------|------------|
| Ingest (yfinance download) | 3-10s per symbol | yfinance API rate limits | Incremental ingest (only new bars) — saves 80% |
| DB_Agent (load + indicators) | 0.5-1s | TimescaleDB query | Add caching layer (60s TTL) |
| Quant Agent (load + Kelly stats) | 0.5-1s | Redundant DB load + ADX recompute | Share DB load via GraphState (don't re-load) |
| News Agent (Qdrant search) | 0.2-0.5s | Qdrant query + embedding | Cache embeddings; pre-compute per-symbol |
| Master LLM (offline) | <100ms | — | Already fast |
| Master LLM (Gemini) | 3-8s | API round-trip | Add streaming; cache by state hash |
| Master LLM (local/Ollama) | 5-30s | Local inference | Use smaller model (qwen2.5:7b) or quantized |
| Total pipeline (offline) | ~2s | Redundant DB loads | Share state between agents |
| Total pipeline (LLM) | 5-15s | LLM API call | Streaming + caching + parallel agents |

#### Orchestration

| Gap | Impact | Effort |
|-----|--------|--------|
| **Agents share no state** — db_agent and quant_agent both load OHLCV independently from TimescaleDB. | Double DB query; ADX computed twice; data could differ if a bar arrives between loads | Medium — pass OHLCV through GraphState; quant_agent reads db_agent's `high`/`low`/`close` instead of re-loading |
| **No conditional routing** — all 4 agents always run, even when data is unavailable. | Alt_Agent always runs but always returns stub/no-data for equities; wasted compute | Low — add conditional edges: skip alt_agent for equities; skip news_agent if Qdrant is down |
| **No parallel agent optimization** — LangGraph runs agents concurrently but the GraphState merge is sequential. | Correct but could be faster with explicit parallel fan-out + barrier | Low — already parallel via LangGraph; verify with timing |
| **No retry/backoff** — if an agent fails, the graph continues with partial state. No retry. | A transient DB failure causes missing evidence for the entire run | Medium — add retry with exponential backoff on DB-dependent agents |
| **No streaming state updates** — the dashboard gets the full result at the end. No per-agent completion event. | User waits 10-30s with no feedback; can't show agent-by-agent progress | Medium — add SSE: stream state updates as each agent completes |

### Tier 2 Summary

| Area | Planned | Implemented | Gaps |
|------|---------|-------------|------|
| LangGraph orchestration | ✅ | ✅ | No state sharing between agents; no conditional routing |
| GraphState convergence | ✅ | ✅ | — |
| DB_Agent (indicators + signal selector) | ✅ | ✅ ← upgraded | Limited indicators; no volume, no multi-timeframe, no patterns |
| Quant Agent (Alpha-Zoo factor engine) | ★ "build next" | ◌ basic stats only | No factor model, no correlation regime, no portfolio Kelly, no covariance |
| News Agent (real embeddings + live feed) | ✅ | ◐ embeddings fixed, no live feed | No live news; no scraping; no real-time sentiment; 8 seed articles only |
| Alt Agent (physical data) | ○ deferred | ○ stub | Requires commercial contracts; no free alternative data |
| Correlation Regime agent | ★ "build next" | ✗ not started | Not implemented — no regime detection, no cross-asset correlation |
| Master Reasoning LLM | ✅ | ✅ | No fine-tuning; no CoT; no calibration training; no ensemble; no streaming |
| TimescaleDB | ✅ | ✅ | No caching; no data quality; no compression |
| Qdrant (hybrid search) | ✅ | ✅ ← fixed | Embeddings work; no live news flow |
| yfinance ingest | ✅ | ✅ | No real-time; no incremental; no provider failover |
| LSE data provider | ✅ | ✅ ← new | Free plan only (candles); no macro/bonds/options (paid); no provider failover to yfinance yet |
| Kafka/Redpanda | ✅ | ✅ | Producer + consumer; no streaming pipeline |
| Circuit breakers | ✅ | ✅ | — |
| OPA policy enforcement | ✅ | ✅ | — |

**Implementation: ~68% of the Tier 2 blueprint.** (↑ from 65% — LSE provider added)

---

## Tier 3 — Oversight & Sizing

### What the blueprint planned

Tier 3 is where position sizing and human oversight live — "how much, and who signs off." Three components:

1. **Asset Manager** — Kelly sizing + a **hard 5% policy cap** that overrides the model. The blueprint specifies both Kelly formulations:
   - Discrete (binary): `f = W - (1-W)/R`
   - Continuous (returns): `f* = (μ - r)/σ²`
   - Fractional scaling (quarter-Kelly) per Busseti et al. (2016)
   - Deterministic policy override that caps single-instrument exposure regardless of the probabilistic model

2. **Human Decision Gate** — advice-only today; a person approves before any action

3. **Shadow Account Audit** — bias diagnostics; needs a manager's real trade history (deferred)

The blueprint's **three laws** are most relevant to Tier 3:
- **Law 1**: Numbers are deterministic; the LLM only explains
- **Law 2**: A reproducible graph, not an agent free-loop
- **Law 3**: Nothing is trusted until it beats buy-and-hold — the backtest gate governs promotion to real money

### What's implemented (today)

#### Asset Manager (`agents/asset_manager.py` — 89 lines)

| Feature | Implementation | Status |
|---------|---------------|--------|
| Discrete Kelly formula | `f = W - (1-W)/R` | ✅ |
| Continuous Kelly formula | `f* = (μ - r)/σ²` | ✅ |
| Quarter-Kelly fractional scaling | `raw * s.kelly_fraction` (0.25x default) | ✅ |
| 5% hard policy cap | `min(fractional, s.max_single_instrument)` (0.05) | ✅ |
| Discrete Kelly as primary driver | `raw = max(0.0, d_kelly)` — continuous Kelly is informational only | ✅ ← fixed this session |
| No-edge → flat | `d_kelly(0.5, 1.0) = 0` → 0% allocation | ✅ ← fixed |
| Negative-edge → flat (no shorting) | `max(0.0, d_kelly)` clamps negatives to 0 | ✅ ← fixed |
| LLM confidence tempering | `w = 0.5 * w + 0.5 * confidence` — the LLM adjusts W but never overrides the cap | ✅ |
| `Allocation` dataclass | Reports: discrete_kelly, continuous_kelly, raw_fraction, fractional, final_fraction, capped_by_policy, rationale | ✅ |
| OPA authorization | `authorize_tool(IDENTITY, "kelly")` | ✅ |
| Config-driven risk policy | `kelly_fraction`, `max_single_instrument`, `risk_free_rate` in `config.py` | ✅ |

#### Kelly sizing behavior (verified this session)

| Edge scenario | W | R | Discrete f | Quarter-Kelly | Final | Capped? |
|---------------|---|---|-----------|---------------|-------|---------|
| No edge | 0.50 | 1.00 | 0.000 | 0% | **0%** | No |
| Modest edge | 0.55 | 1.10 | 0.141 | 3.52% | **3.52%** | No |
| Strong edge | 0.72 | 1.60 | 0.545 | 13.6% | **5%** | Yes |
| Negative edge | 0.40 | 0.80 | -0.350 | 0% | **0%** | No |

#### Backtest engine's Kelly integration (`backtest/engine.py` — 145 lines)

| Feature | Implementation | Status |
|---------|---------------|--------|
| Incremental signal-conditioned Kelly | Accumulates W/R within the walk-forward loop (O(1)/bar) — resolves prior bar's outcome at next bar (look-ahead-safe) | ✅ ← new |
| Minimum-sample guard | Requires ≥10 signal-conditioned samples before using real W/R; else neutral (0.5, 1.0) → flat | ✅ ← new |
| Shared W/R formula | Uses `indicators.wr_from_tallies()` — same formula as live path | ✅ ← new |
| Kelly-sized strategy return | `strat_rets.append(frac * rt)` where frac is signed exposure × Kelly fraction | ✅ |
| Long/short 100% exposure baseline | `dir_rets` — raw directional edge at full exposure | ✅ ← new |
| Long-only 100% baseline | `lo_rets` — long-only filter at full exposure | ✅ ← new |
| Buy & hold benchmark | `bh = close[-1] / close[warmup] - 1` | ✅ |
| Sharpe ratio | `mean/std * √252` | ✅ |
| Max drawdown | `max_dd(equity_curve)` | ✅ |
| Hit rate | `signs_correct / trades` | ✅ |

#### CLI commands

| Command | Implementation | Status |
|---------|---------------|--------|
| `arthaai execute GLD` | Runs pipeline → paper order through Tier 4 guardrails | ✅ |
| `arthaai backtest GLD --signal trend\|breakout --adx 25` | Walk-forward backtest with Kelly sizing | ✅ ← upgraded |
| `arthaai compare --symbols GLD,SLV,USO,XOM,AAPL` | Multi-asset signal comparison table | ✅ ← new |
| `arthaai eval --provider offline` | LLM eval harness (direction, rationale, calibration) | ✅ ← new |

#### Test coverage for Tier 3

| Test file | Tests | What it covers |
|-----------|-------|---------------|
| `test_kelly.py` | 8 | Discrete Kelly formula, continuous Kelly formula, negative edge → 0, policy cap overrides model, fraction never exceeds policy at confidence=1, discrete Kelly drives sizing under cap, no-edge → 0, negative-edge → 0 |
| `test_backtest.py` | 3 | Max drawdown on known series, no drawdown when monotonic, result serialization |
| `test_eval.py` | 10 | Golden fixtures, rationale check, confidence bands, calibration score (perfect, anti, no-signal, too-few), offline passes all, aggregation |

### What was fixed this session

| Component | Before | After |
|-----------|--------|-------|
| Kelly sizing driver | Continuous Kelly always won the branch (`c_kelly if variance > 0 else d_kelly`); 5% cap did 100% of sizing; discrete Kelly was dead code | Discrete Kelly is primary (`raw = max(0.0, d_kelly)`); continuous Kelly is informational only; Kelly drives sizing honestly |
| Kelly inputs (W, R) | Asset's unconditional daily win rate (ignores signal edge) | Signal-conditioned — the signal's actual hit rate and payoff |
| Signed-return bug | `win_sum += rt` — bearish wins accumulated negative returns, corrupting R negative → forced flat on correct bearish signals | `win_sum += abs(rt)` — direction-agnostic; bearish wins no longer corrupt R |
| Kelly formula duplication | W/R formula in both `signal_kelly_stats` (live) and backtest engine (incremental) with divergent guards | Shared `wr_from_tallies()` helper — single source of truth |
| Backtest Kelly accumulation | No incremental Kelly — each bar called `win_loss_ratio(c_win)` (O(n²)) | Incremental accumulation (O(1)/bar, look-ahead-safe, zero extra signal calls) |
| Backtest baselines | Only strategy return + B&H | Added `long_short_return` (100% L/S) and `long_only_return` (100% L/O) for honest edge comparison |

### What can be improved

#### Kelly Sizing Math

| Gap | Impact | Effort |
|-----|--------|--------|
| **No portfolio-level Kelly** — sizing is per-asset, not portfolio-aware. Two perfectly correlated assets each get 5% → 10% correlated exposure. | No diversification benefit in sizing; correlated positions compound risk; no covariance estimation | High — implement Kelly portfolio: Σ (covariance matrix) → optimal weights `F* = Σ⁻¹(μ - r)`; policy cap both per-asset AND portfolio-level |
| **No fractional Kelly by volatility regime** — the 0.25x fraction is static. In high-vol regimes, quarter-Kelly is still aggressive; in low-vol, it's conservative. | Same Kelly fraction in calm and crisis markets; no tail-risk adjustment | Medium — add dynamic Kelly fraction: `fraction = base × (target_vol / realized_vol)`; shrink in high-vol, expand in low-vol |
| **No drawdown-adjusted Kelly** — the fraction doesn't reduce after a drawdown. | Kelly assumes you can tolerate full drawdown (which can be ~50% of capital); no drawdown-aware throttling | Medium — add drawdown throttle: `fraction = base × max(0, 1 - current_drawdown / max_drawdown)`; halts sizing as drawdown deepens |
| **No correlation-aware position cap** — the 5% cap is per-instrument. 20 instruments at 5% each = 100% gross, but if all are correlated, effective risk is much higher. | No gross/net exposure limit; no beta-adjusted cap; portfolio can be fully correlated 100% | Medium — add portfolio-level constraints: max gross exposure (e.g. 50%), max net exposure (e.g. 30%), max beta-adjusted exposure |
| **No Kelly fraction estimation** — the 0.25x is hardcoded. The "optimal" fraction depends on the signal's edge quality and the investor's risk tolerance. | Over-sizing weak signals (should be lower fraction) and under-sizing strong signals (should be higher fraction) | Medium — estimate optimal fraction from backtest: fraction = Kelly × (1 - variance_of_kelly_estimate); shrink when edge estimate is noisy |
| **Continuous Kelly unused** — it's computed and reported but never influences anything. | Wasted compute; could serve as a cross-check or sanity bound | Low — add sanity check: if `discrete_kelly` and `continuous_kelly` disagree on direction, flag in rationale |

#### Risk Controls & Guardrails

| Gap | Impact | Effort |
|-----|--------|--------|
| **No Value-at-Risk (VaR)** — no probabilistic risk estimate. | Can't say "with 95% confidence, the portfolio will not lose more than X% in one day"; no regulatory-compliant risk metric | Medium — add VaR: historical or parametric; 95%/99% confidence; daily and 10-day |
| **No Conditional VaR (Expected Shortfall)** — no tail-risk metric. | VaR doesn't tell you how bad the worst cases are; ES does (average loss beyond VaR) | Low — add ES: average of losses beyond VaR threshold |
| **No stress testing** — no scenario analysis (2008 crash, COVID, rate shock). | No idea how the portfolio performs in extreme scenarios; no regime-aware risk | Medium — add stress scenarios: historical replay (2008, 2020, 2022), synthetic shocks (rate +200bp, equity -20%) |
| **No correlation stress** — no test of what happens when correlations go to 1 (crisis). | Diversification disappears in crises; the portfolio's risk is much higher than calm-period correlations suggest | Medium — add correlation stress: recompute portfolio risk with correlation matrix → 1.0 (all assets move together) |
| **No sector/asset-class concentration limit** — no cap on exposure to a single sector. | Could hold 5% in 10 energy stocks = 50% energy concentration | Low — add sector concentration cap (e.g. max 25% per sector) |
| **No leverage limit** — shorting is disabled but there's no explicit gross leverage cap. | If shorting is ever enabled, no guardrail prevents over-leverage | Low — add gross leverage cap (e.g. max 1.5x gross / 0.5x net) |

#### LLM Confidence → Sizing Integration

| Gap | Impact | Effort |
|-----|--------|--------|
| **Confidence blending is naive** — `w = 0.5 * w + 0.5 * confidence` is a 50/50 blend. The LLM's confidence has equal weight to the signal's historical hit rate. | The LLM can override the signal's edge estimate; a hallucinated high confidence doubles the position size | Medium — shrink the LLM's influence: `w = 0.8 * w + 0.2 * confidence`; or use the LLM confidence as a *gate* (below 0.4 → halve position) not a *blend* |
| **No calibration of LLM confidence** — the LLM says "75% confident" but its actual accuracy at 75% confidence is unknown. | Overconfident LLMs inflate W → inflate position size; the eval harness measures this but doesn't feed back into sizing | Medium — apply Platt scaling / isotonic regression: map LLM confidence to actual accuracy using eval harness data; use the calibrated confidence for sizing |
| **No confidence floor/ceiling on LLM influence** — the LLM can push W to 0 or 1. | An LLM saying 0% confidence → W halved → position zeroed; 100% confidence → W doubled → position potentially huge (capped by policy) | Low — clamp LLM influence: `confidence = max(0.3, min(0.9, confidence))` so it can nudge but not dominate |

#### Human Decision Gate

| Gap | Impact | Effort |
|-----|--------|--------|
| **No approval workflow** — `arthaai execute` places a paper order immediately; no human approval step. | The blueprint specifies a human decision gate; currently the pipeline is fully automated (paper only, but still no checkpoint) | Medium — add approval gate: generate order draft → require explicit `--approve` flag or interactive prompt → then submit |
| **No multi-signature** — no requirement for multiple approvals above a threshold. | Large positions should require more sign-off; currently no threshold | Low — add threshold: positions > 3% require secondary approval |
| **No audit trail of approvals** — no log of who approved what and when. | No accountability; can't reconstruct the decision chain | Low — add structlog: log approval (who, what, when, rationale) |
| **No notification system** — no email/Slack/webhook when a position is proposed. | Decisions happen in a vacuum; no collaborative review | Low — add webhook notification: post order draft to Slack/Teams for review |

#### Shadow Account Audit (deferred)

| Gap | Impact | Effort |
|-----|--------|--------|
| **Not started** — the blueprint specifies "bias diagnostics — needs a manager's real trade history." | No bias detection (anchoring, disposition effect, herding); no behavioral risk | High — requires a real manager's trade history; not a code gap but a data availability one. Could implement a framework: ingest trade log → detect patterns → report biases |

#### Backtest Gate (Law 3: "Nothing is trusted until it beats buy-and-hold")

| Gap | Impact | Effort |
|-----|--------|--------|
| **No automated promotion gate** — the backtest runs but doesn't automatically promote/reject signals. | Law 3 says "nothing is trusted until it beats B&H" but there's no automated check; currently a human reads the table | Medium — add promotion gate: signal must beat B&H out-of-sample with Sharpe > 1.0 and max DD < 25%; auto-flag promoted/rejected |
| **No out-of-sample split** — the backtest runs on the full series, not train/test split. | In-sample backtest overfits; no honest out-of-sample test | Medium — add walk-forward OOS: train on first 70%, test on last 30%; report OOS metrics separately |
| **No transaction costs** — the backtest doesn't model slippage, commissions, or spread. | Strategy returns are optimistic; real-world performance will be worse | Low — add cost model: commission (e.g. $1/trade), slippage (e.g. 5bps), spread (e.g. 1bp) |
| **No multiple-comparison correction** — testing many signals inflates false discovery. | If you test 20 signals, one will look good by chance; no Bonferroni/BHY correction | Medium — add multiple testing correction: Bonferroni or Benjamini-Hochberg on p-values |
| **No regime-conditional backtest** — the backtest runs across all regimes but doesn't split by ADX/volatility. | A signal might work only in trending markets; the aggregate backtest hides this | Low — add regime-conditional backtest: report metrics separately for trending/choppy/high-vol/low-vol |

### Tier 3 Summary

| Area | Planned | Implemented | Gaps |
|------|---------|-------------|------|
| Discrete Kelly formula | ✅ | ✅ ← fixed | — |
| Continuous Kelly formula | ✅ | ✅ (informational) | Not used for sizing — could add as sanity bound |
| Quarter-Kelly fractional scaling | ✅ | ✅ | Static 0.25x — no vol-regime adjustment |
| 5% hard policy cap | ✅ | ✅ ← real | Per-asset only — no portfolio-level cap |
| No-edge → flat | ✅ | ✅ ← fixed | — |
| No shorting (negative → flat) | ✅ | ✅ ← fixed | — |
| Signal-conditioned Kelly (W, R) | ✅ | ✅ ← new | — |
| LLM confidence tempering | ✅ | ✅ | Naive 50/50 blend — should be calibrated |
| Backtest with Kelly sizing | ✅ | ✅ ← upgraded | No OOS split, no transaction costs, no promotion gate |
| Human decision gate | ✅ | ◐ advice-only | No approval workflow; no audit trail |
| Shadow account audit | ✅ (deferred) | ✗ | Requires real trade history |
| Portfolio-level Kelly | ✅ | ✗ | No covariance, no portfolio cap, no diversification benefit |
| Risk metrics (VaR, ES) | ✅ | ✗ | No VaR, no Expected Shortfall, no stress testing |
| Dynamic Kelly by regime | ✅ | ✗ | Static fraction; no vol-regime adjustment |

**Implementation: ~70% of the Tier 3 blueprint.**

---

## Tier 4 — Action

### What the blueprint planned

Tier 4 is where decisions become actions — "simulated today; guard-railed always." Three components:

1. **Paper Execution** — kill switch, stop-loss, 10% daily drawdown breaker, audit log
2. **Live Broker** — IBKR / Alpaca. Only after edge is proven (deferred by Law 3)
3. **Script Exporters** — Pine / MQL5 / TDX. Output feature, not edge (deferred)

The blueprint's design rules for Tier 4:
- **Programmable Guardrails**: deterministic anchors against probabilistic hallucinations — a max daily drawdown that halts ALL trading and a mandatory stop-loss on every position
- These are **hard limits the LLM cannot override**
- PAPER ONLY — never contacts a broker; records intended orders against a simulated account
- Real execution (a broker MCP tool) plugs in behind the same guardrails
- **Law 3 governs Tier 4**: "Nothing is trusted until it beats buy-and-hold" → live broker is gated by the backtest gate, not by code availability

### What's implemented (today)

#### Execution Engine (`execution/engine.py` — 75 lines)

| Feature | Implementation | Status |
|---------|---------------|--------|
| `ExecutionEngine` dataclass | Holds equity, drawdown limit, stop-loss %, order list | ✅ |
| 10% daily drawdown breaker | `max_daily_drawdown = 0.10`; `breaker_state` = "OPEN" when `daily_pnl_pct <= -0.10` | ✅ |
| Mandatory 8% stop-loss | `stop_loss_pct = 0.08`; stop = `entry × (1 ± 0.08)` (below for buys, above for sells) | ✅ |
| `TradingHalted` exception | Raised when breaker is OPEN and `submit()` is called | ✅ |
| `mark_equity()` | Updates equity intraday (drives the drawdown breaker) | ✅ |
| `submit()` | Converts allocation → notional, attaches stop-loss, appends to order list | ✅ |
| Paper-only flag | `Order.paper = True` on every order | ✅ |
| Order dataclass | `symbol`, `side` (buy/sell), `notional`, `stop_loss`, `paper` | ✅ |

#### CLI Integration (`cli.py` — `execute` command)

| Feature | Implementation | Status |
|---------|---------------|--------|
| `arthaai execute GLD` | Runs full pipeline → places paper order through Tier 4 guardrails | ✅ |
| Equity configurable | `--equity 100000` (default) | ✅ |
| Neutral/allocation-zero handling | Prints "No paper order" and exits if direction is neutral or allocation is 0 | ✅ |
| TradingHalted display | Shows red panel with drawdown details | ✅ |
| Order display | Shows side, symbol, notional, fraction, stop-loss, breaker state, PAPER flag | ✅ |
| Disclaimer | "Simulated order only — no broker contacted." | ✅ |

#### Guardrail behavior (verified by tests)

| Scenario | What happens | Test |
|-----------|-------------|------|
| Bullish order, 5% allocation, $100K equity | BUY GLD, notional $5,000, stop @ $92.00 (8% below) | `test_order_sized_from_allocation` |
| Bearish order, 3% allocation | SELL USO, stop @ $108.00 (8% above) | `test_sell_stop_above_entry` |
| -11% daily drawdown | Breaker OPEN → `TradingHalted` raised | `test_drawdown_breaker_halts_trading` |

#### Test coverage

| Test file | Tests | What it covers |
|-----------|-------|---------------|
| `test_execution.py` | 3 | Order sizing from allocation, sell stop above entry, drawdown breaker halts trading |

### What's implemented vs. planned

| Blueprint element | Where | Status |
|---|---|---|
| **Paper Execution** (kill switch, stop-loss, drawdown breaker, audit log) | `execution/engine.py`, `cli.py:execute` | ✅ implemented (but no audit log) |
| **Live Broker** (IBKR / Alpaca) | — | ○ deferred (gated by Law 3) |
| **Script Exporters** (Pine / MQL5 / TDX) | — | ○ deferred (output feature, not edge) |

### What can be improved

#### Execution Engine — Guardrails

| Gap | Impact | Effort |
|-----|--------|--------|
| **No position tracking** — the engine records orders but doesn't track open positions, fills, or P&L. | Can't compute current exposure, unrealized P&L, or portfolio-level drawdown; the breaker only fires on manually-marked equity, not on actual position P&L | High — add `Position` dataclass: track entry price, current price, unrealized P&L, quantity, stop-loss; mark-to-market on each bar; portfolio-level equity |
| **No fill simulation** — orders are recorded but never "filled." No slippage, no partial fills, no rejection. | Paper P&L is meaningless — orders execute at the last close with zero slippage; real-world performance will differ | Medium — add fill simulator: slippage model (5bps for liquid, 20bps for illiquid), partial fill on large orders, rejection on limit orders |
| **No stop-loss execution** — the stop-loss is calculated and stored but never triggered. | A position that drops 20% keeps losing; the 8% stop is never enforced in code | High — add stop-loss monitor: on each price update, check if stop is hit → generate exit order → realize loss |
| **No daily reset** — `_day_start_equity` is set in `__post_init__` but never reset. | The "daily" drawdown breaker is actually a session-level breaker; it never resets at market open | Medium — add `reset_day()` method: reset `_day_start_equity` to current equity at start of each trading day |
| **No kill switch** — the blueprint mentions a kill switch. The drawdown breaker halts new orders but doesn't close existing positions. | A kill switch should immediately flatten ALL positions when triggered, not just stop new entries | Medium — add `kill_switch()`: close all positions at market, set breaker to OPEN, require manual reset |
| **No audit log** — the blueprint specifies an "audit log." Orders are in a list but not persisted or logged. | No trail of what was ordered, when, at what price, with what rationale; can't reconstruct the decision chain | Low — add structlog: log every order (symbol, side, notional, stop, timestamp, allocation rationale) |
| **No max position count** — no limit on how many concurrent positions the engine can hold. | Could accumulate 20+ positions → over-diversified or over-leveraged | Low — add `max_positions` config: reject new orders when at limit |
| **No max gross exposure** — no cap on total notional across all positions. | 5% × 20 positions = 100% gross exposure; no guardrail on portfolio-level risk | Low — add `max_gross_exposure` check: sum of all open notionals must not exceed cap |

#### Paper Account Simulation

| Gap | Impact | Effort |
|-----|--------|--------|
| **No equity curve tracking** — the engine doesn't maintain a time series of equity. | Can't visualize performance over time; can't compute Sharpe, max drawdown, or CAGR on the paper account | Medium — add `equity_curve`: append equity mark on each bar; compute performance metrics on demand |
| **No multi-asset portfolio** — the engine handles one symbol per `execute` call. No persistent portfolio across symbols. | Can't run a multi-asset strategy; can't compute portfolio-level metrics or diversification | High — add `Portfolio` class: holds positions across symbols, computes portfolio P&L, net/gross exposure, sector breakdown |
| **No bar-by-bar simulation** — the engine is one-shot (submit order, done). No intraday simulation loop. | Can't backtest the execution layer; can't test stop-loss triggers, drawdown breaker behavior, or fill models | Medium — add `step(price_updates)`: mark-to-market, check stops, update breaker, generate exits |
| **No commission/spread model** — paper orders have zero costs. | Strategy returns are optimistic; real-world performance will be worse by the cost drag | Low — add cost model: commission ($1/trade or 0.5bps), spread (1bp for liquid), slippage (5-20bps) |

#### Live Broker Integration (deferred by Law 3)

| Gap | Impact | Effort |
|-----|--------|--------|
| **No broker API** — the engine is paper-only. The docstring mentions `._place()` as a plug-in point but it doesn't exist. | Can't execute real orders; paper-only indefinitely (correctly gated by Law 3) | High — add broker adapter: IBKR (ib_insync), Alpaca (REST), or generic FIX protocol; behind the same guardrails |
| **No order management system (OMS)** — no state machine for order lifecycle (pending → submitted → partial → filled → cancelled). | Can't track real orders; can't handle rejections, modifications, or cancellations | Medium — add `OrderState` enum: PENDING, SUBMITTED, PARTIAL, FILLED, CANCELLED, REJECTED; track lifecycle transitions |
| **No order types** — only market orders (buy/sell). No limit, stop, stop-limit, trailing stop, OCO (one-cancels-other). | No sophisticated execution strategies; can't implement TWAP/VWAP/iceberg orders | Medium — add order type support: limit (price), stop (trigger), stop-limit, trailing stop (% or ATR-based) |
| **No connection management** — no broker session, reconnection, or heartbeat. | If a live broker connection drops, orders are lost; no reconnect logic | Medium — add connection manager: heartbeat, auto-reconnect, session state |
| **No pre/post-market handling** — no session awareness. | Orders could be placed outside market hours; no awareness of halts, holidays, or half-days | Low — add session awareness: market hours check, holiday calendar, halt detection |

#### Script Exporters (deferred)

| Gap | Impact | Effort |
|-----|--------|--------|
| **No Pine Script export** — the blueprint mentions Pine / MQL5 / TDX exporters. | Users can't deploy signals to TradingView, MetaTrader, or TongDaXin | Low — add `arthaai export --format pine|mt5|tdx`: generate indicator script from the current signal config |
| **No signal serialization** — the signal parameters (SMA windows, ADX threshold, breakout windows) aren't serializable. | Can't export a self-contained script; the signal logic is in Python, not a portable format | Low — add signal config export: JSON/dict of all parameters; template renderer per target platform |

#### Observability & Monitoring

| Gap | Impact | Effort |
|-----|--------|--------|
| **No OpenTelemetry** — the blueprint lists it as "deferred" under cross-cutting. | No distributed tracing; can't see which agent took how long; no span per LLM call or DB query | High — add OpenTelemetry: trace per agent, span per LLM call / DB query / Qdrant search; export to Jaeger/Tempo |
| **No metrics dashboard** — no Grafana/Prometheus integration. | Can't monitor latency, error rates, LLM costs, signal hit rates in real-time | Medium — add Prometheus exporter: request latency, agent durations, LLM token usage, breaker trips, order count |
| **No alerting** — no notification when the drawdown breaker trips or an agent fails. | Failures are silent; the user only sees them when checking the CLI | Low — add alerting: webhook/Slack on breaker trip, agent failure, LLM circuit breaker open |
| **No cost tracking** — LLM API costs aren't tracked. | Can't budget LLM spend; no per-run cost attribution | Low — add cost tracking: token count × price per model; cumulative spend per provider |

### Tier 4 Summary

| Area | Planned | Implemented | Gaps |
|------|---------|-------------|------|
| Paper execution engine | ✅ | ✅ | No position tracking, no fill simulation, no stop-loss triggering |
| 10% daily drawdown breaker | ✅ | ✅ | No daily reset; no kill switch (flatten all positions) |
| Mandatory 8% stop-loss | ✅ | ✅ (calculated) | Never triggered/executed — only stored on the order |
| `arthaai execute` CLI | ✅ | ✅ | — |
| Audit log | ✅ | ✗ | No persistence; orders in-memory list only |
| Live broker (IBKR / Alpaca) | ○ deferred | ✗ | Correctly gated by Law 3 — no real money to unproven signal |
| Script exporters (Pine / MQL5 / TDX) | ○ deferred | ✗ | Low effort, but low value until signal has proven edge |
| Position tracking & P&L | ✅ | ✗ | No open positions, no mark-to-market, no equity curve |
| Fill simulation (slippage, spread) | ✅ | ✗ | Zero-cost paper execution |
| Multi-asset portfolio | ✅ | ✗ | Single-symbol per execute call; no portfolio |
| OpenTelemetry / observability | ○ deferred | ✗ | No tracing, no metrics, no alerting |

**Implementation: ~40% of the Tier 4 blueprint.**

---

## Overall System Summary

| Tier | Planned | Implemented | Key gap |
|------|---------|-------------|---------|
| **Tier 1 — Interface & Ingress** | ~100% | ~87% | Real OAuth 2.1 / JWT; mTLS (infra); dashboard UX |
| **Tier 2 — Intelligence Core** | ~100% | ~68% | Quant Agent factor engine (the ★ star); live news; correlation regime |
| **Tier 3 — Oversight & Sizing** | ~100% | ~70% | Portfolio Kelly; risk metrics (VaR/ES); automated backtest gate |
| **Tier 4 — Action** | ~100% | ~40% | Position lifecycle; fill simulation; stop-loss triggering |

The system's **plumbing is complete** — data flows from Tier 1 through Tier 4 with auth, circuit breakers, OPA enforcement, and Kelly sizing. The **edge is thin** — the honest finding is that no signal beats B&H on raw return, and the Quant Agent (where "the edge lives") is basic stats, not the factor engine the blueprint calls for. The **priority sequence** the blueprint specifies is correct: prove the signal edge (Tier 2 Quant Agent) → automate the backtest gate (Tier 3 Law 3) → then build the execution layer (Tier 4) → then connect real money (gated by Law 3).

### What was added on 2026-08-25

- **LSE data provider** (`arthaai/data/lse.py`) — London Strategic Edge API integration with incremental ingest, 404 fallback, `ingest-lse` CLI command. 5 assets (GLD, SLV, XOM, AAPL, TSLA) ingested from LSE (501 bars each).
- **numpy serialization fix** — `/analyze` endpoint no longer crashes with 500 (`numpy.bool_` → native `bool` in `asset_manager.size()`).
- **Off-by-one fix** — LSE incremental ingest guard corrected to prevent permanent one-day lag in scheduled ingest.

### Commits (5 total, unpushed)

| Commit | Description |
|--------|-------------|
| `ebadb2a` | Signal-conditioned Kelly sizing + trend/breakout signal layer |
| `5577817` | Secure gateway — authenticate /ohlcv, httpOnly cookie |
| `b6b9661` | Golden-fixture eval harness for Master Reasoning LLM |
| `57abb1d` | Breakout live wiring + eval calibration + OPA fix + AGENTS.md |
| `b0252a6` | 4-tier architecture status report (STATUS_REPORT.md) |

Uncommitted (ready to commit): LSE data provider, numpy fix, off-by-one fix, test_lse.py.

### Test count: 57 DB-independent tests pass in 6s

| Test file | Tests | What it covers |
|-----------|-------|---------------|
| `test_indicators.py` | 15 | SMA, RSI, annualised stats, trend signal, signal Kelly stats, vectorization, breakout |
| `test_kelly.py` | 8 | Discrete/continuous Kelly, policy cap, no-edge → flat, negative-edge → flat |
| `test_backtest.py` | 3 | Drawdown, monotonic, serialization |
| `test_eval.py` | 10 | Golden fixtures, rationale, confidence bands, calibration score |
| `test_llm.py` | 5 | Verdict parsing, provider chain fallback, chain always ends offline |
| `test_gateway.py` | 7 | Auth required, cookie auth, httpOnly cookie, dev-token refusal |
| `test_policy.py` | 3 | OPA allow/deny |
| `test_execution.py` | 3 | Order sizing, sell stop, drawdown breaker |
| `test_lse.py` | 4 | 404 fallback, candle parsing, API key required, friendly meta ← new |
| **Total** | **57** | +1 health test excluded (needs Docker) |

---

*Decision-support only · paper context · not investment advice.*
