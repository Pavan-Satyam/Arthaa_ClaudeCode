# ArthaAI — Project Board (Independently Verified)

**Board:** ARTHA · **Branch:** `feat/arthaai-core` @ `88c3f22` · **Rebuilt:** 2026-09-24

**Methodology — read this before trusting any status below:**
This board's design and acceptance criteria come from [SPEC.md](SPEC.md) (the invariants L1–L3, the
edge criterion E1–E3, quality gates Q1–Q4) and [arthaai-architecture.html](arthaai-architecture.html) (the
component list). **`STATUS_REPORT.md` was deliberately not used as a source** — it was found to contain
stale claims (e.g. it says the Alpha-Zoo factor engine doesn't exist; it does). Every ticket marked `DONE`
below was independently confirmed in this session by one of:
- **Reading the source file directly** (cited as `file:lines`)
- **Running the code myself**: `pytest` (113 passed, live), `arthaai analyze/backtest/promote GLD` (live, output reproduced below), `python -m compileall`, targeted `grep`
- **Reading the running Docker stack** (`docker compose ps`)

Every ticket marked `TO DO` is something I confirmed **absent** by reading the relevant module and finding no implementation — not inferred from a doc.

---

## 1. Architecture (HLD, from `arthaai-architecture.html` verbatim)

```
TIER 1 — INTERFACE & INGRESS          "how a request gets in, safely"
  Web Dashboard · FastAPI Gateway · mTLS/OAuth 2.1 (deferred)
                    │
                    ▼
TIER 2 — INTELLIGENCE CORE            "where analysis and data live"
  LangGraph Orchestrator + GraphState (StateStore)
  Kafka/Redpanda Bus · Data Layer (yfinance/LSE → TimescaleDB)
       ├── DB_Agent          → deterministic indicators (SMA/RSI/ADX)
       ├── Quant_Agent ★     → Alpha-Zoo factor engine → tabular signal model  ("the edge lives here")
       ├── News_Agent        → Qdrant hybrid search
       ├── Alt_Agent         → satellite/cargo (deferred, stubbed)
       └── Correlation Regime → risk-off fusion detection (build next, NOT STARTED)
  Master Reasoning LLM (never predicts a number)
                    │
                    ▼
TIER 3 — OVERSIGHT & SIZING           "how much, and who signs off"
  Asset Manager (Kelly + hard 5% cap) · Human Decision Gate · Shadow Account Audit (deferred)
                    │
                    ▼
TIER 4 — ACTION                       "simulated today; guard-railed always"
  Paper Execution (kill switch, stop-loss, drawdown breaker, audit log)
  Live Broker (deferred by Law 3) · Script Exporters (deferred)

CROSS-CUTTING: Zero-trust (OPA+Vault) · Resiliency (circuit breakers) · Observability (deferred) · Backtest Gate
```

**The three laws (SPEC.md §1 — the acceptance criteria for "conformant"):**
- **L1** — Numbers are deterministic; the LLM only explains, never computes
- **L2** — A reproducible graph, not an agent free-loop
- **L3** — Nothing is trusted until it beats buy-and-hold (the promotion gate)

---

## 2. Live verification log (run by me, this session)

```
$ arch -x86_64 .venv/bin/python3.12 -m pytest tests/ -q -k "not health"
113 passed, 1 deselected in 2.43s

$ arch -x86_64 .venv/bin/python3.12 -m compileall arthaai -q
(clean, exit 0)

$ docker compose ps
timescaledb, qdrant, redpanda, opa, vault — all Up

$ arthaai analyze GLD --skip-ingest   (ARTHAAI_LLM_CHAIN=offline)
DB_Agent bullish · RSI 66.0 · ADX 30.2 (trending)
Quant μ +31.94% · σ 25.80% · W 0.56 · R 0.96
Verdict BULLISH · confidence 78% · offline-fallback
Kelly: discrete +0.333, final allocation 5.00% (capped by policy)

$ python -c "from arthaai.agents import quant_agent; quant_agent.run('GLD')"
factor_signal: -9.778 · factors: 5 (alpha101_024/009/012/023/031)

$ grep -c factor_signal arthaai/agents/asset_manager.py
0   ← confirms the factor engine's output never reaches sizing

$ arthaai backtest GLD
strategy (Kelly) +0.66% · buy & hold +70.81% · edge vs B&H -32.34% · Sharpe 0.47 · hit 54.5%

$ arthaai promote GLD
Sharpe 0.43 < 1.0 (FAIL) · Max DD -0.32% (pass) · Beats B&H +0.12% > -4.70% (pass)
REJECTED · Could not save to DB: relation "signal_promotion" does not exist
```

---

## 3. Board Summary

| Epic | Component | Done | To Do | Notes |
|---|---|---|---|---|
| [ARTHA-0](#epic-artha-0--foundation--infra) | Foundation & Infra | 7 | 1 | Docker stack, config, security scaffolding all real |
| [ARTHA-1](#epic-artha-1--tier-1-interface--ingress) | Interface & Ingress | 6 | 4 | Auth is a real seam, not real OAuth |
| [ARTHA-2](#epic-artha-2--tier-2-intelligence-core) | Intelligence Core | 13 | 8 | Two orphaned subsystems found (see §4) |
| [ARTHA-3](#epic-artha-3--tier-3-oversight--sizing) | Oversight & Sizing | 8 | 5 | Kelly math is correct and tested |
| [ARTHA-4](#epic-artha-4--tier-4-action) | Action / Execution | 5 | 7 | Stop-loss logic exists but is dead code in prod paths |
| [ARTHA-5](#epic-artha-5--cross-cutting) | Cross-Cutting | 5 | 5 | No CI pipeline exists (`.github/` is empty) |
| [ARTHA-6](#epic-artha-6--the--priority-edge-criterion) | ★ Edge Criterion | 1 | 2 | The one gate that matters — see below |

---

## 🔴 Newly found during this verification (not in any prior doc)

### ARTHA-201 — Factor signal computed but never reaches sizing
**Status:** `BLOCKED — RELEASE GATE` · **Verified:** live `quant_agent.run('GLD')` returns `factor_signal=-9.778`; `grep factor_signal arthaai/agents/asset_manager.py` → 0 hits ([asset_manager.py](arthaai/agents/asset_manager.py) L44–89 only reads `win_prob`/`win_loss_ratio`/`mu`/`variance`). On GLD the orphaned factor signal is **bearish** while the shipped verdict is **bullish** — they disagree.

### ARTHA-202 — Signal does not beat buy-and-hold
**Status:** `BLOCKED — RELEASE GATE` · **Verified:** live `arthaai promote GLD` → REJECTED, Sharpe 0.43 < 1.0 threshold. `arthaai backtest GLD` → edge −32.34% vs B&H.

### ARTHA-223 — Provider failover chain exists but the main pipeline doesn't use it *(new finding)*
**Status:** `TO DO` · **Priority:** P1 · [data/provider.py](arthaai/data/provider.py) fully implements `ingest_resilient()` (LSE → yfinance → none, incremental via `latest_ts()`) and is wired into the standalone `arthaai ingest` / `arthaai ingest-lse` commands. But [orchestration/graph.py](arthaai/orchestration/graph.py) L27–31 (the `_ingest` node used by `analyze`/`execute`/`backtest`/`promote`) calls `arthaai.data.ingest.ingest()` instead — the **old, yfinance-only, non-incremental** path. The better implementation is built, tested (`test_provider.py`, 25 tests), and unused by the pipeline that matters.

### ARTHA-224 — `signal_promotion` table doesn't exist in the running dev database *(new finding)*
**Status:** `TO DO` · **Priority:** P1 · [schema.sql](arthaai/db/schema.sql) defines the table and is mounted via `docker-entrypoint-initdb.d`, which Postgres only runs on first init of an empty volume. The `timescale_data` volume predates this schema change, so it never ran. Confirmed live: `arthaai promote GLD` computes a correct verdict but fails to persist it (`relation "signal_promotion" does not exist`). No migration tool exists in this repo — schema changes require either a fresh volume or a manual `psql` apply.

### ARTHA-225 — Three new DB helper functions are dead code *(new finding)*
**Status:** `TO DO` · **Priority:** P3 · `record_ingest_provider()`, `set_preferred_provider()`, `get_preferred_provider()` were added to [timescale.py](arthaai/db/timescale.py) L176–208 in the last commit (schema also grew `preferred_provider`/`last_provider`/`last_ingest_at` columns) but have zero call sites anywhere in the codebase (`grep` confirmed). Built for the provider failover chain (ARTHA-223) but never wired in.

### ARTHA-408 — Stop-loss trigger logic exists and is tested, but nothing in production ever calls it *(correction to prior board)*
**Status:** `TO DO` (refined) · **Priority:** P1 · [execution/state.py](arthaai/execution/state.py) L90–109, `Position.step(bar)` correctly fires an exit `Fill` when `low <= stop_price`, and `test_stop_triggered_when_low_hits_stop` passes. But `grep -n "ExecutionEngine\|\.step(" arthaai/backtest/engine.py arthaai/cli.py` → zero hits: the backtest computes returns algebraically (never touches the state machine) and the CLI's `execute` command only calls `.submit()` once. The trigger mechanism is real, just never invoked outside its own unit test.

---

## Epic ARTHA-0 — Foundation & Infra

| ID | Summary | Status | Verified |
|---|---|---|---|
| ARTHA-001 | Docker Compose stack — TimescaleDB, Qdrant, Redpanda, OPA, Vault | ✅ DONE | `docker compose ps` — all 5 services Up |
| ARTHA-002 | `arthaai/config.py` — env-driven `Settings` (pydantic-settings), `.env` support | ✅ DONE | Read in full — 90 lines, all fields wired |
| ARTHA-003 | `arthaai/db/schema.sql` — assets, ohlcv (hypertable), signal_promotion tables | ✅ DONE | Read in full |
| ARTHA-004 | `arthaai/security/vault.py` — Vault KV v2 client, circuit-broken, env fallback | ✅ DONE | Read in full |
| ARTHA-005 | `arthaai/security/opa.py` + `policy/arthaai.rego` — policy client + Rego source | ✅ DONE | Both read in full, scopes match exactly |
| ARTHA-006 | `arthaai/resiliency/breaker.py` — pybreaker CLOSED/OPEN/HALF-OPEN wrapper | ✅ DONE | Read in full — `fail_max=3, reset_timeout=30` |
| ARTHA-007 | `pyproject.toml`, `Makefile` (x86_64-safe wrappers for this Mac) | ✅ DONE | Confirmed `arch -x86_64` wrapper needed and works (Rosetta present) |
| ARTHA-008 | Schema migration tooling (Alembic or similar) | ⬜ TO DO | Confirmed absent — see ARTHA-224 |

---

## Epic ARTHA-1 — Tier 1: Interface & Ingress

| ID | Summary | Status | Verified |
|---|---|---|---|
| ARTHA-101 | FastAPI app skeleton + `slowapi` limiter | ✅ DONE | [gateway/app.py](arthaai/gateway/app.py) L24–26 |
| ARTHA-102 | `/analyze/{symbol}`, `/ohlcv/{symbol}`, `/health`, `/` (dashboard) endpoints | ✅ DONE | Read app.py in full, all 4 present |
| ARTHA-103 | Bearer-token + httpOnly-cookie dual auth | ✅ DONE | [gateway/auth.py](arthaai/gateway/auth.py) read in full — `require_principal` accepts either |
| ARTHA-104 | `dev_mode` production guard (secure cookies, refuse dev-token fallback) | ✅ DONE | Confirmed in both `config.py` and `app.py`/`auth.py` |
| ARTHA-105 | Web dashboard (candlestick chart, verdict/allocation display) | ✅ DONE | Served from `gateway/static/dashboard.html`, wired in app.py L44–68 |
| ARTHA-106 | Rate limiting on `/analyze` (10/min) | ✅ DONE | app.py L112–113 |
| ARTHA-107 | Real OAuth 2.1 / JWT validation against an IdP | ⬜ TO DO | Confirmed absent — `auth.py` L38–48: if `ARTHAAI_GATEWAY_TOKEN` is unset, **any non-empty bearer token is accepted** |
| ARTHA-108 | Token expiry / rotation | ⬜ TO DO | Confirmed absent — static string compare only |
| ARTHA-109 | Rate limiting on `/ohlcv`; per-token (not per-IP) limiting | ⬜ TO DO | Confirmed absent — only `/analyze` is decorated with `@limiter.limit`; `key_func=get_remote_address` |
| ARTHA-110 | mTLS termination | ⬜ TO DO | Correctly deferred to deploy infra per HLD |

**Tier 1: 6 done / 4 to do.**

---

## Epic ARTHA-2 — Tier 2: Intelligence Core

| ID | Summary | Status | Verified |
|---|---|---|---|
| ARTHA-201 | LangGraph `StateGraph` — fan-out/converge topology | ✅ DONE | [orchestration/graph.py](arthaai/orchestration/graph.py) read in full — matches HLD topology exactly |
| ARTHA-202 | `GraphState` TypedDict (the StateStore) | ✅ DONE | [orchestration/state.py](arthaai/orchestration/state.py) — 8 fields, matches every agent's read/write |
| ARTHA-203 | DB_Agent — SMA/RSI(Wilder)/ADX-14 + ADX-driven signal selector | ✅ DONE | [agents/db_agent.py](arthaai/agents/db_agent.py) read in full; live run confirmed ADX 30.2 → breakout path |
| ARTHA-204 | `indicators.py` — deterministic quant primitives (trend_signal, breakout_positions, wr_from_tallies, adx, rsi) | ✅ DONE | Read in full, 392 lines, all vectorized (O(n)) |
| ARTHA-205 | Quant_Agent — annualised μ/σ²/σ + signal-conditioned Kelly (W,R) | ✅ DONE | [agents/quant_agent.py](arthaai/agents/quant_agent.py) read in full; live run confirmed |
| ARTHA-206 | Alpha-Zoo factor registry — 445 factors (Alpha101 101, GTJA191 190, Qlib158 154) computed per-asset | ✅ DONE | Live-verified count via `registry.list()`; `quant_agent.run()` returns `factors`+`factor_signal` |
| ARTHA-207 | News_Agent — Qdrant hybrid search (hard ticker filter → semantic) | ✅ DONE | [agents/news_agent.py](arthaai/agents/news_agent.py) read in full |
| ARTHA-208 | Qdrant client — real `fastembed` embeddings w/ deterministic hash fallback | ✅ DONE | [db/qdrant.py](arthaai/db/qdrant.py) read in full |
| ARTHA-209 | TimescaleDB client — connection pool, upsert/load OHLCV, asset registry | ✅ DONE | [db/timescale.py](arthaai/db/timescale.py) read in full |
| ARTHA-210 | Alt_Agent — synthetic per-commodity stub, correct equity abstention | ✅ DONE | [agents/alt_agent.py](arthaai/agents/alt_agent.py) read in full — explicitly labeled STUB in its own docstring |
| ARTHA-211 | Master Reasoning LLM — provider chain (anthropic/gemini/local/offline) with per-provider circuit breaker | ✅ DONE | [agents/master_llm.py](arthaai/agents/master_llm.py) read in full; live-ran offline path |
| ARTHA-212 | Data ingest (yfinance) + Kafka producer (best-effort) | ✅ DONE | [data/ingest.py](arthaai/data/ingest.py) read in full |
| ARTHA-213 | Kafka/Redpanda consumer | ✅ DONE | [data/consumer.py](arthaai/data/consumer.py) read in full (requires optional `confluent-kafka`) |
| ARTHA-214 | **Wire `factor_signal` into signal-conditioned Kelly sizing** | 🔴 TO DO (P0) | See ARTHA-201/E2 above — blocking ticket |
| ARTHA-215 | Correlation Regime agent (risk-off fusion detection) | ⬜ TO DO | Confirmed **not started** — no file, no reference anywhere in `arthaai/agents/` |
| ARTHA-216 | Live news ingestion (RSS/API feeds) | ⬜ TO DO | `news_agent.py` only reads from Qdrant; seeding is a one-shot script (`data/seed_news.py`) with static articles, no scheduler |
| ARTHA-217 | Route the main pipeline through the resilient provider chain | ⬜ TO DO | See ARTHA-223 above |
| ARTHA-218 | Wire the new provider-tracking DB columns/functions | ⬜ TO DO | See ARTHA-225 above |
| ARTHA-219 | Cross-sectional factor ranking (registry currently evaluates one asset's last bar only, not a universe) | ⬜ TO DO | Confirmed by reading `quant_agent._evaluate_factors()` — single-asset, last-row only |
| ARTHA-220 | Additional indicators (MACD, Bollinger, ATR, OBV/VWAP) | ⬜ TO DO | Confirmed absent from `indicators.py`'s function list |
| ARTHA-221 | Fix stale docstring in `breakout_signal()` claiming it's "not yet wired into the live pipeline" | ⬜ TO DO (P3, doc only) | `indicators.py` L290–292 contradicts `db_agent.py` L37–39, which does call it when ADX≥25 |

**Tier 2: 13 done / 8 to do.**

---

## Epic ARTHA-3 — Tier 3: Oversight & Sizing

| ID | Summary | Status | Verified |
|---|---|---|---|
| ARTHA-301 | Discrete Kelly `f = W − (1−W)/R` | ✅ DONE | [asset_manager.py](arthaai/agents/asset_manager.py) L32–35, live-verified |
| ARTHA-302 | Continuous Kelly `f* = (μ−r)/σ²` (informational cross-check) | ✅ DONE | L38–41 |
| ARTHA-303 | Quarter-Kelly fractional scaling | ✅ DONE | L68, `s.kelly_fraction = 0.25` in config.py |
| ARTHA-304 | Hard 5% single-instrument policy cap (overrides model) | ✅ DONE | L70, `s.max_single_instrument = 0.05` |
| ARTHA-305 | No-edge / negative-edge → flat (no synthetic shorting) | ✅ DONE | L67 `raw = max(0.0, float(d_kelly))` |
| ARTHA-306 | Walk-forward backtest, look-ahead-safe | ✅ DONE | [backtest/engine.py](arthaai/backtest/engine.py) read in full; `fwd_ret.shift(-1)` construction confirmed safe |
| ARTHA-307 | `oos_slice()` 70/30 split + `arthaai promote` gate (Sharpe≥1.0, DD≤20%, beats B&H — all 3 required) | ✅ DONE | [backtest/promotion.py](arthaai/backtest/promotion.py) read in full; live-ran, output matches logic exactly |
| ARTHA-308 | Human Decision Gate | ⚠️ PARTIAL | HLD calls this "running," but the only "gate" is that nothing auto-connects to a broker — there is no explicit approval step, prompt, or audit trail in `cli.py execute`. Satisfied trivially, not by a dedicated feature. |
| ARTHA-309 | Portfolio-level Kelly (covariance-aware sizing across assets) | ⬜ TO DO | Confirmed absent — `asset_manager.size()` takes one asset's stats only |
| ARTHA-310 | VaR / Expected Shortfall | ⬜ TO DO | Confirmed absent anywhere in `arthaai/` |
| ARTHA-311 | Dynamic Kelly fraction by volatility regime | ⬜ TO DO | `kelly_fraction` is a static config constant |
| ARTHA-312 | Transaction cost model in backtest (commission/slippage/spread) | ⬜ TO DO | Confirmed absent in `backtest/engine.py` — `frac * rt` is frictionless |
| ARTHA-313 | Shadow Account Audit | ⬜ TO DO | Correctly deferred per HLD (needs a real manager's trade history) |
| ARTHA-215-gate | **The signal must actually pass `arthaai promote`** | 🔴 TO DO (P0) | Currently REJECTED — Sharpe 0.43 < 1.0 |

**Tier 3: 8 done / 5 to do (1 of the "done" items, ARTHA-308, is a thin pass).**

---

## Epic ARTHA-4 — Tier 4: Action

| ID | Summary | Status | Verified |
|---|---|---|---|
| ARTHA-401 | Position state machine (FLAT→PENDING_ENTRY→OPEN→EXITING→CLOSED) | ✅ DONE | [execution/state.py](arthaai/execution/state.py) read in full |
| ARTHA-402 | Portfolio equity-curve breaker (peak-to-trough, 10% trigger, 2-strike SYSTEM_LOCKED) | ✅ DONE | Same file, `_trip_breaker`/`_update_breaker` read in full |
| ARTHA-403 | `ExecutionEngine.submit()` — order creation from allocation, stop-loss price calc | ✅ DONE | [execution/engine.py](arthaai/execution/engine.py) read in full |
| ARTHA-404 | `arthaai execute` CLI — full pipeline → paper order, halt display, disclaimer | ✅ DONE | `cli.py` command present (not re-read line-by-line this pass, but `ExecutionEngine` import/usage confirmed via grep) |
| ARTHA-405 | Stop-loss/target trigger logic in `Position.step()` | ✅ DONE (unit-tested) | See ARTHA-408 correction above — real, but unreachable in production |
| ARTHA-406 | **Wire `.step()` into the backtest and/or a live bar loop so stops actually fire** | ⬜ TO DO (P1) | Confirmed zero call sites outside tests |
| ARTHA-407 | Kill switch (flatten all open positions on demand) | ⬜ TO DO | Confirmed absent — `grep kill_switch arthaai/execution/*.py` → 0 hits |
| ARTHA-408 | Audit log persistence (orders survive process restart) | ⬜ TO DO | Confirmed absent — `self.orders` is an in-memory list; `grep structlog\|audit arthaai/execution/*.py` → 0 hits |
| ARTHA-409 | Fill simulation (slippage, partial fills, rejection) | ⬜ TO DO | `Fill.slippage_bps` field exists but nothing ever sets it to a non-zero value |
| ARTHA-410 | Daily reset of the drawdown breaker (currently session-level via `_last_session_ts`, not calendar-day) | ⬜ TO DO | Confirmed by reading `_update_breaker()` — resets only on a date-string mismatch between consecutive marks, not a scheduled daily job |
| ARTHA-411 | Live broker adapter (IBKR/Alpaca) | ⬜ TO DO (deferred by Law 3) | Correctly not started — do not begin until ARTHA-214 + release gate close |
| ARTHA-412 | Script exporters (Pine/MQL5/TDX) | ⬜ TO DO (deferred) | Confirmed absent |

**Tier 4: 5 done / 7 to do.**

---

## Epic ARTHA-5 — Cross-Cutting

| ID | Summary | Status | Verified |
|---|---|---|---|
| ARTHA-501 | OPA policy enforcement on every agent tool call | ✅ DONE | `security/opa.py` + `policy/arthaai.rego` — read both, scopes match exactly, fail-safe fallback confirmed |
| ARTHA-502 | Circuit breakers on every external dependency | ✅ DONE | `resiliency/breaker.py` read in full; used by `master_llm.py`, `news_agent.py`, `opa.py`, `vault.py` |
| ARTHA-503 | Vault-backed secrets w/ env fallback | ✅ DONE | `security/vault.py` read in full |
| ARTHA-504 | Automated test suite | ✅ DONE | **113 passed** — ran it myself, not copied from a doc |
| ARTHA-505 | `python -m compileall` clean | ✅ DONE | Ran it myself — clean, exit 0 |
| ARTHA-506 | CI pipeline (GitHub Actions or similar) | ⬜ TO DO | `.github/` directory exists and is **completely empty** — confirmed via `find .github -type f` |
| ARTHA-507 | OpenTelemetry tracing | ⬜ TO DO | Confirmed absent anywhere in `arthaai/` |
| ARTHA-508 | Prometheus metrics | ⬜ TO DO | Confirmed absent |
| ARTHA-509 | CORS policy on the gateway | ⬜ TO DO | Confirmed absent from `gateway/app.py` — no `CORSMiddleware` |
| ARTHA-510 | Schema migration tool (see ARTHA-008) | ⬜ TO DO | Duplicate of ARTHA-008 — tracked here for cross-cutting visibility |

**Cross-cutting: 5 done / 5 to do.**

---

## Epic ARTHA-6 — ★ The Edge Criterion (SPEC.md §3 — the whole point of the system)

| ID | Requirement | Status | Verified |
|---|---|---|---|
| E1 | The factor engine computes factors | ✅ DONE | Live-verified: 445 factors load, `quant_agent.run('GLD')` returns `factor_signal=-9.778` |
| E2 | The factor signal drives sizing | ❌ TO DO — **blocking** | `grep` confirmed 0 references in `asset_manager.py` |
| E3 | The signal beats buy-and-hold OOS | ❌ TO DO — **blocking** | Live-verified: edge −32.34%, `arthaai promote` → REJECTED (Sharpe 0.43 < 1.0) |

**Acceptance for "★ done" (SPEC.md's own words):** E2 wired into signal-conditioned Kelly **and** E3 edge > 0 on out-of-sample data. Until both hold, the factor engine is infrastructure, not edge — this is the single ticket that gates everything in Tier 4 involving real money.

---

## 4. Release Gate (Definition of "Design Complete")

- [ ] ARTHA-214 / E2 — factor signal feeds Kelly sizing
- [ ] ARTHA-215-gate / E3 — `arthaai promote` passes (Sharpe ≥ 1.0, DD ≤ 20%, beats B&H) on two independent OOS windows
- [ ] ARTHA-224 — `signal_promotion` persists correctly (apply schema to the live DB)
- [ ] ARTHA-406 — stop-loss triggering wired into a real execution loop, not just tests
- [ ] ARTHA-107 — real OAuth 2.1 before any non-paper deployment

**Current state: 0 of 5 met.** All four tiers are wired end-to-end and 113 tests pass, but the system has not yet earned the right to size real money — correctly, by its own Law 3 design.
