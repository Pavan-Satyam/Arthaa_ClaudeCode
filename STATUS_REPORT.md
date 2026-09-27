# ArthaAI — Architecture Status Report

*Last revised: 2026-09-27 · version 0.1.0 · branch `feat/arthaai-core`*

ArthaAI is a zero-trust multi-agent LLM framework for equities & commodities analysis.
The deterministic quant layer computes every number; the LLM only synthesises and
explains. This report is written **from the code**, not from intent: every "implemented"
claim below was read out of the repository, and the verification results in
[§8](#8-verification-log-live) were produced against the running Docker stack.

**How to read this:** each tier separates *what's implemented* from *what's missing*,
and marks verified vs. unverified. The single most important number in the whole
system is **E3** — whether a signal beats buy-and-hold out-of-sample. It currently
**fails** ([§8.3](#83-e3--the-edge-gate--fails)).

---

## Table of Contents

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
- **E3 fails, live-verified.** On GLD, both `trend` and `breakout` are rejected across
  two independent OOS windows (hit-rate 46–63%, no window consistently beats B&H with
  Sharpe ≥ 1.0). No factor in the 442-strong zoo survives Benjamini-Hochberg FDR on a
  28-asset cross-section.
- **E2 is wired** (the factor signal now drives sizing via a dampen-only gate), but the
  evidence says it should stay **off**: it lowered OOS Sharpe on GLD, and the factor
  signal it consumes has no FDR-significant edge. See [§10](#10-known-issues--defects).
- A genuine **data-corruption bug was found and fixed** this session: GLD/SLV carried
  two bars per day (LSE `00:00` + yfinance `13:30`), which silently doubled their series
  and distorted every backtest. 1095 duplicate bars were removed.

| Area | Verdict |
|---|---|
| Tier 1 — Interface & Ingress | ✅ implemented (JWT/OAuth 2.1, rate limits, CORS) |
| Tier 2 — Intelligence Core | 🟡 agents work; Quant "edge" still unproven |
| Alpha Zoo factor engine | 🟡 445 factors, 403 compute; no FDR-significant edge |
| Tier 3 — Oversight & Sizing | ✅ Kelly + policy caps + cost-aware, exposure-matched promotion gate |
| Tier 4 — Action | ✅ paper engine, stops, kill switch, audit; broker deferred by Law 3 |
| **★ Edge (E1–E3)** | **🟡 E1/E2 wired · ❌ E3 fails** |

**Overall: ~80% of the blueprint is code-complete; 0% of the release gate is met** —
because the release gate is gated on E3, and E3 is a research result, not a checkbox.

---

## 2. System at a glance

| Metric | Value |
|---|---|
| Python source files | 50 (excl. generated zoo) |
| Test files | 25 |
| Tests passing (DB-independent) | **220** (+1 deselected `health`) |
| CLI commands | 19 |
| Registered factor alphas | **445** (alpha101 101, gtja191 190, qlib158 154) |
| DB symbols with OHLCV | ~40 |
| Quality gates | `compileall` clean · correctness lint clean · CI workflow defined |

### Data flow

```
ingest (provider chain: LSE → yfinance, incremental, SWR fallback)
    │  fan-out (LangGraph)
    ├── DB_Agent      → technical indicators + ADX regime signal selector
    ├── Quant Agent   → μ / σ² / signal-conditioned Kelly inputs + factor signal
    ├── News_Agent    → hybrid-search sentiment (Qdrant, circuit-breaker-guarded)
    └── Alt_Agent     → physical signal (STUB)
    │  converge → GraphState
    ▼
Master Reasoning LLM  → direction + confidence + rationale (provider chain → offline)
    ▼
Asset Manager Agent   → discrete Kelly (primary) + cont. Kelly (info) + factor gate
                        + vol targeting + 5% policy cap → allocation
    ▼
Tier 4 paper execution → Position/Portfolio state machine, mandatory stop-loss,
                          equity-curve breaker, kill switch, JSONL audit log
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
- **mTLS is infrastructure, not code** (`ARTHA-110`) — documented as terminated upstream.
- **JWT path not verified against a real IdP** (no `pyjwt` installed here; only the
  dispatch, claim-mapping, and failure paths are unit-tested).
- No refresh-token rotation; expiry is enforced but rotation is operational.

---

## 4. Tier 2 — Intelligence Core

### Implemented

**Orchestrator (`arthaai/orchestration/graph.py`, 86 lines)** — LangGraph fan-out/merge
with nodes `_ingest → _db → _quant → _news → _alt → _master → _asset_manager`, plus
`analyze()` used by the gateway and CLI. The ingest node now calls
**`ingest_resilient`** (incremental, multi-provider) instead of the old yfinance-only path.

**GraphState (`orchestration/state.py`)** — `symbol`, `skip_ingest`, `db`, `quant`,
`news`, `alt`, `verdict`, `allocation`.

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
- News is seeded/illustrative, not a live feed; Alt_Agent is a stub (paid feeds).
- No correlation-regime detection (`ARTHA-215`) or cross-sectional composite wired into
  sizing (`ARTHA-219`).

---

## 5. Alpha Zoo — factor engine

| Module | Lines | Role |
|---|---|---|
| `factors/base.py` | 454 | Operators: `rank`, `zscore`, `scale`, `delta`, `ts_*`, `decay_linear`, `safe_div`, … |
| `factors/registry.py` | 352 | AST-scan discovery, lazy import, **helper injection**, health |
| `factors/panel.py` | 132 | Wide OHLCV panel; derives `vwap`/`amount`; daily de-dup |
| `factors/eval.py` | 242 | Rank-IC, t-stat, **Benjamini-Hochberg FDR**, IC embargo |

- **445 alphas** load cleanly (`alpha101` 101, `gtja191` 190, `qlib158` 154).
- **Loader helper injection**: many machine-extracted zoo files call helpers
  (`safe_div`, `ts_std`, `np`, …) they never import. Rather than patch hundreds of
  generated files, `registry._inject_helpers` supplies the `factors.base` namespace on
  load (never overriding names the module defines). Combined with panel-derived
  `vwap`/`amount` and removing a leaked junk line, single-symbol compute went
  **341 → 403/445**; the remaining 42 are cross-sectional (undefined for one symbol).
- `factors bench` evaluates the zoo with **BH FDR** and an explicit observation count.

---

## 6. Tier 3 — Oversight & Sizing

### Implemented

**Asset Manager (`agents/asset_manager.py`, 151 lines)** — deterministic, pure-function
sizing:
- **Discrete Kelly is the driver**: `f = W − (1−W)/R`; continuous Kelly is informational.
- Quarter-Kelly scaling (`kelly_fraction=0.25`); **5% hard policy cap**; negative/zero
  edge → **flat** (no shorting).
- LLM `confidence` tempers `W` (50/50 blend), never overrides the caps.
- **Factor gate (E2)** — optional, dampen-only: a factor signal that conflicts with a long
  edge multiplies size by `factor_dampening` (0.5). Never amplifies; still capped.
- **Volatility targeting (C)** — scales toward an annualised target vol, de-risk-only by
  default (`vol_max_leverage=1.0`).
- `Allocation` reports `discrete_kelly`, `continuous_kelly`, `fractional`,
  `final_fraction`, `capped_by_policy`, `factor_multiplier`, `factor_signal`,
  `vol_multiplier`, and a human rationale.

**Backtest engine (`backtest/engine.py`, 243 lines)** — walk-forward, look-ahead-guarded
(signal at bar *t* sees bars ≤ *t*; earns *t+1*'s return). Supports `data_slice`,
`cost_bps` (turnover friction), `factor_gate`, `vol_target`. `oos_slice()` and
**`oos_windows()`** (non-overlapping, most-recent-first).

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
- No portfolio-level Kelly (covariance/correlation), no VaR/Expected-Shortfall/stress
  tests, no dynamic Kelly by vol regime (`ARTHA-309/310/311`).
- Human decision gate is advice-only (no approval workflow).
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

**Engine (`execution/engine.py`, 231 lines)** — `ExecutionEngine` composes the state
machine: `submit()` (creates order, seeds entry equity, attaches stop-loss),
`step()` (mark-to-market + fire stops/targets), `exit_position()`, `kill_switch()`,
`breaker_state`, `equity`. `TradingHalted` raised when halted.

**Audit log (`execution/audit.py`, 59 lines)** — append-only JSONL (`AuditLog` +
`read_audit`); engine records orders, fills (with `stop_loss`/`target`/`signal` reason),
breaker trips, kill switch, unlock. Opt-in, so tests never write files.

**Bar-loop simulation (`execution/simulate.py`, 177 lines)** — `simulate_symbol()` drives
the engine bar-by-bar so **stop-losses actually fire**; look-ahead safe; long-only;
returns fills, stop/target counts, realised P&L, equity curve. Exposed as
`arthaai paper-sim`.

### Missing / gaps
- **Stop-loss is enforced in the paper-sim path, not in live `execute`** (single-order).
- Fill simulation has no slippage/partial fills (`ARTHA-409`).
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
Neither signal beats B&H with Sharpe ≥ 1.0 in every OOS window. Hit-rate on the most
recent window is ~46%; the signal has no reliable directional edge on GLD in this period.
**Law 3 holds: nothing is promotable.**

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

---

## 9. Cross-cutting concerns

| Concern | Status |
|---|---|
| **Policy / identity** (`security/policy.py`, 39) | SPIFFE-style `AgentIdentity` + `authorize_tool`; **OPA-backed** with in-process least-privilege fallback (`security/opa.py`, 47) |
| **Secrets** (`security/vault.py`, 46) | Vault read/write; env fallback |
| **Resiliency** (`resiliency/breaker.py`, 44) | `pybreaker` per service; `guarded(name, fn, fallback)` |
| **CI** (`.github/workflows/ci.yml`) | Q1 `compileall` · Q2 `pytest -k "not health"` · correctness-only lint (zoo excluded) |
| **Observability** | ❌ no OpenTelemetry (`ARTHA-507`), no Prometheus (`ARTHA-508`) |
| **Alerting / cost tracking** | ❌ not implemented |

---

## 10. Known issues & defects

1. **E3 fails** — no promotable edge on GLD; no FDR-significant factor. This is the
   blocking release-gate item and is a research problem, not a coding one.
2. **Factor gate is ON by default but unjustified** — it lowered OOS Sharpe and its input
   factor signal has no significant edge. **Recommendation: default `factor_gate=False`**
   (law 3: don't trust an unproven signal). `ARTHAAI_FACTOR_GATE` re-enables it.
3. **Duplicate daily bars (fixed)** — dual-provider ingest stored two timestamps/day for
   GLD/SLV, corrupting backtests. Fixed at ingest (canonical midnight key), at read
   (`load_ohlcv` de-dup), in `build_panel`, and via `arthaai migrate`.
4. **qlib158 residual** — 42 cross-sectional factors are degenerate on a single symbol
   (by design); they require a universe panel.
5. **JWT unverified against a real IdP**; `pyjwt[crypto]` not installed here.
6. **CI never run on GitHub**; work is **uncommitted** on the working tree.
7. **qdrant client/server version mismatch** and **Vault 404s** — cosmetic, as before.
8. `test_health` pings TimescaleDB; excluded from normal runs and CI.

---

## 11. Test inventory

**220 passed, 1 deselected** (`test_health`, needs Docker) in ~8s.

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
| `execute` | Place one paper order (`--audit` JSONL) |
| `paper-sim` | Bar-by-bar paper simulation that fires stops/targets |
| `backtest` | Walk-forward backtest (`--signal`, `--adx`, `--cost-bps`, `--vol-target`) |
| `promote` | OOS promotion gate, multi-window, exposure-matched (`--windows`, `--cost-bps`, `--vol-target`) |
| `compare` | Compare signals across assets |
| `factors` | `list` / `show` / `bench` (BH-corrected IC) |
| `eval` | Golden-fixture LLM eval |
| `llm-status` | Probe the LLM provider chain |
| `seed-news` / `seed-secrets` | Seed Qdrant news / Vault secrets |
| `serve` | Run the Tier 1 gateway |
| `consume` | Consume ingest events from Redpanda |

---

## 13. Implementation by tier

| Tier | Planned | Implemented | Key gap |
|---|---|---|---|
| **1 — Interface & Ingress** | ~100% | ~90% | IdP-verified JWT; mTLS (infra) |
| **2 — Intelligence Core** | ~100% | ~75% | Quant factor edge; live news; Alt stub |
| **Alpha Zoo** | ~100% | ~90% | 42 cross-sectional factors need a universe; no composite wired |
| **3 — Oversight & Sizing** | ~100% | ~85% | Portfolio Kelly; VaR/ES; human gate |
| **4 — Action** | ~100% | ~70% | Fill/slippage sim; live-loop stops; broker (deferred) |
| **Cross-cutting** | ~100% | ~55% | OTel; Prometheus; alerting |
| **★ Edge (E1–E3)** | ~100% | **E1✅ E2🟡 E3❌** | E3 is a research result |

---

## 14. Remaining work

**Blocking the release gate**
1. **E3** — find a signal with OOS edge (multi-asset, purged walk-forward, IC-weighted
   composite), or accept that these signals should not trade.
2. **Decide the factor-gate default** — flip to off unless E3 proves the factor signal.
3. **Commit + push**, and let the new CI workflow run.

**High value, low risk**
4. Wire stop-losses into the live `execute` path; add slippage/partial-fill modelling.
5. Expose `signal_promotion` in the gateway/UI; add a `promote --all` sweep.

**Larger, still open**
6. Portfolio Kelly + VaR/ES (`ARTHA-309/310/311`).
7. Cross-sectional factor composite wired into sizing (`ARTHA-219`).
8. OpenTelemetry + Prometheus (`ARTHA-507/508`).
9. Human approval gate with audit trail.
10. Real broker adapter — only after E3 passes (Law 3).

---

## 15. Commit history

| Commit | Description |
|--------|-------------|
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

> **Uncommitted:** the entire Phase 0–3 + A–D body of work (21 modified, 15 new files)
> plus this report revision. Nothing above is pushed beyond `4e830d0`.

---

*Decision-support only · paper context · not investment advice.*
