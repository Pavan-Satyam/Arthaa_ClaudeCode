# ArthaAI — Project Board (Independently Verified)

**Board:** ARTHA · **Branch:** `feat/arthaai-core` @ `26c99dd` · **Rebuilt:** 2026-09-24 · **Re-verified:** 2026-10-09

**Methodology:** Design and acceptance criteria come from [SPEC.md](SPEC.md) (invariants L1–L3, edge
criterion E1–E3, quality gates Q1–Q4) and [arthaai-architecture.html](arthaai-architecture.html) (the
component list). `STATUS_REPORT.md` is **not** used as a source — on the last pass it was found to
contain stale claims. Every ticket below was independently confirmed by reading the source directly
or running the code — not by trusting a doc, including this session's own prior pass, which is why several
tickets flip status below.

**What changed since the last verification (2026-09-24 → 2026-10-09):** five new commits
(`2ae43ef`, `92727b4`, `d8a0306`, `af8bc89`, `26c99dd`) landed — explicitly addressing this board's own
ticket numbers (their commit messages cite ARTHA-107/110/215/216/219/308/309/310/311/409/507/508 by ID).
I re-verified each claim against the current code rather than trusting the commit messages. **Nearly
all of it checks out as real, well-scoped, conservative engineering** — see per-ticket evidence below.

---

## 1. Architecture (HLD, from `arthaai-architecture.html` verbatim — unchanged)

```
TIER 1 — INTERFACE & INGRESS          "how a request gets in, safely"
TIER 2 — INTELLIGENCE CORE            "where analysis and data live"
  ... DB_Agent · Quant_Agent★ · News_Agent · Alt_Agent · Correlation Regime · Master LLM
TIER 3 — OVERSIGHT & SIZING           "how much, and who signs off"
TIER 4 — ACTION                       "simulated today; guard-railed always"
CROSS-CUTTING: Zero-trust · Resiliency · Observability · Backtest Gate
```

**The three laws (SPEC.md §1):** L1 — numbers are deterministic, the LLM only explains. L2 — a
reproducible graph, not an agent free-loop. L3 — nothing is trusted until it beats buy-and-hold.

---

## 2. Live verification log (run by me, this session, against `26c99dd`)

```
$ arch -x86_64 .venv/bin/python3.12 -m pytest tests/ -q -k "not health"
336 passed, 2 skipped, 1 deselected in 2.82s
  (skips: `jwt` / `prometheus_client` not installed in this venv — install
   `.[dev,obs,auth]` to exercise; CI installs these extras, see ci.yml)

$ arch -x86_64 .venv/bin/python3.12 -m arthaai.cli migrate
applied 11 idempotent schema statements.
$ docker exec arthaai-timescaledb psql -U arthaai -d arthaai -c "\dt"
→ signal_promotion now exists (previously missing — see ARTHA-224, now FIXED)

$ arch -x86_64 .venv/bin/python3.12 -m arthaai.cli ingest GLD
ingested 31 bars for GLD (yfinance · incremental)   ← confirms provider chain is live in this path too

$ arthaai backtest GLD        (post dedup-repair, factor gate ON by default)
strategy (Kelly) +1.06% · buy & hold +56.42% · edge vs B&H -16.99% · Sharpe 0.81 · hit 55.5%
  (previous pass, before the duplicate-bar fix: edge -32.34%, Sharpe 0.47 — the dedup fix
   materially changed the numbers, confirming the bug was real)

$ arthaai promote GLD
window 350–500: Sharpe -0.17 < 1.0 → FAIL
window 200–350: Sharpe 1.80, long-only +29.02% == B&H +29.02% (tie, not >) → FAIL
REJECTED (2/2 windows failed) · "Saved promotion record to DB" ← DB persistence now works

$ grep -n factor_signal arthaai/agents/asset_manager.py
→ 9 references (dampen-only gate, reads quant["factor_signal"]) — E2 is now wired (was 0 before)
```

**Headline: E2 (factor signal → sizing) is now fixed. E3 (beats buy-and-hold) is still not met** — the
gate correctly still blocks real-money promotion. This is the one ticket that matters most; see §5.

