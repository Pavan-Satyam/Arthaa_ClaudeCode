# ArthaAI — Architecture Status Report

*Last revised: 2026-10-11 · version 0.1.0 · branch `feat/arthaai-core`*

ArthaAI is a zero-trust multi-agent LLM framework for equities & commodities analysis.
The deterministic quant layer computes every number; the LLM only synthesises and
explains. This report is written **from the code**, not from intent: every "implemented"
claim below was read out of the repository, and the verification results in
[§8](#8-verification-log-live) were produced against the running Docker stack.

**How to read this:** each tier separates *what's implemented* from *what's missing*,
and marks verified vs. unverified. The single most important number in the whole
system is **E3** — whether a signal beats buy-and-hold out-of-sample. It still
**fails** after four signal families were tested to exhaustion ([§8.3](#83-e3--the-edge-gate--fails)),
and the failure now exposes a **criterion mismatch** for cross-sectional signals
([§8.7](#87-e3-exhaustion--the-criterion-mismatch-issue)).

**2026-10-11 implementation and verification update:** Added `refresh_history()` and
`refresh_history_batch()` in `arthaai/data/provider.py`, `refresh-history` and `refresh-universe` CLI
commands, and the read-only `audit-history` workflow for calendar-aware coverage. Refreshed 73
data-bearing registered US-listed symbols from yfinance (5 over 800 days, 68 over 60 days); audit
reported 100% recent XNYS session coverage for these 73, while `SILVER` and `XAG` remain without bars.
The 73-asset cross-sectional diagnostic trailed equal-weight in both tested OOS windows; dry-run
trend/breakout sweeps found no formal E3 qualifiers. No promotion rows were written and the E3 gate
was not changed. Detailed source status, replacement seams, and qualification requirements are in
[DATA_PRODUCTION_READINESS.md](DATA_PRODUCTION_READINESS.md); the board addendum records exact window metrics.

**2026-10-11 provider abstraction update:** Added `OHLCVProvider`, `ProviderRegistry`, and built-in
LSE/yfinance adapters in `arthaai/data/provider.py`. Existing auto fallback remains LSE-if-configured
then yfinance; `fetch_ohlcv()`, `ingest_resilient()`, and history refresh APIs now accept an injected
registry. Custom providers can be registered by trusted host startup using `register_provider()`.

**2026-10-11 configured provider selection update:** Added `ARTHAAI_MARKET_DATA_PROVIDER` to settings
and `.env.example`; its default `auto` preserves the existing fallback. A configured name must exist
in the active registry and be available or routing fails clearly. `--provider` remains an invocation-
level override, and normal ingestion preserves per-symbol pins ahead of the global default. Provider
status accepts registered names and displays the configured default. Built-in adapters are the only
ones registered in the shipped host at present; production vendor packaging/registration, per-bar
lineage, and data qualification remain open. The focused provider/config suite passes (34 tests).
Final verification: the DB-independent project suite passes **413 tests** with 1 health test deselected;
provider/config Ruff checks, CLI undefined-name checks, and editor diagnostics pass.

**2026-10-11 OHLCV provenance update:** Added nullable `source_provider`, `retrieved_at`,
`adjustment_basis`, `provider_symbol`, `provider_timestamp`, and `normalization_version` fields to the
OHLCV schema and idempotent migration. `timescale.upsert_ohlcv()` persists available provenance and
updates it on conflict; registry-based and direct LSE/yfinance paths provide source labels, provider
ticker, source timestamp, adjustment-basis descriptor, and canonical version. The opt-in
`load_ohlcv(..., include_provenance=True)` exposes all lineage without changing the default consumer
schema. Applied migration and refreshed GLD over five days; four rows were verified in the database.
Of 39,212 rows, 39,208 remain NULL/unknown rather than guessed. `provider_symbol` is not a stable vendor
security ID. Focused provenance/migration/provider tests passed; full suite: 418 passed, 1 health test
deselected. Provenance lint/editor diagnostics pass. E3 and execution policy are unchanged.

**2026-10-12 composite-signal CLI exposure update (ARTHA-219):** The backtest engine already
supported a `composite` per-bar factor signal but no user-facing command could select it. `arthaai
backtest`, `arthaai promote`, and `arthaai promote-sweep` now accept `--signal composite` (the fixed
five-factor per-bar mean via `quant_agent.factor_signal_series`). A shared `_validate_signal()` helper
normalizes the value and rejects unknown signals with exit code 2 instead of silently defaulting to
trend. A `composite` run that cannot resolve a factor series now raises a clear `ValueError` in the
engine instead of silently degrading to the trend signal; `backtest`/`promote` print the error and exit
1, and `promote-sweep` records the failure for that symbol and continues. This is diagnostic/analysis
tooling only: the default remains `trend`, live sizing is untouched, and `composite` is not wired into
the asset manager. New `tests/test_cli_signals.py` (7 tests) covers acceptance, normalization, rejection,
signal pass-through, and the unavailable-signal error path; `tests/test_backtest.py` adds 2 tests for the
loud failure. Full suite: 427 passed, 1 health test deselected; `compileall` clean; CI correctness lint clean.

**2026-10-12 evaluation-sample freeze update:** Added `arthaai/data/metadata.py` (normalizes yfinance
exchange codes/names; fetches name/asset-class/exchange/currency with an injectable factory for tests)
and extended `timescale` with `ensure_asset(exchange=, currency=)`, `update_asset_metadata`,
`list_asset_symbols`, `assets_missing_exchange`, and `asset_coverage`. New CLI commands:
`backfill-metadata` (populated exchange for the universe — 74/75 assets now carry one — and corrected 36
ETFs previously mislabeled `equity`) and `freeze-universe` (emits a reproducible universe manifest with a
content hash). Declared [E3_EVALUATION_PROTOCOL.md](E3_EVALUATION_PROTOCOL.md) and froze the 73-symbol
sample (`evaluation/frozen_universe.json`, hash `f1f17e20c26d6eea`). Verified the `composite` signal runs
end-to-end on real data (GLD: edge −17.88%, Sharpe 0.89 — still no edge). No promotion criterion changed;
E3 remains open. Full suite: 432 passed, 1 health test deselected; `compileall` clean; CI lint clean.

**2026-10-12 IC-weighted composite evaluation update (E3 step 2/3):** Wired the walk-forward IC-weighted
cross-sectional composite as a selectable signal (`--signal ic_composite`) on `backtest`, `promote`, and
`promote-sweep`. Added `factors.composite.per_symbol_signals` / `cross_sectional_signal_map`,
`factors.panel.normalize_ohlcv_frame` / `align_signal_to_ohlcv`, and `eval/universe.load_frozen_universe`;
the gate feeds each symbol's causal series through the engine's `signal_series`. Evaluated on the frozen
73-symbol universe with `promote-sweep --cost-bps 10`: **0/73 qualified** (6 symbols passed one window,
none passed both; no promotion rows written). GLD cross-check: edge −23.91%, Sharpe 0.72. Result recorded
in `evaluation/e3_results.md`. E3 remains open; the gate and promotion criteria are unchanged. Full suite:
440 passed, 1 health test deselected; `compileall` clean; CI lint clean.

**2026-10-12 classic momentum family update (E3, pre-registered):** Added `arthaai/factors/momentum.py`
(`tsmom` time-series momentum, `xsmom` cross-sectional momentum) and exposed `--signal tsmom|xsmom` with
`--lookback`/`--top-quantile` on `backtest`/`promote`/`promote-sweep` via a shared `_signal_map_for`
dispatcher. Three variants were pre-declared in the protocol and all reported on the frozen hash
`f1f17e20c26d6eea`: `tsmom` L=126 → **0/73**, `xsmom` L=63 q=0.30 → **0/73**, `xsmom` L=126 q=0.30 →
**0/73** (6/3/4 symbols passed one window, none passed both). Five pre-declared signal families now
evaluated on this sample with no promoter. Results in `evaluation/e3_results.md`. Full suite: 446 passed,
1 health test deselected; `compileall` clean; CI lint clean.

**2026-10-12 extended-history sample update (E3):** Extended the frozen universe to ~10 years via
`refresh-universe --lookback-days 3650` (now 2016-10-14 → 2026-10-09; 1249–3009 bars/symbol).
`freeze-universe` now fingerprints each symbol's bar count, so re-freezing produced a new sample hash
`e6468871a625ea35` (superseding `f1f17e20c26d6eea`; prior verdicts void). Re-ran all seven pre-declared
variants on the extended sample: **all 0/73**, none passing both OOS windows on any symbol. The negative
result is now robust to sample length. E3 remains open; gate and promotion criteria unchanged. Full
suite: 446 passed, 1 health test deselected; `compileall` clean; CI lint clean.

**2026-10-12 intermarket risk-regime update (E3, different axis):** Added `arthaai/factors/regime.py`
(`risk_regime`, `regime_signal_map`) and exposed `--signal regime|regime_tsmom` — a market-state axis
(SPY trend + HYG/LQD credit ratio) rather than own price, using data already in the universe (free,
keyless, PIT-safe). Pre-registered in the protocol and evaluated on `e6468871a625ea35`: both **0/73**
(8 symbols each passed one window). Eight pre-declared variants have now failed across two axes; no
promotable edge in price/market data for this universe under the current criteria. Results in
`evaluation/e3_results.md`. Full suite: 450 passed, 1 health test deselected; `compileall` clean; CI
lint clean.

**2026-10-12 E3 verdict — no promotable edge on available data:** E3 is closed on the current data. Eight
pre-declared signal variants across two information axes (own-price: trend, breakout, composite,
ic_composite, tsmom, xsmom; market-state: regime, regime_tsmom) were evaluated on a 10-year, 73-asset
frozen sample (`e6468871a625ea35`) under the unchanged gate — every one **0/73**, no symbol passing both
OOS windows. The result is robust to sample length and signal family, and the protocol (pre-registration,
no OOS tuning, change control) rules out the usual artifacts. The gate requires genuine market-timing
alpha on liquid assets, which the available price/market data does not contain. **E3 is a data problem,
not a signal-search problem.** Recommendation: keep Law 3 (no live money) in force; treat point-in-time
data procurement (EDGAR/macro/news) as the gating prerequisite for any further E3 attempt; redirect
adjacent effort until an exogenous axis exists. Full details in `evaluation/e3_results.md`.

**2026-10-12 fundamental value/quality axis (SEC EDGAR, PIT):** Added `arthaai/data/fundamentals_pit.py`
— free, keyless SEC EDGAR XBRL access with **filing-date point-in-time** availability (no look-ahead),
cached, and injectable for tests. Exposed `--signal value`: cross-sectional z-score of book-to-price,
earnings yield, and ROE; long the top quantile. Pre-registered and evaluated on the **equity subset**
(33 symbols; ETFs have no fundamentals) under the unchanged gate: **0/34** (3 symbols passed one window).
Nine pre-declared variants now fail across three information axes (own-price, market-state, fundamental).
E3 remains closed; Law 3 stays in force. Raw sweep in `evaluation/sweep10_value.txt`; details in
`evaluation/e3_results.md`. Full suite: 455 passed, 1 health test deselected; `compileall` clean; CI
lint clean.

**2026-10-12 macro term-spread axis (FRED, keyless):** Added `arthaai/data/macro_series.py` (keyless FRED
CSV fetch, cached) and `arthaai/factors/macro_regime.py` (`macro`, `macro_tsmom` from the 10y-2y spread
`T10Y2Y`; market data, non-revised → PIT-safe). Exposed `--signal macro|macro_tsmom`. Pre-registered and
evaluated on the frozen 73-symbol sample: both **0/73** (8 symbols each passed one window). Eleven
pre-declared variants now fail across four information axes (own-price, market-state, fundamental,
macro) — every tractable, free, PIT-safe axis available without new data procurement. E3 remains closed;
Law 3 stays in force. Raw sweeps in `evaluation/sweep10_macro*.txt`. Full suite: 461 passed, 1 health
test deselected; `compileall` clean; CI lint clean.

---

## 0. Next session — start here

**State (2026-10-04, end of session):**
- Branch `feat/arthaai-core` — **all work committed and pushed** to `origin/feat/arthaai-core` (HEAD `af8bc89`); working tree clean, 0 ahead / 0 behind.
- Last full run: **353 tests pass** (+1 deselected `health`), `compileall` clean, CI correctness lint clean. GitHub CI wired to install `.[dev,obs,auth]`.
- Docker stack was up (TimescaleDB/Qdrant/OPA/Vault/Redpanda); `LSE_API_KEY` present in `.env`. OHLCV loaded for ~45 symbols.
- **Decision recorded (2026-10-10): hold release.** No market-neutral criterion is approved; E3 remains failed and Law 3 remains in force. The factor-gate default is now off, with explicit `ARTHAAI_FACTOR_GATE=true` opt-in.

**Completed this session:** all 11 independent backlog tickets + ARTHA-309/311 (fill simulation, VaR/ES, human approval gate, correlation-regime agent, cross-sectional + IC-weighted composite, live news ingestion, OpenTelemetry, Prometheus, mTLS fail-closed, real-IdP JWT test, portfolio + dynamic Kelly), a full `/review uncommitted` pass whose **10 findings are all fixed**, and the §14 follow-ups **#1 (commit+push), #4 (live stop enforcement via ledger + `mark`), #5 (`promote-sweep` + `/promotions` endpoint), #6 (portfolio exposure guard + VaR/ES in `execute`), #8 (config-driven news feeds), #9 (alerts + LLM call tracking)**.

**Immediate next steps (in order):**
2. ✅ **E3 decision: hold release.** No signal is currently promotable; no separate market-neutral criterion is approved. Keep the directional B&H gate unchanged and Law 3 in force.
3. ✅ **Factor-gate default** — `factor_gate=False`; explicit `ARTHAAI_FACTOR_GATE=true` remains available. Focused factor-gate, backtest, and Kelly tests pass.
7. **Composite → live sizing** — only if #2 shows a promotable edge (Law 3). *(depends on #2)*
10. **Broker adapter + Pine/MQL5/TDX exporters** — only after E3 passes. *(depends on #2 + #4)*

**Commands to resume:**
```powershell
docker compose up -d
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m arthaai.cli migrate
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m pytest tests/ -q -k "not health"
# reproduce the E3 gate (Expect REJECTED):
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m arthaai.cli promote GLD --signal breakout --cost-bps 10
# universe sweep of the promotion gate:
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m arthaai.cli promote-sweep --signal breakout
# composite / IC-weighted ranking over the universe:
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m arthaai.cli factors composite --symbols GLD,SLV,USO,XOM,AAPL --ic-weighted
```

**Known open items / caveats:** the human-gate fix binds symbol/side/fraction and is one-shot, but the executed stop is engine-derived (no price-drift tolerance). `execute` enforces the portfolio exposure cap but the ledger is a flat file (no atomic multi-writer). `PROJECT_BOARD.md` is stale relative to this report.

---

## Table of Contents

0. [Next session — start here](#0-next-session--start-here)
1. [Executive summary](#1-executive-summary)
2. [System at a glance](#2-system-at-a-glance)
3. [Tier 1 — Interface & Ingress](#3-tier-1--interface--ingress)
4. [Tier 2 — Intelligence Core](#4-tier-2--intelligence-core)
5. [Alpha Zoo — factor engine](#5-alpha-zoo--factor-engine)
6. [Tier 3 — Oversight & Sizing](#6-tier-3--oversight--sizing)
7. [Tier 4 — Action](#7-tier-4--action)
8. [Verification log (live)](#8-verification-log-live)
9. [Cross-cutting concerns](#9-cross-cutting-concerns)
10. [Known issues & defects](#10-known-issues--defects)
11. [Test inventory](#11-test-inventory)
12. [CLI reference](#12-cli-reference)
13. [Implementation by tier](#13-implementation-by-tier)
14. [Remaining work](#14-remaining-work)
15. [Commit history](#15-commit-history)

---

## 1. Executive summary

**The plumbing is complete; the edge is not.**

- Data flows end-to-end: ingest (provider chain with failover) → TimescaleDB →
  LangGraph fan-out (DB/Quant/News/Alt agents) → Master LLM synthesis → Kelly sizing
  → paper execution, all under OPA policy, circuit breakers, and configurable auth.
- **E3 fails, live-verified — now across four signal families and a 45-asset
  cross-section.** `trend`, `breakout`, an equal-weight cross-sectional composite, and an
  **IC-weighted composite** (expanding rank-IC weights with an embargo) were all run
  through the promotion gate on a widened LSE universe (~45 symbols). **Nothing passes all
  OOS windows.** Several assets are "one-window-shy" (SLV, PPLT, PALL, XLE, XLU, XLC, EWJ,
  JPM), and the failures concentrate in the most recent bull window — see
  [§8.3](#83-e3--the-edge-gate--fails) and [§8.7](#87-e3-exhaustion--the-criterion-mismatch-issue).
  No factor in the 442-strong zoo survives Benjamini-Hochberg FDR on a 28-asset cross-section.
- **The gate may be grading the wrong quantity for cross-sectional signals** (new issue,
  [§8.7](#87-e3-exhaustion--the-criterion-mismatch-issue)). The promotion gate compares a
  signal's *exposure-matched long-only* return to buy-and-hold — a fair test for a
  directional signal, but a cross-sectional factor's natural expression is a long/short,
  market-neutral book that has no B&H benchmark. This does **not** make E3 pass; it flags
  that the release criterion and the cross-sectional research direction are misaligned.
- **E2 is wired** (the factor signal now drives sizing via a dampen-only gate), but the
  evidence says it should stay **off**: it lowered OOS Sharpe on GLD, and the factor
  signal it consumes has no FDR-significant edge. The default is off pending promotion; explicit opt-in remains available. See [§10](#10-known-issues--defects).
- **Thirteen open backlog items were completed this session** (ARTHA-221, 409, 310, 308,
  219, 215, 216, 507, 508, 107, 110, plus 309/311): fill simulation (slippage/partial/
  rejection), VaR/Expected-Shortfall, dynamic + portfolio Kelly, correlation-regime agent,
  cross-sectional + IC-weighted composite, live news ingestion, OpenTelemetry, Prometheus,
  human approval gate, mTLS fail-closed, and a real-IdP JWT test. See
  [§14](#14-remaining-work) for what remains.
- A genuine **data-corruption bug was found and fixed** this session: GLD/SLV carried
  two bars per day (LSE `00:00` + yfinance `13:30`), which silently doubled their series
  and distorted every backtest. 1095 duplicate bars were removed.

| Area | Verdict |
|---|---|
| Tier 1 — Interface & Ingress | ✅ implemented (JWT/OAuth 2.1 IdP-verified, rate limits, CORS, mTLS fail-closed) |
| Tier 2 — Intelligence Core | 🟡 agents work (incl. correlation regime); Quant "edge" still unproven |
| Alpha Zoo factor engine | 🟡 445 factors, 403 compute; composite + IC-weighted composite built; no FDR-significant edge |
| Tier 3 — Oversight & Sizing | ✅ Kelly + policy caps + promotion gate + portfolio/dynamic Kelly + VaR/ES + human gate |
| Tier 4 — Action | ✅ paper engine, stops, kill switch, audit, fill/slippage sim; broker deferred by Law 3 |
| Cross-cutting | ✅ OTel tracing + Prometheus metrics (optional `obs` extra) |
| **★ Edge (E1–E3)** | **🟡 E1/E2 wired · ❌ E3 fails across 4 signal families (gate/criterion mismatch flagged)** |

**Overall: ~80% of the blueprint is code-complete; 0% of the release gate is met** —
because the release gate is gated on E3, and E3 is a research result, not a checkbox.

---

## 2. System at a glance

| Metric | Value |
|---|---|
| Python source files | ~58 (excl. generated zoo) |
| Test files | 34 |
| Tests passing (DB-independent) | **353** (+1 deselected `health`) |
| CLI commands | 25 |
| Registered factor alphas | **445** (alpha101 101, gtja191 190, qlib158 154) |
| DB symbols with OHLCV | ~50 (widened LSE cross-section for E3) |
| Quality gates | `compileall` clean · correctness lint clean · CI workflow defined |

### Data flow

```
ingest (provider chain: LSE → yfinance, incremental, SWR fallback)
    │  fan-out (LangGraph)
    ├── DB_Agent          → technical indicators + ADX regime signal selector
    ├── Quant Agent       → μ / σ² / signal-conditioned Kelly inputs + factor signal
    ├── News_Agent        → hybrid-search sentiment (Qdrant, circuit-breaker-guarded)
    ├── Alt_Agent         → physical signal (STUB)
    └── Correlation Agent → risk-off fusion regime (avg pairwise correlation)
    │  converge → GraphState
    ▼
Master Reasoning LLM  → direction + confidence + rationale (provider chain → offline)
    ▼
Asset Manager Agent   → discrete Kelly (primary) + cont. Kelly (info) + factor gate
                        + vol targeting + dynamic/portfolio Kelly + VaR/ES
                        + 5% policy cap → allocation
    ▼
Tier 4 paper execution → Position/Portfolio state machine, mandatory stop-loss,
                          equity-curve breaker, kill switch, JSONL audit log,
                          fill model (slippage/partial/rejection), human approval gate
```

---

## 3. Tier 1 — Interface & Ingress

### Implemented

**Gateway (`arthaai/gateway/app.py`, 142 lines)**
- FastAPI app, version `0.1.0`; served via `arthaai serve`.
- Endpoints:

  | Method | Path | Protection |
  |---|---|---|
  | `GET` | `/` | none (serves dashboard, sets httpOnly cookie) |
  | `GET` | `/health` | none (pings TimescaleDB extension) |
  | `GET` | `/ohlcv/{symbol}` | bearer/cookie auth · rate limit 60/min |
  | `POST` | `/analyze/{symbol}` | bearer/cookie auth · rate limit 10/min |
  | `GET` | `/metrics` | bearer/cookie auth · mTLS (optional `obs` extra; 503 if absent) |
  | `GET` | `/promotions` | bearer/cookie auth · mTLS (qualified symbols from the promotion gate) |

- **Rate limiting** (`slowapi`) keyed by `client_key` — a SHA-256 **hash of the bearer
  token** (header or cookie), falling back to client IP. Keying on the credential means
  a shared NAT doesn't pool limits; the raw token is never stored.
- **CORS** (`ARTHA-509`): `CORSMiddleware` with origins from `ARTHAAI_CORS_ORIGINS`
  (empty = same-origin only), credentials enabled.
- `/ohlcv` lazily ingests via **`ingest_resilient`** when the DB has no bars.

**Auth (`arthaai/gateway/auth.py`, 133 lines)** — three modes, selected by config:
1. **OAuth 2.1 / JWT** (`ARTHAAI_OAUTH_JWKS_URL` set): validates the bearer token as a
   JWT — signature via the IdP JWKS, **`exp` required**, plus `iss`/`aud`. Requires the
   optional `auth` extra (`pyjwt[crypto]`); clear 503 if absent.
2. **Static token** (`ARTHAAI_GATEWAY_TOKEN`, from Vault or env): constant-time
   `secrets.compare_digest`.
3. **Unconfigured**: dev mode accepts any non-empty bearer; **production
   (`dev_mode=False`) refuses with 503** rather than silently accepting anything.

**Dashboard (`gateway/static/dashboard.html`, 155 lines)** — price/candles/verdict/
allocation; token held in an httpOnly cookie (never in page source).

**Config (`arthaai/config.py`, 123 lines)** — env-driven `Settings`:
`dev_mode`, `provider_chain`, `cb_fail_max`, `cb_reset_timeout`, `stale_max_age_days`,
`kelly_fraction`, `max_single_instrument`, `risk_free_rate`, `factor_gate`,
`factor_dampening`, `factor_epsilon`, `vol_target`, `vol_max_leverage`,
`oauth_jwks_url`, `oauth_issuer`, `oauth_audience`, `oauth_algorithms`, `cors_origins`.

### Missing / gaps
- **mTLS is infrastructure, not code** (`ARTHA-110`) — terminated upstream. When
  `ARTHAAI_MTLS_REQUIRED=true`, `gateway/mtls.py` enforces it **fail-closed**: the
  client-cert header is honored only when the request source is in
  `ARTHAAI_MTLS_TRUSTED_PROXIES`, and enforcement refuses if no trusted proxy is
  configured — so a bare/spoofed header cannot satisfy the gate.
- JWT is now verified **end-to-end against a real IdP** (generated RSA keypair + JWKS HTTP
  server + `jwt.encode`) in `tests/test_oauth_jwt.py`; pointing at a production IdP is
  config, not code.
- No refresh-token rotation; expiry is enforced but rotation is operational.

---

## 4. Tier 2 — Intelligence Core

### Implemented

**Orchestrator (`arthaai/orchestration/graph.py`)** — LangGraph fan-out/merge
with nodes `_ingest → {_db, _quant, _news, _alt, _correlation} → _master → _asset_manager`,
plus `analyze()` used by the gateway and CLI. The ingest node calls
**`ingest_resilient`** (incremental, multi-provider) instead of the old yfinance-only path.

**GraphState (`orchestration/state.py`)** — `symbol`, `skip_ingest`, `db`, `quant`,
`news`, `alt`, `correlation`, `verdict`, `allocation`.

**DB_Agent (`agents/db_agent.py`, 68 lines)** — deterministic indicators (SMA20/50,
RSI14, ADX14); **ADX regime selector**: `ADX ≥ 25` → Donchian breakout signal, else
multi-timeframe trend filter. Runs under a SPIFFE identity via `authorize_tool`.

**Quant Agent (`agents/quant_agent.py`, 185 lines)**:
- `run()` returns annualised `mu`/`variance`/`sigma` and `factor_signal`.
- `factor_signal_series()` — a **causal, per-bar** aggregate (row-wise mean) of a fixed
  a-priori factor set (`DEFAULT_FACTOR_IDS`), used by both live sizing and the backtest so
  the two never diverge.
- `_evaluate_factors()` — top-K factor display by |score|.

**News_Agent (`agents/news_agent.py`, 35 lines)** — Qdrant hybrid search (ticker filter
+ similarity), wrapped in a circuit breaker with neutral fallback; returns
`avg_sentiment` and labelled `bullish`/`bearish`/`mixed`.

**Alt_Agent (`agents/alt_agent.py`, 38 lines)** — explicitly-labelled **STUB** synthetic
physical signals for commodity ETFs; abstains for equities.

**Correlation Regime agent (`agents/correlation_regime.py`)** — new (ARTHA-215). Measures
the average pairwise correlation of a cross-asset universe over a rolling window and labels
the regime (`risk_off` / `mixed` / `diversified`); surfaced to the Master LLM as **risk
context, not a directional signal** (no weight in `_weighted_score`). Registered under its
own OPA scope.

**Master Reasoning LLM (`agents/master_llm.py`, 226 lines)** — provider chain
`anthropic → gemini → local → offline` with circuit breakers; `_parse_verdict`,
`_weighted_score`, `provider_status()`, `reason()`. Always ends at the deterministic
offline reasoner, so **no API key is required**.

### Data layer

| Module | Lines | Role |
|---|---|---|
| `data/provider.py` | 197 | Provider registry, per-provider circuit breakers, stale-while-revalidate, per-asset preference, `ingest_resilient` |
| `data/ingest.py` | 74 | yfinance fetch + Kafka publish |
| `data/lse.py` | 118 | London Strategic Edge API client |
| `data/universe.py` | 85 | Universe catalog sync/search |
| `data/consumer.py` | 49 | Redpanda/Kafka ingest-event consumer (optional extra) |

### Missing / gaps
- **Quant Agent is still basic statistics**, not the multi-factor model the blueprint
  calls for. The factor signal exists and is validated for *evaluation*, but has not been
  shown to predict returns ([§8.4](#84-factor-ic-bench--live)).
- **News now has live RSS/Atom ingestion** (`data/news_feed.py`, `arthaai ingest-news`,
  deterministic lexicon sentiment, idempotent Qdrant upsert); the store still defaults to
  the illustrative seed until feeds are configured. Alt_Agent remains a stub.
- Correlation-regime detection (`ARTHA-215`) and a cross-sectional / **IC-weighted
  composite** (`ARTHA-219`) are now **built**; the composite is gradeable by the backtest
  (`run_backtest(signal_series=...)`) but is **not yet wired into live sizing**.

---

## 5. Alpha Zoo — factor engine

| Module | Lines | Role |
|---|---|---|
| `factors/base.py` | 454 | Operators: `rank`, `zscore`, `scale`, `delta`, `ts_*`, `decay_linear`, `safe_div`, … |
| `factors/registry.py` | 352 | AST-scan discovery, lazy import, **helper injection**, health |
| `factors/panel.py` | 132 | Wide OHLCV panel; derives `vwap`/`amount`; daily de-dup |
| `factors/eval.py` | 242 | Rank-IC, t-stat, **Benjamini-Hochberg FDR**, IC embargo |
| `factors/composite.py` | ~230 | Cross-sectional z-score composite; **IC-weighted composite** (expanding rank-IC weights, embargoed); asset ranking / top-K |

- **445 alphas** load cleanly (`alpha101` 101, `gtja191` 190, `qlib158` 154).
- **Loader helper injection**: many machine-extracted zoo files call helpers
  (`safe_div`, `ts_std`, `np`, …) they never import. Rather than patch hundreds of
  generated files, `registry._inject_helpers` supplies the `factors.base` namespace on
  load (never overriding names the module defines). Combined with panel-derived
  `vwap`/`amount` and removing a leaked junk line, single-symbol compute went
  **341 → 403/445**; the remaining 42 are cross-sectional (undefined for one symbol).
- `factors bench` evaluates the zoo with **BH FDR** and an explicit observation count.
- **Cross-sectional composite (`factors/composite.py`)**: standardises each factor across
  symbols per date (z-score), averages into a composite, and ranks the universe. An
  **IC-weighted** variant weights each factor by the expanding mean of its historical rank-IC,
  floored at 0 and **lagged by `horizon + embargo − 1`** bars so a date's weight never uses the
  forward return it is graded on. CLI: `arthaai factors composite --symbols …`.

---

## 6. Tier 3 — Oversight & Sizing

### Implemented

**Asset Manager (`agents/asset_manager.py`, ~290 lines)** — deterministic, pure-function
sizing:
- **Discrete Kelly is the driver**: `f = W − (1−W)/R`; continuous Kelly is informational.
- Quarter-Kelly scaling (`kelly_fraction=0.25`); **5% hard policy cap**; negative/zero
  edge → **flat** (no shorting).
- LLM `confidence` tempers `W` (50/50 blend), never overrides the caps.
- **Factor gate (E2)** — optional, dampen-only: a factor signal that conflicts with a long
  edge multiplies size by `factor_dampening` (0.5). Never amplifies; still capped.
- **Volatility targeting (C)** — scales toward an annualised target vol, de-risk-only by
  default (`vol_max_leverage=1.0`).
- **Dynamic Kelly (ARTHA-311)** — optional inverse-vol scaling of the Kelly *fraction*,
  bounded to `[kelly_fraction_min, kelly_fraction_max]`.
- **Portfolio Kelly (ARTHA-309)** — `portfolio_size()` combines per-asset discrete Kelly
  fractions with a covariance-based, **de-risk-only** correlation multiplier (≤ 1) and a
  total-exposure cap (`max_portfolio_exposure`); CLI `arthaai portfolio`.
- **Tail risk (ARTHA-310)** — `agents/risk.py`: historical and parametric **VaR / Expected
  Shortfall**. Parametric 95% VaR/ES is reported on `Allocation` (informational, never feeds
  sizing); historical VaR/ES is reported by the `portfolio` CLI on the sized book's return
  series.
- `Allocation` reports `discrete_kelly`, `continuous_kelly`, `fractional`,
  `final_fraction`, `capped_by_policy`, `factor_multiplier`, `factor_signal`,
  `vol_multiplier`, `kelly_fraction_used`, `var_95`, `expected_shortfall_95`, and a human
  rationale.

**Backtest engine (`backtest/engine.py`, ~250 lines)** — walk-forward, look-ahead-guarded
(signal at bar *t* sees bars ≤ *t*; earns *t+1*'s return). Supports `data_slice`,
`cost_bps` (turnover friction), `factor_gate`, `vol_target`, and **`signal_series`** — a
precomputed per-bar signal that lets cross-sectional / composite signals be graded by the
same gate. `oos_slice()` and **`oos_windows()`** (non-overlapping, most-recent-first).

**Promotion gate (`backtest/promotion.py`, 137 lines)** — a signal is promoted only if it
passes **all windows** and all three criteria:
1. Sharpe ≥ `MIN_SHARPE` (1.0)
2. Max drawdown ≤ `MAX_DD` (20%)
3. **Beats B&H, exposure-matched** — compares the **100%-exposure long-only** return to
   B&H, *not* the ~1–5%-exposure Kelly return (the old comparison was unwinnable by
   construction). `combine_windows()` requires the intersection across windows.

**Persistence (`db/timescale.py`, 281 lines)** — `signal_promotion` upsert/get and
`list_qualified_symbols`; provider preference recording; **canonical daily timestamps**;
`load_ohlcv` de-duplicates by day; `repair_daily_duplicates()`.

### Missing / gaps
- Portfolio Kelly, VaR/Expected-Shortfall, and dynamic Kelly are now **implemented**
  (`ARTHA-309/310/311`); portfolio Kelly is exposed via `arthaai portfolio` and the VaR/ES
  via `Allocation`, but neither is yet wired into the live `execute` path.
- Shadow-account bias audit deferred (needs real trade history).

---

## 7. Tier 4 — Action

### Implemented

**State machine (`execution/state.py`, 247 lines)**
- `Fill`; `Position` lifecycle `FLAT → PENDING_ENTRY → OPEN → EXITING → CLOSED`.
- `Portfolio` — multi-position aggregate with a **rolling peak-to-trough equity-curve
  breaker**, `record_entry_equity()`, `mark_to_market()`, `add_proceeds()`,
  `_is_new_session()`/`reset_day()` (calendar-day reset; trip counter escalates to
  `SYSTEM_LOCKED`), and **`kill_switch()`** (flatten all + require manual unlock).

**Engine (`execution/engine.py`, ~280 lines)** — `ExecutionEngine` composes the state
machine: `submit()` (creates order, applies the fill model, seeds entry equity, attaches
stop-loss), `step()` (mark-to-market + fire stops/targets), `exit_position()`,
`kill_switch()`, `breaker_state`, `equity`. `TradingHalted` raised when halted. `Order`
carries `status` (`filled`/`partial`/`rejected`), `filled_quantity`, `slippage_bps`.

**Fill model (`execution/fills.py`, ARTHA-409)** — deterministic adverse-fill simulation:
**slippage** (bps, adverse per side), **partial fills** (capped by `participation_rate × bar
volume`), and **rejection** (seeded RNG, reproducible). Defaults are a no-op, so it is
strictly opt-in and existing behaviour is unchanged.

**Human decision gate (`execution/approval.py`, ARTHA-308)** — append-only, restart-safe
proposal/decision workflow (`ApprovalGate`, `Proposal`). `arthaai execute` only places an
order once a proposal is approved; `arthaai approve` / `arthaai reject` are separate acts.
Proposal and decision both land in the audit log.

**Position ledger + live stop enforcement (`execution/ledger.py`, ARTHA-4xx)** — `execute
--ledger` records each opened position to an append-only JSONL ledger; `arthaai mark`
steps open positions against the latest bar and fires the stop/target via the canonical
`Position.step` state machine, so stops are enforced in the live paper path (not only in
`paper-sim`). `execute` also enforces the portfolio exposure cap from the ledger's open
notional.

**Audit log (`execution/audit.py`, 59 lines)** — append-only JSONL (`AuditLog` +
`read_audit`); engine records orders, fills (with `stop_loss`/`target`/`signal` reason),
breaker trips, kill switch, unlock. Opt-in, so tests never write files.

**Bar-loop simulation (`execution/simulate.py`, 177 lines)** — `simulate_symbol()` drives
the engine bar-by-bar so **stop-losses actually fire**; look-ahead safe; long-only;
returns fills, stop/target counts, realised P&L, equity curve. Exposed as
`arthaai paper-sim`.

### Missing / gaps
- **Stop-loss is enforced in the paper-sim path, not in live `execute`** (single-order).
- Fill simulation (slippage/partial/rejection) is **implemented** (`ARTHA-409`) and wired
  through the engine; the live `execute` path still uses the no-op default model.
- Human approval gate is **implemented** (`ARTHA-308`).
- Live broker (IBKR/Alpaca) and Pine/MQL5/TDX exporters deferred by Law 3.
- No OMS/order-state lifecycle for real orders.

---

## 8. Verification log (live)

All results below were produced against the running Docker stack
(`docker compose up -d`: TimescaleDB, Qdrant, Redpanda, OPA, Vault).

### 8.1 Schema migration — ✅ verified
`arthaai migrate` applied **11 idempotent statements** and **repaired 1095 duplicate
daily bars**. Before: GLD 1008 rows / 504 days (2/day); after: 499 rows / 499 days.

### 8.2 Promotion gate — ✅ verified (as a gate)
`arthaai promote GLD --signal breakout --cost-bps 10` (two OOS windows):

| Window | Sharpe | Long-only | B&H | Pass |
|---|---|---|---|---|
| 349–499 | −0.23 | −3.24% | −7.17% | ❌ |
| 199–349 | **2.33** | +26.72% | +26.72% | ✅ |

Combined verdict: **REJECTED (1/2 windows failed)**. Critically, window 199–349 *looks*
promotable — the all-windows rule is what prevents cherry-picking. `trend` behaves the
same. Rows persisted to `signal_promotion`.

### 8.3 E3 — the edge gate — ❌ **FAILS**
Re-confirmed across **four signal families** on **2026-10-04** against the live stack with a
widened **45-symbol LSE universe** (~500 daily bars each, 2024-08 → 2026-10). The promotion
gate (Sharpe ≥ 1.0 · MaxDD ≤ 20% · exposure-matched long-only > B&H, on **every** OOS window)
rejects:

| Signal family | Assets | Qualified |
|---|---|---|
| `trend` | 7 | none |
| `breakout` (ADX ≥ 25) | 7 | none |
| equal-weight cross-sectional composite | 7 | none |
| **IC-weighted composite** (h=1 and h=5, min_ic=20) | **45** | none |

No symbol passes all OOS windows. Eight assets are "one-window-shy" at h=1 (SLV, PPLT, PALL,
XLE, XLU, XLC, EWJ, JPM); three at h=5 (SLV, UNG, EWJ). Failures concentrate in the most
recent bull window (e.g. SLV window 351–501 passes strongly — long-only **+31.7%** vs B&H
**−12.4%** — while window 201–351 lags B&H's +124.8% melt-up). **Law 3 holds: nothing is
promotable.** This is a research result, not a coding gap.

### 8.4 Factor IC bench — live
`arthaai factors bench` over **28 assets × 442 factors** (horizon 1, BH FDR α=0.05):

> **0 factors survive BH FDR**; 2 "alive", 10 "reversed", 430 dead.

The IC machinery is correct and the multiple-testing correction is doing its job: with
442 tests, the best t-stat (~−2.7) does not clear the BH threshold. **No cross-sectional
factor shows a robust edge** in this universe/window.

### 8.5 Volatility targeting — implemented, not beneficial here
With `--vol-target 0.15`, window 199–349 Sharpe moved **2.33 → 2.11** (worse). Kept
disabled by default.

### 8.6 Factor-zoo repair — ✅ verified
Single-symbol compute rose **341 → 403/445** after helper injection + `vwap`/`amount`
derivation; the residual 42 are cross-sectional.

### 8.7 E3 exhaustion — the criterion-mismatch issue
**New finding (2026-10-04).** After four signal families and a 45-asset cross-section all
failed the gate, the failure pattern points at the **criterion**, not only the signal:

- The promotion gate passes a signal only if its **exposure-matched long-only return beats
  buy-and-hold** on *every* OOS window. That is the correct test for a **directional**
  signal (in/out timing vs passive).
- A **cross-sectional factor** has no natural "B&H" comparison. Its correct economic
  expression is a **long/short, market-neutral book** (long top-ranked, short bottom-ranked),
  judged on Sharpe / IC — not on beating a fully-invested benchmark.
- The observed failures are almost entirely in the **recent bull window**, exactly where a
  defensive long/flat cross-sectional rule *should* lag a melt-up while adding value in
  drawdowns (SLV 351–501: +31.7% vs −12.4% B&H). That is consistent with a real but
  defensively-tilted signal being graded against an unsuitable benchmark.

**This does not make E3 pass and must not be used to relax the gate silently.** It means the
release criterion and the cross-sectional research direction are **misaligned**. Resolving it
is a **policy decision**: either (a) accept no promotable directional edge (Law 3 holds), or
(b) explicitly add a *market-neutral* evaluation path for cross-sectional signals (Sharpe/IC
against a dollar-neutral benchmark) as a **separate, documented criterion** — not by weakening
the existing B&H gate.

---

## 9. Cross-cutting concerns

| Concern | Status |
|---|---|
| **Policy / identity** (`security/policy.py`, 39) | SPIFFE-style `AgentIdentity` + `authorize_tool`; **OPA-backed** with in-process least-privilege fallback (`security/opa.py`, 47) |
| **Secrets** (`security/vault.py`, 46) | Vault read/write; env fallback |
| **Resiliency** (`resiliency/breaker.py`, 44) | `pybreaker` per service; `guarded(name, fn, fallback)` |
| **CI** (`.github/workflows/ci.yml`) | Q1 `compileall` · Q2 `pytest -k "not health"` · correctness-only lint (zoo excluded) |
| **Observability** | ✅ OpenTelemetry tracing (`observability/tracing.py`, `ARTHA-507`) + Prometheus metrics (`observability/metrics.py`, `ARTHA-508`); optional `obs` extra; authenticated `/metrics` (same principal/mTLS as data routes) + request middleware that labels only matched route templates; no-op when the extra is absent |
| **Alerting / cost tracking** | 🟡 hooks added: `observability/alerts.py` (log + `arthaai_alerts_total`) wired to circuit-breaker trips; `arthaai_llm_calls_total{provider,outcome}` usage tracking in the Master LLM. No external pager/billing integration (deploy infra). |

---

## 10. Known issues & defects

1. **E3 fails** — no promotable edge across **four signal families** (`trend`, `breakout`,
   equal-weight composite, IC-weighted composite) and a widened **45-asset** cross-section.
   No factor in the zoo is FDR-significant. The blocking release-gate item; a research
   problem, not a coding one.
2. **Promotion-gate criterion vs cross-sectional signals (new)** — the gate grades
   exposure-matched long-only vs B&H, which fits *directional* signals; a cross-sectional
   factor's natural expression is a long/short market-neutral book. The failure pattern is
   consistent with a defensive signal graded against an unsuitable benchmark. **Do not
   silently relax the gate**: choose (a) accept no edge, or (b) add a separate, documented
   market-neutral evaluation path. See [§8.7](#87-e3-exhaustion--the-criterion-mismatch-issue).
3. **Factor gate is ON by default but unjustified** — it lowered OOS Sharpe and its input
   factor signal has no significant edge. **Recommendation: default `factor_gate=False`**
   (Law 3: don't trust an unproven signal). `ARTHAAI_FACTOR_GATE` re-enables it.
4. **Duplicate daily bars (fixed)** — dual-provider ingest stored two timestamps/day for
   GLD/SLV, corrupting backtests. Fixed at ingest (canonical midnight key), at read
   (`load_ohlcv` de-dup), in `build_panel`, and via `arthaai migrate`.
5. **qlib158 residual** — 42 cross-sectional factors are degenerate on a single symbol
   (by design); they require a universe panel (now supplied by `factors/composite.py`).
6. **JWT verified against a local IdP, not production** — `tests/test_oauth_jwt.py` exercises
   the full signature path against a generated JWKS server; wiring a real IdP is config.
7. **CI now runs on GitHub** (workflow installs `.[dev,obs,auth]`; observability tests skip when the `obs` extra is absent). All work is committed and pushed on `feat/arthaai-core`.
8. **qdrant client/server version mismatch** and **Vault 404s** — cosmetic, as before.
9. `test_health` pings TimescaleDB; excluded from normal runs and CI.

---

## 11. Test inventory

**353 passed, 1 deselected** (`test_health`, needs Docker) in ~14s.

| File | Focus |
|---|---|
| `test_indicators.py` / `test_indicators_extra.py` | SMA/RSI/ADX/trend/breakout · ATR/Bollinger/MACD/OBV/VWAP |
| `test_kelly.py` / `test_factor_gate.py` / `test_vol_target.py` | Discrete/continuous Kelly, policy cap, factor gate, vol targeting |
| `test_backtest.py` / `test_backtest_costs.py` / `test_factor_gate_backtest.py` | Drawdown, cost model, gate wiring into the backtest |
| `test_promotion.py` | Criteria, exposure-matched B&H, `oos_slice`, `oos_windows`, `combine_windows` |
| `test_execution.py` / `test_execution_state.py` / `test_execution_audit.py` / `test_execution_sim.py` | Orders, state machine, breaker, kill switch, audit persistence, stop-loss simulation |
| `test_provider.py` | Provider chain, incremental ingest, preference, DB-error fail-open |
| `test_lse.py` / `test_universe` (in provider) | LSE parsing/fallback, universe |
| `test_factors.py` / `test_factors_eval.py` | Base operators, panel, IC, BH FDR |
| `test_eval.py` / `test_llm.py` | Golden fixtures, calibration, provider chain fallback |
| `test_gateway.py` / `test_gateway_auth.py` | Auth required, cookie, JWT/static dispatch, rate-limit key |
| `test_policy.py` | OPA allow/deny |
| `test_migrate.py` / `test_daily_bars.py` | SQL splitter, schema contents · daily-bar canonicalisation/de-dup |
| `test_execution_fills.py` | Fill model: slippage, partial fills, seeded rejection, engine wiring |
| `test_risk.py` | Historical/parametric VaR, Expected Shortfall, sizing report |
| `test_portfolio_kelly.py` | Covariance de-risk, exposure cap, dynamic Kelly fraction bounds |
| `test_approval.py` / `test_mtls.py` | Human gate propose/approve/reject + persistence · mTLS fail-closed |
| `test_composite.py` | Cross-sectional z-score, composite, ranking, IC-weighted (embargo, fallback) |
| `test_correlation_regime.py` / `test_news_feed.py` | Correlation regime labels · RSS/Atom parse, sentiment, SSRF guard, upsert |
| `test_observability.py` / `test_oauth_jwt.py` | Prometheus/OTel + `/metrics` · real-IdP JWT via local JWKS server (skip without extras) |
| `test_ledger.py` | Position ledger replay · live stop/target firing · `mark` CLI · exposure guard |

---

## 12. CLI reference

| Command | Purpose |
|---|---|
| `health` | Ping TimescaleDB extension |
| `migrate` | Apply idempotent schema + repair duplicate daily bars |
| `universe` | Sync/search the asset universe catalog |
| `ingest` / `ingest-lse` | Ingest bars (provider chain / LSE) |
| `provider-status` | Show/set the stored provider for a symbol |
| `analyze` | Run the full multi-agent pipeline |
| `execute` | Place one paper order (`--audit` JSONL); `--approval`/`--proposal-id` enables the human gate; `--ledger` records for stop monitoring; `--force` overrides the exposure cap |
| `mark` | Step open ledger positions against the latest bar and fire stop/target (live stop enforcement) |
| `approve` / `reject` | Approve or reject a pending human-gate proposal (`--by`) |
| `paper-sim` | Bar-by-bar paper simulation that fires stops/targets (`--slippage-bps`, `--participation`, `--reject-probability`, `--fill-seed`) |
| `portfolio` | Covariance-aware portfolio Kelly across a universe |
| `backtest` | Walk-forward backtest (`--signal`, `--adx`, `--cost-bps`, `--vol-target`) |
| `promote` | OOS promotion gate, multi-window, exposure-matched (`--windows`, `--cost-bps`, `--vol-target`) |
| `promote-sweep` | Sweep the promotion gate across a universe; list every qualified symbol |
| `compare` | Compare signals across assets |
| `factors` | `list` / `show` / `bench` (BH-corrected IC) / `composite` (`--ic-weighted`) |
| `ingest-news` | Ingest live RSS/Atom headlines into Qdrant for a symbol (defaults to `ARTHAAI_NEWS_FEEDS`) |
| `eval` | Golden-fixture LLM eval |
| `llm-status` | Probe the LLM provider chain |
| `seed-news` / `seed-secrets` | Seed Qdrant news / Vault secrets |
| `serve` | Run the Tier 1 gateway |
| `consume` | Consume ingest events from Redpanda |

---

## 13. Implementation by tier

| Tier | Planned | Implemented | Key gap |
|---|---|---|---|
| **1 — Interface & Ingress** | ~100% | ~95% | Production IdP wiring; mTLS (infra) |
| **2 — Intelligence Core** | ~100% | ~85% | Quant factor edge; Alt stub; composite not wired to sizing |
| **Alpha Zoo** | ~100% | ~95% | No FDR-significant edge; IC-weighted composite built, not live-wired |
| **3 — Oversight & Sizing** | ~100% | ~95% | Portfolio Kelly/VaR not wired into live `execute` |
| **4 — Action** | ~100% | ~85% | Live-loop stops; broker (deferred); exporters |
| **Cross-cutting** | ~100% | ~80% | Alerting; cost tracking |
| **★ Edge (E1–E3)** | ~100% | **E1✅ E2🟡 E3❌** | E3 research result + gate/criterion mismatch ([§8.7](#87-e3-exhaustion--the-criterion-mismatch-issue)) |

---

## 14. Remaining work

**Blocking the release gate**
1. ✅ **E3 decision recorded (2026-10-10): hold release.** No separate market-neutral
  criterion is approved; no promotable edge exists. Keep the directional B&H gate and
  Law 3 unchanged. See [§8.7](#87-e3-exhaustion--the-criterion-mismatch-issue).
2. ✅ **Factor-gate default** — `factor_gate=False`; explicit `ARTHAAI_FACTOR_GATE=true`
  opt-in is retained until a factor signal passes promotion.
3. **Commit + push** — ✅ done: `92727b4` (backlog), `d8a0306` (follow-ups), `af8bc89` (CI extras) all pushed to `origin/feat/arthaai-core`.

**Completed this pass (was on the list)**
4. ✅ **Live stop enforcement** — `execute --ledger` + `arthaai mark` fire stops/targets in the live path.
5. ✅ **`promote-sweep`** CLI + authenticated gateway **`/promotions`** endpoint.
6. ✅ **Portfolio exposure guard + VaR/ES** surfaced in the live `execute` path.
7. ✅ **Composite → live sizing** is now *wired into the backtest* (`run_backtest(signal_series=...)`) and rankable via `factors composite --ic-weighted`; live-sizing wiring still pending E3.
8. ✅ **Config-driven news feeds** (`ARTHAAI_NEWS_FEEDS`, `news_auto_ingest`).
9. ✅ **Alerting hooks** (`observability/alerts.py`) + **LLM call tracking** (`arthaai_llm_calls_total`).

**Remaining (gated on the E3 decision)**
10. **Composite → live sizing** — deferred while no signal passes E3 (Law 3). Reopen only
  after an approved candidate passes promotion; do not wire an unproven signal live.
11. **Broker adapter + Pine/MQL5/TDX exporters** — deferred until E3 passes and paper
  stop operations are verified. Broker automation remains distinct from operator-invoked
  `mark`; exporter work must not imply live approval.

---

## 15. Commit history

| Commit | Description |
|--------|-------------|
| `af8bc89` | ci: install obs+auth extras; skip observability tests without extras |
| `d8a0306` | feat: live stop ledger + mark, promote-sweep, exposure guard, news feeds, alerts |
| `92727b4` | feat: fill sim, tail risk, portfolio/dynamic Kelly, composite, observability, human gate |
| `2ae43ef` | feat: provider-chain wiring, Tier 4 execution, promotion gate, factor engine |
| `4e830d0` | docs: rebuild project board from independent code verification |
| `fa6ac07` | docs: refresh status report summary, commit history, TOC |
| `88c3f22` | Complete architecture status report + CLI/schema/DB refactor |
| `08183f9` | Execution state machine, equity-curve breaker, promotion gate |
| `b822afe` | Green the branch against SPEC.md quality gates (Q1–Q3) |
| `0b0c539` | Factor zoo and provider workflows |
| `b0252a6` | 4-tier architecture status report |
| `57abb1d` | Breakout live wiring + eval calibration + OPA fix + AGENTS.md |
| `b6b9661` | Golden-fixture eval harness for Master Reasoning LLM |
| `5577817` | Secure gateway — authenticate /ohlcv, httpOnly cookie |

> **All committed and pushed.** The Phase 0–3 + A–D body of work, the **2026-10-04 backlog
> session** (13 tickets), the `/review uncommitted` fix pass, the §14 follow-ups, the widened
> LSE universe, and this report revision are all on `origin/feat/arthaai-core` (HEAD `af8bc89`).
> Working tree clean, 0 ahead / 0 behind.

---

*Decision-support only · paper context · not investment advice.*