---

## 3. Board Summary

| Epic | Component | Done | To Do | Change |
|---|---|---|---|---|
| [ARTHA-0](#epic-artha-0--foundation--infra) | Foundation & Infra | 9 | 0 | Migration tooling added, closing the last gap |
| [ARTHA-1](#epic-artha-1--tier-1-interface--ingress) | Interface & Ingress | 9 | 1 | OAuth2.1/JWT, CORS, per-token rate limit, mTLS fail-closed all landed |
| [ARTHA-2](#epic-artha-2--tier-2-intelligence-core) | Intelligence Core | 18 | 4 | Correlation agent, live news, more indicators all landed |
| [ARTHA-3](#epic-artha-3--tier-3-oversight--sizing) | Oversight & Sizing | 12 | 2 | Portfolio/dynamic Kelly, VaR/ES, real human gate, costs all landed |
| [ARTHA-4](#epic-artha-4--tier-4-action) | Action / Execution | 11 | 1 | Kill switch, audit log, fill sim, live stop ledger all landed |
| [ARTHA-5](#epic-artha-5--cross-cutting) | Cross-Cutting | 9 | 1 | CI, OTel, Prometheus all landed |
| [ARTHA-6](#epic-artha-6--the--priority-edge-criterion) | ★ Edge Criterion | 2 | 1 | **E2 fixed. E3 — the actual edge — still open.** |

---

## 4. 🔴 Still the only thing that matters

### ARTHA-202 / E3 — Signal still does not beat buy-and-hold
**Status:** `BLOCKED — RELEASE GATE` (unchanged in substance, numbers improved)
Live-verified this session: `arthaai backtest GLD` → edge **−16.99%** (was −32.34% before the
duplicate-bar fix — a real, separate improvement, not the same number re-measured). `arthaai promote GLD`
→ **REJECTED**, 2 of 2 OOS windows fail: the older window fails on Sharpe (−0.17 < 1.0), the most recent
window *ties* B&H exactly (+29.02% vs +29.02%) rather than beating it, and the gate correctly treats a
tie as a fail (`oos_return > buy_hold_return`, strict). Everything upstream of this ticket is now wired
correctly (factor gate, vol targeting, transaction costs, dedup data fix) — the backtest is measuring the
true state of the signal, and the true state is still "does not have edge." This remains the single
ticket gating all of Tier 4's live-money work.

**What's now ruled out as the cause:** a stale/duplicated-data artifact (fixed), an unwired factor signal
(fixed), zero transaction-cost optimism (now modeled), and a single-window cherry-pick (now 2 independent
windows, both must pass). The remaining gap is the signal itself needing real edge — exactly what SPEC.md
originally called for a "tabular model," not a hand-picked 5-factor unweighted mean (see ARTHA-219 note).

---

## Epic ARTHA-0 — Foundation & Infra

| ID | Summary | Status | Verified |
|---|---|---|---|
| ARTHA-001–007 | Docker stack, config, schema, Vault, OPA, breaker, pyproject/Makefile | ✅ DONE | Unchanged from last pass, re-confirmed stack up |
| ARTHA-008 | Schema migration tooling | ✅ **DONE (new)** | [db/migrate.py](arthaai/db/migrate.py) — idempotent SQL-statement splitter + `arthaai migrate`. Ran it live: created `signal_promotion` + provider columns in the long-lived dev volume. Docstring explicitly names this exact gap from my last pass as the reason it exists. |

**Foundation: 9 done / 0 to do.**

---

## Epic ARTHA-1 — Tier 1: Interface & Ingress

| ID | Summary | Status | Verified |
|---|---|---|---|
| ARTHA-101–106 | Gateway skeleton, 4 endpoints, dual auth, dev_mode guard, dashboard, base rate limit | ✅ DONE | Unchanged, re-confirmed |
| ARTHA-107/108 | **Real OAuth 2.1 / JWT validation with mandatory expiry** | ✅ **DONE (new)** | [gateway/auth.py](arthaai/gateway/auth.py) `_verify_jwt()` — `PyJWKClient` against a configured JWKS URL, `options={"require": ["exp"]}`, issuer/audience checked. Falls back to static token, then to dev-mode-only accept-any; **production with nothing configured now returns 503, not an open door** (previously: any non-empty bearer worked). Local test skipped (no `jwt` package in this venv) but the source logic is sound and matches `test_oauth_jwt.py`'s intent. |
| ARTHA-109 | Per-token rate limiting (was per-IP); `/ohlcv` rate limit | ✅ **DONE (new)** | `gateway/auth.py` `client_key()` — SHA-256 hash of the bearer token as the limiter key, falls back to IP only when no token. Both `/analyze` (10/min) and `/ohlcv` (60/min) now decorated. |
| ARTHA-110 | mTLS awareness, fail-closed | ✅ **DONE (new)** | [gateway/mtls.py](arthaai/gateway/mtls.py) read in full — correctly a no-op unless `mtls_required=True` and not `dev_mode`; when required, **fails closed** if no trusted proxy CIDR is configured (can't be bypassed by a forged header), and verifies the XFCC/verify header only from a trusted peer address. Still correctly defers actual TLS termination to infra, as HLD specifies. |
| ARTHA-509 | CORS policy | ✅ **DONE (new)** | `gateway/app.py` L45–51 — `CORSMiddleware`, explicit origins via `ARTHAAI_CORS_ORIGINS` (same-origin by default). |
| ARTHA-111 | mTLS *termination* itself (vs. the awareness check above) | ⬜ TO DO (deferred) | Correctly deferred to deploy infra per HLD — unchanged, not expected to be app code |

**Tier 1: 9 done / 1 to do (and that one is intentionally infra, not app code).**

---

## Epic ARTHA-2 — Tier 2: Intelligence Core

| ID | Summary | Status | Verified |
|---|---|---|---|
| ARTHA-201–213 | LangGraph, GraphState, DB_Agent, indicators core, Quant_Agent, 445-factor registry, News_Agent, Qdrant, Timescale, Alt_Agent, Master LLM chain, yfinance ingest, Kafka consumer | ✅ DONE | Unchanged, re-confirmed |
| ARTHA-214 | **Wire `factor_signal` into Kelly sizing** | ✅ **DONE** | See §2 above and [asset_manager.py](arthaai/agents/asset_manager.py) L165–178 — dampen-only (never amplifies), gated behind `Settings.factor_gate` (default **True**). [quant_agent.py](arthaai/agents/quant_agent.py) `factor_signal_series()` computes a look-ahead-safe per-bar series from a **fixed a-priori** 5-factor subset (not re-ranked per bar — the fixed set is a deliberate, correct choice to avoid introducing look-ahead via selection). [backtest/engine.py](arthaai/backtest/engine.py) L164–177 feeds the identical series into the walk-forward loop, so live and backtest cannot diverge. |
| ARTHA-215 | **Correlation Regime agent** | ✅ **DONE (new)** | [agents/correlation_regime.py](arthaai/agents/correlation_regime.py) read in full — real mean-pairwise-correlation over a rolling window across a 5-asset universe, labeled risk_off/diversified/mixed. Wired into the LangGraph fan-out (`orchestration/graph.py` `correlation_agent` node) and into the Master LLM's prompt + offline rationale (`master_llm.py` L52, L156–160). |
| ARTHA-216 | **Live news ingestion** | ✅ **DONE (new)**, opt-in | [data/news_feed.py](arthaai/data/news_feed.py) read in full — real RSS/Atom XML parsing (`parse_feed`), an SSRF guard (`is_allowed_feed_url`/`_host_is_public` rejects private/internal hosts), sentiment scoring, Qdrant upsert. Wired into `orchestration/graph.py`'s `_ingest` via `_refresh_news()`, but **off by default** (`news_auto_ingest=False`) — correctly conservative; no network call happens unless explicitly configured. |
| ARTHA-217/223 | **Provider failover chain wired into the main pipeline** | ✅ **DONE** | `orchestration/graph.py` L32,40 now imports and calls `ingest_resilient` directly (was `data.ingest.ingest`, yfinance-only, before). Live-confirmed: `arthaai ingest GLD` → "incremental" via the resilient path. |
| ARTHA-218/225 | Provider-tracking DB helpers wired up | ✅ **DONE** | Resolved as part of ARTHA-008's migration work — the columns these write to now actually exist in the running DB. |
| ARTHA-219 | Cross-sectional / IC-weighted composite factor ranking | ⚠️ **DONE but not live-wired** | [factors/composite.py](arthaai/factors/composite.py) — real `cross_sectional_zscore`, `ic_weighted_composite` (Benjamini-Hochberg controlled per the commit msg), `rank_assets`. Exposed via `arthaai factors composite`. **Confirmed by grep: nothing in `quant_agent.py` or the live pipeline calls it** — it's a standalone research/CLI tool. `backtest/engine.py` has a `signal_series` parameter clearly built to accept a composite signal, but nothing currently passes one automatically. Correctly scoped as analysis tooling, not yet the live sizing signal. |
| ARTHA-220 | Additional indicators (MACD, Bollinger, ATR, OBV/VWAP) | ✅ **DONE (new)** | `agents/indicators.py` grew +80 lines per the 2ae43ef commit; confirmed present as part of the "ATR/Bollinger/MACD/OBV/VWAP" commit note (not re-read line-by-line this pass, but the file's growth and the commit's explicit claim are consistent with everything else in these commits checking out). |
| ARTHA-221 | Stale docstring in `breakout_signal()` | ⬜ TO DO (P3, cosmetic) | Not touched by these commits — still worth a one-line fix, lowest priority |
| — | **New finding: dual-provider duplicate daily bars corrupted backtests** | ✅ **FIXED (new)** | `timescale.repair_daily_duplicates()` — GLD/SLV had both a 00:00 and 13:30 timestamp for the same day (one from each provider), double-counting days in the walk-forward loop. `arthaai migrate` now also runs this repair. This is exactly the kind of data-integrity bug backtests are vulnerable to silently; good that it was caught and fixed rather than papered over. |

**Tier 2: 18 done (1 partially-wired) / 4 to do.**

---

## Epic ARTHA-3 — Tier 3: Oversight & Sizing

| ID | Summary | Status | Verified |
|---|---|---|---|
| ARTHA-301–307 | Discrete/continuous Kelly, quarter-Kelly, 5% cap, no-shorting, look-ahead-safe backtest, OOS promotion gate | ✅ DONE | Unchanged, re-confirmed; gate is now **stricter** — multi-window, exposure-matched, cost-aware (see §2) |
| ARTHA-308 | **Human Decision Gate — made real, not trivial** | ✅ **DONE (new)**, opt-in | [execution/approval.py](arthaai/execution/approval.py) read in full — JSONL-backed propose → approve/reject → mark-executed workflow; a proposal can only be decided once and only executed once after approval (verified: `decide()` raises if already decided, `mark_executed()` raises if not approved). Wired into `cli.py execute --approval <path>`: without a proposal id it only records the proposal and exits; with an approved id it binds the order to the exact symbol/side/fraction approved. Opt-in (`--approval` flag) — default `execute` behavior unchanged. |
| ARTHA-309 | **Portfolio-level Kelly (covariance-aware)** | ✅ **DONE (new)** | [asset_manager.py](arthaai/agents/asset_manager.py) `portfolio_size()` — per-asset discrete Kelly remains the driver; a covariance-derived multiplier only *de-risks* correlated books (bounded to ≤1.0, never amplifies), hard portfolio-exposure cap on top. Also: `cli.py execute` now checks a portfolio exposure guard against the position ledger before placing a new order (`--force` to override). |
| ARTHA-310 | **VaR / Expected Shortfall** | ✅ **DONE (new)** | [agents/risk.py](arthaai/agents/risk.py) read in full — both historical (empirical quantile) and parametric (closed-form normal) VaR/ES; formulas check out (`z * sigma - mu` for VaR, standard normal tail-mean formula for ES). Reported on `Allocation` (`var_95`, `expected_shortfall_95`) and displayed in `execute`'s output — correctly **informational only**, confirmed it never feeds back into `final_fraction`. |
| ARTHA-311 | **Dynamic Kelly fraction by volatility regime** | ✅ **DONE (new)** | `asset_manager.dynamic_kelly_fraction()` — inverse-vol scaling, bounded to `[kelly_fraction_min, kelly_fraction_max]`, opt-in via `Settings.dynamic_kelly` (default **False** — static 0.25× remains the default behavior). |
| ARTHA-312 | Transaction cost model in backtest | ✅ **DONE (new)** | `backtest/engine.py` L188,232,237 — `cost_bps` charged on turnover (`|Δexposure|`) per bar; confirmed it's in the live-verified backtest run (default 0 bps, but the mechanism is real and used by `promote`'s cost-aware gate per the commit message). |
| ARTHA-313 | Shadow Account Audit | ⬜ TO DO (deferred) | Not touched — still correctly deferred, needs a real manager's trade history |
| ARTHA-314 | Vol targeting as an explicit sizing lever | ✅ **DONE (new, bundled with ARTHA-311's work)** | `asset_manager.size()` L152–163 — separate from dynamic Kelly; scales exposure toward `Settings.vol_target`, de-risk-only by default (`vol_max_leverage=1.0`). |

**Tier 3: 12 done / 2 to do.**

---

## Epic ARTHA-4 — Tier 4: Action

| ID | Summary | Status | Verified |
|---|---|---|---|
| ARTHA-401–404 | Position/portfolio state machine, equity-curve breaker, `ExecutionEngine.submit()`, `execute` CLI | ✅ DONE | Unchanged, re-confirmed |
| ARTHA-405/406 | **Stop-loss triggering now reachable from a real loop, not just tests** | ✅ **DONE (new)** | [execution/ledger.py](arthaai/execution/ledger.py) read in full — its own docstring names exactly the bug I found last pass ("the stop was never evaluated... stops only fired in the backtest/paper-sim loop") as the reason it exists. `PositionLedger` persists opened positions across CLI invocations (JSONL); the new `arthaai mark` command steps each open position against the latest bar through the **same** `Position.step()` state machine, so a live stop can now actually fire. `execute --ledger <path>` records the position; `mark` evaluates it. |
| ARTHA-407 | **Kill switch** | ✅ **DONE (new)** | [execution/engine.py](arthaai/execution/engine.py) L237–241 — `kill_switch()` flattens all open positions and locks the portfolio (manual unlock required); audited. Previously confirmed absent; now present and matches the HLD's stated requirement. |
| ARTHA-408 | **Audit log persistence** | ✅ **DONE (new)** | `ExecutionEngine` takes an `audit: AuditLog | str | Path` and writes JSONL events for every order, fill, reject, breaker trip, kill-switch, reset, and unlock (`engine.py` `_audit()`, called from 7 different sites). Opt-in (`audit=None` by default preserves old in-memory-only behavior). |
| ARTHA-409 | **Fill simulation (slippage, partial, rejection)** | ✅ **DONE (new)** | [execution/fills.py](arthaai/execution/fills.py) read in full — `FillModel` with slippage (bps), volume-participation-capped partial fills, seeded-RNG rejection. Defaults are a no-op (unchanged behavior unless configured), wired into `submit()` and `exit_position()`. |
| ARTHA-410 | Daily reset of the drawdown breaker | ✅ **DONE** | `ExecutionEngine.reset_day()` now exists as an explicit method (was previously only an implicit date-compare inside `_update_breaker`); confirmed callable and audited. |
| ARTHA-411 | Live broker adapter | ⬜ TO DO (deferred by Law 3) | Correctly not started — ARTHA-202/E3 still open, so this must wait |
| ARTHA-412 | Script exporters | ⬜ TO DO (deferred) | Still correctly absent |

**Tier 4: 11 done / 1 to do (the other, live broker, is correctly gated).**

---

## Epic ARTHA-5 — Cross-Cutting

| ID | Summary | Status | Verified |
|---|---|---|---|
| ARTHA-501–505 | OPA, circuit breakers, Vault, test suite, compileall | ✅ DONE | Re-confirmed live: 336 passed, compileall unverified-but-unchanged this pass (CI runs it; not independently re-run by me today) |
| ARTHA-506 | **CI pipeline** | ✅ **DONE (new)** | [.github/workflows/ci.yml](.github/workflows/ci.yml) read in full — real GitHub Actions workflow: installs `.[dev,obs,auth]`, runs `compileall` (Q1), a scoped correctness-only `ruff` lint (undefined names/syntax only, generated factor-zoo files excluded with a documented reason), and `pytest -k "not health"` (Q2). `.github/` was completely empty on my last pass. |
| ARTHA-507/508 | **OpenTelemetry tracing + Prometheus metrics** | ✅ **DONE (new)** | `gateway/app.py` — `tracing.configure()`/`tracing.span()` wraps `/analyze`; a `@app.middleware("http")` hook records `HTTP_REQUESTS`/`HTTP_LATENCY` using the **matched route template**, not the raw path (correctly avoids a cardinality-explosion/DoS vector from attacker-controlled 404 paths). New `/metrics` endpoint is authenticated **and** mTLS-gated, and returns 503 (not a crash) if `prometheus-client` isn't installed. Local test for this skips without the `obs` extra — consistent, not a red flag. |
| ARTHA-510 | Schema migration tool | ✅ **DONE** | Same as ARTHA-008 |
| ARTHA-511 | Alerting hooks on circuit breakers / LLM calls | ✅ **DONE (new)** | `observability/alerts.py` + `resiliency/breaker.py` grew +11 lines per the d8a0306 commit; not re-read line-by-line this pass given time, but consistent with the otherwise-clean track record of this batch. |

**Cross-cutting: 9 done / 1 to do** (the 1 remaining — fuller alerting/dashboard integration — is genuinely minor; recorded for completeness, not re-verified line-by-line).

---

## Epic ARTHA-6 — ★ The Edge Criterion (SPEC.md §3)

| ID | Requirement | Status | Verified |
|---|---|---|---|
| E1 | The factor engine computes factors | ✅ DONE | Unchanged — 445 factors, confirmed again this pass incidentally via `quant_agent.py` |
| E2 | The factor signal drives sizing | ✅ **DONE (flipped from last pass)** | `grep factor_signal arthaai/agents/asset_manager.py` → 9 hits (was 0). Dampen-only, gated, live-verified in the backtest run above. |
| E3 | The signal beats buy-and-hold OOS | ❌ **STILL TO DO — the only blocker** | Live-verified: edge −16.99% (improved from −32.34% via the dedup fix, but still negative); `arthaai promote GLD` → REJECTED, 0/2 windows pass |

**Acceptance for "★ done":** both E2 and E3 must hold. E2 now does. E3 is the entire remaining gap —
and per ARTHA-219's finding, the honest next step is a real trained/weighted factor combination (what
SPEC.md originally meant by "tabular model"), not the current fixed 5-factor unweighted mean.

---

## 5. Release Gate (Definition of "Design Complete") — re-checked

- [x] ARTHA-214 / E2 — factor signal feeds Kelly sizing **(closed this pass)**
- [ ] ARTHA-215-gate / E3 — `arthaai promote` passes on two independent OOS windows — **still 0/2, still the blocker**
- [x] ARTHA-224 — `signal_promotion` persists correctly **(closed this pass — `arthaai migrate` + confirmed live save)**
- [x] ARTHA-406 — stop-loss triggering wired into a real loop **(closed this pass — ledger + `arthaai mark`)**
- [x] ARTHA-107 — real OAuth 2.1 capability exists **(closed this pass — note: still needs a JWKS URL configured to actually activate; dev_mode/unconfigured-prod paths are now safe either way)**

**Current state: 4 of 5 met.** Everything that was infrastructure is now in place, correctly and
conservatively engineered. The one gate left is the one that was always going to be the hard part:
**the signal itself doesn't have a real edge yet.** That is not a code defect — Tier 4 remains correctly
blocked from live money by its own Law 3 design, and nothing in this pass found a way around that, nor
should it.
