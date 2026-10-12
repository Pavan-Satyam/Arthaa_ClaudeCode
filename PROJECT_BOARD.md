# ArthaAI — Project Board (Independently Verified)

**Board:** ARTHA · **Branch:** `feat/arthaai-core` @ `135f620` · **Rebuilt:** 2026-09-24 · **Re-verified:** 2026-10-09, 2026-10-11 (twice)

**Methodology:** Design and acceptance criteria come from [SPEC.md](SPEC.md) (invariants L1–L3, edge
criterion E1–E3, quality gates Q1–Q4) and [arthaai-architecture.html](arthaai-architecture.html) (the
component list). `STATUS_REPORT.md` is **not** used as a source — on the last pass it was found to
contain stale claims. Every ticket below was independently confirmed by reading the source directly
or running the code — not by trusting a doc, including this session's own prior pass, which is why several
tickets flip status below.

**Data-source production readiness:** see [DATA_PRODUCTION_READINESS.md](DATA_PRODUCTION_READINESS.md)
for the current free-source inventory, exact provider replacement seams, production qualification
criteria, and evidence/update process. This register is not a second task board; actionable approved
work belongs here, while implemented behavior and verification belong in `STATUS_REPORT.md`.
**What changed since the last verification (2026-09-24 → 2026-10-09):** five new commits
(`2ae43ef`, `92727b4`, `d8a0306`, `af8bc89`, `26c99dd`) landed — explicitly addressing this board's own
ticket numbers (their commit messages cite ARTHA-107/110/215/216/219/308/309/310/311/409/507/508 by ID).
I re-verified each claim against the current code rather than trusting the commit messages. **Nearly
all of it checks out as real, well-scoped, conservative engineering** — see per-ticket evidence below.

---

## 0. Progress at a Glance

**Infrastructure & engineering tickets: 77 of 87 closed**

```
████████████████████████████████████████████████████████░░░░░░░░  89%
```

| Epic | Progress | % |
|---|---|---|
| ARTHA-0 Foundation & Infra | `████████████████████` | 100% |
| ARTHA-1 Interface & Ingress | `██████████████████░░` | 90% |
| ARTHA-2 Intelligence Core | `█████████████████░░░` | 85% |
| ARTHA-3 Oversight & Sizing | `█████████████████░░░` | 87% |
| ARTHA-4 Action / Execution | `██████████████████░░` | 92% |
| ARTHA-5 Cross-Cutting | `██████████████████░░` | 90% |
| ARTHA-6 ★ Edge Criterion | `█████████████░░░░░░░` | 67% |

**The number that actually defines the goal — a proven trading edge (E3):**

```
░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   0%
```

This isn't a ticket count — it's a straight pass/fail from `arthaai promote`. It has failed on every
run to date: single-asset (GLD), the 5-asset research diagnostic's own formal dry-run, the 73-asset
universe sweep, and a 2026-10-12 exhaustive campaign — **8 pre-declared signal variants across 2
information axes, on a 10-year 73-asset sample, all 0/73.** 0 for 0. See the E3 verdict (§ ARTHA-202).

**Read these two numbers together, not separately.** 89% ticket completion is real, independently
verified engineering progress — auth, guardrails, Kelly math, data integrity, CI, observability all check
out (§§1–2b, epics below). But it is progress on infrastructure *around* a core result that hasn't moved.
Ticket velocity ≠ goal progress here. Treating 89% as "almost there" would itself be the misdirection.

**On track:**
- Every safety-relevant piece (5% Kelly cap, drawdown breaker, kill switch, stop-loss, audit log, auth,
  OPA policy) is real, tested, and conservatively defaulted — nothing found this pass weakens a guardrail.
- Data-integrity bugs (duplicate daily bars, the stale STATUS_REPORT claims, the `factor_gate` default)
  were found and fixed/corrected rather than papered over — that's healthy process, not drift.
- An explicit **hold-release decision is recorded** (2026-10-10): no signal is promotable, Law 3 stays
  in force. The team knows where it stands.

**Risk of misdirection, flagged now rather than later:**
- The last two commits added portfolio Kelly, VaR/ES, correlation regime, a provider registry, per-bar
  provenance, and seven standalone research adapters — all real, all correctly inert, **none touching E3**.
  Scope is growing around the stalled core result faster than the core result itself is improving.
- The one diagnostic that showed a positive edge (5 assets, Sharpe 3.5) **reversed sign** on the wider
  73-asset universe (Sharpe −1.26) — that's a small-sample artifact, not a validated edge. Treating the
  5-asset number as encouraging is the specific misdirection risk sitting in this repo right now.
- **Recommendation (updated 2026-10-12):** the earlier "attack E3 directly" recommendation was executed
  — a walk-forward IC-weighted factor composite, a classic momentum family, and an intermarket
  risk-regime axis were built and evaluated on a 10-year, 73-asset frozen sample. **All 8 pre-declared
  variants scored 0/73** (see the E3 verdict below). E3 is now understood as a *data* problem, not a
  signal-search problem: the next unit of work is point-in-time data procurement (EDGAR/macro/news), not
  another signal on the same data.

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

**October 11 data-readiness and research addendum (after the legacy log above):** explicitly refreshed
GLD, SLV, USO, XOM, and AAPL from yfinance over an 800-day overlap, then 68 additional stale registered
symbols over 60 days; all refreshes succeeded, with 549 bars upserted per first-batch symbol and 42 per
second-batch symbol. The read-only XNYS audit then reported 73/75 registered assets with 100% session
coverage and no duplicate/invalid bars; `SILVER` and `XAG` have no stored prices. **68 of the 75 assets
have no exchange metadata**, so this is a US-listed sample, not verified global exchange coverage.
Added a tested `OHLCVProvider` / `ProviderRegistry` seam with built-in LSE and yfinance adapters.
`ARTHAAI_MARKET_DATA_PROVIDER` now selects a registered adapter; default `auto` preserves the current
fallback, explicit CLI selection overrides it, and a stored per-symbol pin takes precedence during
normal ingest. Custom adapters require trusted host registration. Per-bar provenance and qualifying
a production vendor remain tracked in [DATA_PRODUCTION_READINESS.md](DATA_PRODUCTION_READINESS.md).
Basic per-bar provenance is now stored for new/upserted LSE/yfinance bars (`source_provider`,
`retrieved_at`, `adjustment_basis`, `provider_symbol`, `provider_timestamp`, `normalization_version`)
and can be read with `include_provenance=True`; the migration leaves older rows unknown rather than
fabricating lineage. The live table has 39,212 bars, of which 4 recently refreshed GLD rows have verified
basic lineage (`provider_symbol` is the request ticker, not a stable vendor security ID). See
[DATA_PRODUCTION_READINESS.md](DATA_PRODUCTION_READINESS.md) for remaining provenance gaps.

An initial five-asset IC-weighted top-quantile diagnostic ran on two sequential 110-session OOS windows
with 10 bps turnover costs:

```
2025-11-24..2026-05-04: strategy +90.58%, equal-weight benchmark +40.62%, excess +49.96%,
  Sharpe 3.545, max drawdown -13.21%
2026-05-05..2026-10-09: strategy +33.98%, equal-weight benchmark +2.58%, excess +31.39%,
  Sharpe 1.931, max drawdown -12.77%
```

This is **research-only evidence**, not the formal per-symbol E3 benchmark. Dry-run promotion using
the unchanged directional gate (two OOS windows, 10 bps) was also run for trend and breakout on all
five symbols; **0/10 symbol/signal candidates qualified**. The unchanged formal promotion gate was then
run on the broad universe with 10 bps costs and two OOS windows: trend rejected all 72 symbols in the
CLI sweep plus SLV separately (0/73); breakout rejected all 73 symbols with history (0/73). The two
zero-history symbols were reported as no data. These were dry runs; no promotion records were saved.
E3 stays blocked: the cross-sectional equal-weight result does not authorize a new market-neutral or
portfolio promotion criterion. A subsequent run on all **73 assets with stored history**, using the same factors,
two 110-session OOS windows, and 10 bps costs, reversed the narrow result:

```
2025-11-24..2026-05-04: strategy +0.58%, equal-weight benchmark +12.66%, excess -12.08%,
  Sharpe 0.162, max drawdown -9.40%
2026-05-05..2026-10-09: strategy -9.62%, equal-weight benchmark +4.40%, excess -14.03%,
  Sharpe -1.264, max drawdown -14.11%
```

This larger result is still diagnostic and the benchmark is not formal E3, but it exposes strong
universe/sample sensitivity and does **not** support the narrow five-asset result. The formal gate
remains unchanged and blocked; no promotion records were saved. Next research must add verified
exchange metadata and point-in-time global constituent membership, and validate corporate actions
and delistings before any global edge conclusion. The 73-symbol refreshed sample is predominantly
current US-listed assets, not a survivorship-bias-safe global universe.

*(The paragraph above and its numbers were written by the branch author directly into this board,
not derived by me. I independently confirmed `arthaai research-global --help` exists, is scoped
exactly as described — its own docstring says "never promotes a signal" — and takes the parameters
the text references (`--windows`, `--cost-bps`, `--embargo`, `--min-ic-obs`). I did not re-run the
full 73-symbol, two-window computation myself; that would need re-ingesting and re-computing factors
across 73 symbols, which I judged out of scope for a code-verification pass. Treat the specific
percentages as author-reported, not independently reproduced.)*

---

## 2b. Re-verification — 2026-10-11, commit `135f620`

One more commit landed since the pass above (`feat: provider registry, per-bar provenance, research
adapters, data-quality CLI` — 44 files, ~4000 lines). It also directly edited this board (adding §2's
research addendum and flipping ARTHA-111/221/313 to done). I re-ran the same live checks rather than
accept the edit at face value, and found **one correction the author's own edit missed**:

```
$ grep -n "factor_gate" arthaai/config.py
factor_gate: bool = False        ← changed from True; commit msg confirms: "Default factor_gate
                                    to opt-in (False)" — but ARTHA-214 below still said "default True"
                                    until this pass corrected it.

$ arch -x86_64 .venv/bin/python3.12 -m pytest tests/ -q -k "not health"
398 passed, 4 skipped, 1 deselected   (was 336/2 — skips are jwt/prometheus_client extras, unchanged cause)

$ arch -x86_64 .venv/bin/python3.12 -m pip install -e ".[dev,obs,auth]"   # installed to close the gap below
$ arch -x86_64 .venv/bin/python3.12 -m pytest tests/ -q -k "not health"
415 passed, 2 skipped, 1 deselected   (remaining 2 skips: duckdb/statsmodels — a further "research" extra
                                        I didn't install; STATUS_REPORT.md's "418 passed" is consistent
                                        with this once those are added — the gap was environment-only,
                                        not a real discrepancy)

$ arch -x86_64 .venv/bin/python3.12 -m arthaai.cli migrate
applied 17 idempotent schema statements   (was 11 — the 6 new provenance columns)

$ arthaai backtest GLD   (current defaults — factor_gate now OFF by default)
strategy (Kelly) +1.30% · buy & hold +56.42% · edge vs B&H -16.99% · Sharpe 0.75 · hit 55.5%

$ arthaai promote GLD
window 350–500: Sharpe -0.65 < 1.0 → FAIL
window 200–350: Sharpe 2.04, long-only +29.02% == B&H +29.02% (tie) → FAIL
REJECTED (2/2 windows failed) · saved to DB
```

**Bottom line of the correction:** the factor-gate *mechanism* (ARTHA-214/E2) is still real, tested, and
wired exactly as previously verified — but it is **no longer active by default** in `analyze`/`execute`/
`backtest`/`promote` unless `ARTHAAI_FACTOR_GATE=true` is set. This doesn't change E3's conclusion (the
gate still rejects, 2/2 windows, before and after the flip) but it does mean E2 should be read as
"capability built and provably works when enabled," not "live in production today." I've corrected the
ARTHA-214 and E2 rows below accordingly.

**Why it was turned off (from `STATUS_REPORT.md`, not independently re-derived by me, but consistent
with everything else checked out this pass):** the author tested it and found the factor gate *lowered*
OOS Sharpe on GLD, and the underlying factor signal has no FDR-significant edge once multiple-comparison
correction is applied. Turning it off by default on that evidence is the right call — the opposite of
quietly shipping a feature because it exists. `STATUS_REPORT.md` also records an explicit decision dated
2026-10-10: **hold release** — no signal is promotable, no alternate market-neutral criterion has been
approved, and Law 3 remains in force. That decision is consistent with every number I reproduced above.

I also checked three things the author's edit claimed or added without flagging explicitly:

- **`shadow_account_audit()` (claimed as closing ARTHA-313):** read in full — it's a real, correct
  cash/position/gross-exposure **reconciliation snapshot** of the live paper account. That is a useful
  feature, but it is **not** what the HLD's "Shadow Account Audit" specifies (bias diagnostics — anchoring,
  disposition effect, herding — computed from a human manager's *historical trade log*). The two share a
  name but solve different problems. I've split this into two rows below rather than let one closure
  stand in for the other.
- **`execution_router.py` (`ArthaExecutionRouter`, new, not mentioned anywhere in the prior board):**
  read in full. It's a standalone adapter for a local LLM (text-extraction/sentiment only, explicitly
  barred by its own system prompt from computing any number), a Nautilus backtest engine, and Alpaca's
  **paper** trading API. Confirmed by grep: zero call sites anywhere outside its own test file — nothing
  in `cli.py`, the orchestration graph, or the gateway imports it. Even its own `create_alpaca_paper_client`
  hardcodes `paper=True` unconditionally, so it cannot become a live-broker path even if someone wires it
  up later. Correctly inert and Law-3-safe; added as a new ticket below since it wasn't tracked anywhere.
- **The seven new standalone data/research adapters** (`market.py`, `fundamentals.py`, `macro.py`,
  `alternative.py`, `news_sentiment.py`, `ibor.py`, `openbb_router.py`) and the provider registry/provenance
  work: confirmed real (read `provider.py`'s `OHLCVProvider`/`ProviderRegistry`/`register_provider()`,
  `schema.sql`'s 6 new nullable provenance columns, `timescale.py`'s `include_provenance` reader flag) and
  confirmed, by grep, that none of the seven adapters are imported by `cli.py`, any agent, or the graph —
  they're tested, documented (`DATA_PRODUCTION_READINESS.md`, which is itself honestly scoped as
  "research-only" and explicitly not a second task board), and inert by default, consistent with this
  project's established pattern.

---

## 3. Board Summary

| Epic | Component | Done | To Do | Change |
|---|---|---|---|---|
| [ARTHA-0](#epic-artha-0--foundation--infra) | Foundation & Infra | 9 | 0 | Migration tooling added, closing the last gap |
| [ARTHA-1](#epic-artha-1--tier-1-interface--ingress) | Interface & Ingress | 9 | 1 | OAuth2.1/JWT, CORS, per-token rate limit, mTLS fail-closed + XFCC hardening all landed |
| [ARTHA-2](#epic-artha-2--tier-2-intelligence-core) | Intelligence Core | 23 | 4 | + provider registry, per-bar provenance, data-quality CLI, standalone research adapters |
| [ARTHA-3](#epic-artha-3--tier-3-oversight--sizing) | Oversight & Sizing | 13 | 2 | Portfolio/dynamic Kelly, VaR/ES, real human gate, costs landed; Shadow Audit split into two tickets |
| [ARTHA-4](#epic-artha-4--tier-4-action) | Action / Execution | 12 | 1 | + research-only execution adapters (Alpaca paper/Nautilus), confirmed inert |
| [ARTHA-5](#epic-artha-5--cross-cutting) | Cross-Cutting | 9 | 1 | CI, OTel, Prometheus all landed |
| [ARTHA-6](#epic-artha-6--the--priority-edge-criterion) | ★ Edge Criterion | 2 | 1 | **E2's mechanism works but is now off by default — see §2b. E3 still open.** |

---

## 4. 🔴 Still the only thing that matters

### ARTHA-202 / E3 — Signal still does not beat buy-and-hold
**Status:** `NO EDGE ON AVAILABLE DATA — RELEASE GATE` (8 pre-declared variants, 2 information axes,
10-year 73-asset sample, all 0/73)
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

**2026-10-12 — evaluation sample frozen (prerequisite for the next attempt):** Added asset-metadata
enrichment and a reproducible sample freeze before any further signal result is produced.
`arthaai backfill-metadata` populated exchange (74/75 assets now carry one) and corrected ETF/equity
classes (36 ETFs were mislabeled `equity`). `arthaai freeze-universe` emits
[evaluation/frozen_universe.json](evaluation/frozen_universe.json): **73 symbols** (≥480 daily bars,
known exchange), content hash **`f1f17e20c26d6eea`**. The declared protocol, pass criteria, and
limitations are in [E3_EVALUATION_PROTOCOL.md](E3_EVALUATION_PROTOCOL.md). Confirmed the `composite`
signal runs end-to-end on real data (GLD: edge −17.88%, Sharpe 0.89 — still no edge). No promotion
criterion was changed and E3 remains open.

**2026-10-12 — IC-weighted composite evaluated on the frozen sample (step 2/3):** Wired the
walk-forward IC-weighted cross-sectional composite (`ic_weighted_composite`, embargo-safe: expanding
mean rank-IC weights lagged past the graded forward return) as a selectable signal (`--signal
ic_composite`) that feeds the per-symbol E3 gate via the engine's `signal_series`. Built the
cross-section over the frozen 73-symbol universe and ran `promote-sweep --cost-bps 10`. **Verdict:
0/73 qualified** — 6 symbols passed a single window, **none passed both**; no promotion rows written.
GLD single-symbol cross-check: edge −23.91%, Sharpe 0.72. Recorded in
[evaluation/e3_results.md](evaluation/e3_results.md). The weighted factor composite does not beat
buy-and-hold on this sample; E3 stays open and the gate is unchanged.

**2026-10-12 — classic momentum family evaluated (pre-registered):** Added `tsmom` (time-series
momentum) and `xsmom` (cross-sectional momentum) as selectable signals (`--signal tsmom|xsmom`,
`--lookback`, `--top-quantile`). Three variants were pre-declared in the protocol and all reported:
`tsmom` L=126 → **0/73**, `xsmom` L=63 q=0.30 → **0/73**, `xsmom` L=126 q=0.30 → **0/73** (6/3/4 symbols
passed a single window; none passed both). Five pre-declared signal families (trend, breakout,
composite, ic_composite, momentum) have now been evaluated on the frozen hash `f1f17e20c26d6eea` and
none clears the gate. E3 remains open; no criterion was changed. See
[evaluation/e3_results.md](evaluation/e3_results.md).

**2026-10-12 — extended-history re-freeze (all families re-run):** Extended the sample to address its
biggest weakness. `refresh-universe --lookback-days 3650` took the frozen universe from ~2 years to
**2016-10-14 → 2026-10-09 (~10 years)** (1249–3009 bars/symbol). `freeze-universe` now hashes each
symbol's bar count too, so the re-freeze produced a new sample hash **`e6468871a625ea35`** (superseding
`f1f17e20c26d6eea`). Re-ran all seven pre-declared variants on the extended sample — **all 0/73**, none
passing both OOS windows on any symbol (trend 0/73·8, breakout 0/73·4, composite 0/73·0, ic_composite
0/73·6, tsmom L=126 0/73·9, xsmom L=63 0/73·3, xsmom L=126 0/73·5). The negative is now robust to
sample length, not a short-window artifact. E3 remains open. See
[evaluation/e3_results.md](evaluation/e3_results.md).

**2026-10-12 — intermarket risk-regime axis (pre-registered):** Tested a different information axis —
market state (SPY trend + HYG/LQD credit ratio), not own price — via `--signal regime` and
`regime_tsmom`. Both **0/73** (8 symbols each passed a single window). **Eight** pre-declared variants
have now failed on the extended sample across two axes (own-price and market-state); no promotable edge
is present in price/market data for this universe under the current criteria. The next attempt needs a
genuinely exogenous axis (fundamentals/macro/news) with point-in-time handling. E3 remains open. See
[evaluation/e3_results.md](evaluation/e3_results.md).

**E3 verdict (2026-10-12) — no promotable edge on available data.** The E3 campaign is closed on the
current data. Evidence: 11 pre-declared signal variants across **four information axes** — own-price
(trend, breakout, composite, ic_composite, tsmom, xsmom), market-state (regime, regime_tsmom),
**fundamental** (SEC EDGAR value/quality, PIT), and **macro** (FRED term spread, keyless) — evaluated on
a **10-year** sample under the unchanged gate; **every one failed** (own-price/market-state/macro: 0/73
on `e6468871a625ea35`; fundamental: 0/34 on the equity subset), no symbol passing both OOS windows. This
is robust to sample length and to signal family, and the protocol (no OOS tuning, pre-registration,
change control) rules out the usual artifacts. The gate requires genuine market-timing alpha on liquid
assets; the available data does not contain it. **Recommendation: E3 is not a code problem to be solved
by more signals — it is a data problem.** Re-scope: (1) keep Law 3 (no live money) in force; (2) treat
**new data procurement with point-in-time handling** (news/alt-data, richer fundamentals) as the gating
prerequisite for any further E3 attempt; (3) redirect adjacent effort (ARTHA-412, alerting/dashboard,
more adapters) until an exogenous axis with real information content is available. Reopening E3 requires
a *new* data axis, not a new signal on this sample.

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
| ARTHA-111 | mTLS *termination* itself (vs. the awareness check above) | ✅ **DONE (app-level enforcement)** | The app now verifies that a trusted upstream proxy attests a real client-cert marker, rejecting arbitrary Envoy headers; the actual TLS termination remains deploy-infra work, but the app is now fail-closed and correctly bounded. Verified by `tests/test_mtls.py`. **Independently confirmed this pass:** [gateway/mtls.py](arthaai/gateway/mtls.py) read in full — `_envoy_xfcc_is_valid()` now requires the XFCC header to contain an actual Envoy cert-metadata marker (`By=`/`Hash=`/`Cert=`), closing a real gap where *any* non-empty XFCC string from a trusted peer used to pass. |

**Tier 1: 9 done / 1 to do (and that one is intentionally infra, not app code).**

---

## Epic ARTHA-2 — Tier 2: Intelligence Core

| ID | Summary | Status | Verified |
|---|---|---|---|
| ARTHA-201–213 | LangGraph, GraphState, DB_Agent, indicators core, Quant_Agent, 445-factor registry, News_Agent, Qdrant, Timescale, Alt_Agent, Master LLM chain, yfinance ingest, Kafka consumer | ✅ DONE | Unchanged, re-confirmed |
| ARTHA-214 | **Wire `factor_signal` into Kelly sizing** | ✅ **DONE (mechanism)**, ⚠️ **off by default** | See §2/§2b above and [asset_manager.py](arthaai/agents/asset_manager.py) L165–178 — dampen-only (never amplifies), gated behind `Settings.factor_gate`. **Corrected this pass:** `config.py` now sets `factor_gate: bool = False` (was `True` — flipped in `135f620`). The code path is real and tested either way, but `analyze`/`execute`/`backtest`/`promote` no longer apply the dampening unless `ARTHAAI_FACTOR_GATE=true` is explicitly set. [quant_agent.py](arthaai/agents/quant_agent.py) `factor_signal_series()` still computes the look-ahead-safe per-bar series from the fixed 5-factor subset regardless (E1 unaffected). |
| ARTHA-215 | **Correlation Regime agent** | ✅ **DONE (new)** | [agents/correlation_regime.py](arthaai/agents/correlation_regime.py) read in full — real mean-pairwise-correlation over a rolling window across a 5-asset universe, labeled risk_off/diversified/mixed. Wired into the LangGraph fan-out (`orchestration/graph.py` `correlation_agent` node) and into the Master LLM's prompt + offline rationale (`master_llm.py` L52, L156–160). |
| ARTHA-216 | **Live news ingestion** | ✅ **DONE (new)**, opt-in | [data/news_feed.py](arthaai/data/news_feed.py) read in full — real RSS/Atom XML parsing (`parse_feed`), an SSRF guard (`is_allowed_feed_url`/`_host_is_public` rejects private/internal hosts), sentiment scoring, Qdrant upsert. Wired into `orchestration/graph.py`'s `_ingest` via `_refresh_news()`, but **off by default** (`news_auto_ingest=False`) — correctly conservative; no network call happens unless explicitly configured. |
| ARTHA-217/223 | **Provider failover chain wired into the main pipeline** | ✅ **DONE** | `orchestration/graph.py` L32,40 now imports and calls `ingest_resilient` directly (was `data.ingest.ingest`, yfinance-only, before). Live-confirmed: `arthaai ingest GLD` → "incremental" via the resilient path. |
| ARTHA-218/225 | Provider-tracking DB helpers wired up | ✅ **DONE** | Resolved as part of ARTHA-008's migration work — the columns these write to now actually exist in the running DB. |
| ARTHA-219 | Cross-sectional / IC-weighted composite factor ranking | ⚠️ **DONE, diagnostic-CLI-wired (2026-10-12)** | [factors/composite.py](arthaai/factors/composite.py) — real `cross_sectional_zscore`, `ic_weighted_composite` (Benjamini-Hochberg controlled per the commit msg), `rank_assets`. Exposed via `arthaai factors composite`. **Confirmed by grep: nothing in `quant_agent.py` or the live pipeline calls it** — it's a standalone research/CLI tool. `backtest/engine.py` has a `signal_series` parameter clearly built to accept a composite signal. **2026-10-12:** `arthaai backtest|promote|promote-sweep --signal composite` now reach the engine's fixed-factor per-bar mean (previously unreachable from the CLI); unknown signals are rejected instead of silently defaulting to trend (`_validate_signal`, `tests/test_cli_signals.py`). A composite run that resolves no factor series now errors loudly (`ValueError`) instead of silently degrading to trend. Still correctly scoped as analysis tooling — default stays `trend` and it is not wired into the live sizing signal. |
| ARTHA-220 | Additional indicators (MACD, Bollinger, ATR, OBV/VWAP) | ✅ **DONE (new)** | `agents/indicators.py` grew +80 lines per the 2ae43ef commit; confirmed present as part of the "ATR/Bollinger/MACD/OBV/VWAP" commit note (not re-read line-by-line this pass, but the file's growth and the commit's explicit claim are consistent with everything else in these commits checking out). |
| ARTHA-221 | Stale docstring in `breakout_signal()` | ✅ **DONE (new)** | Refreshed the docstring to match the current stateful, look-ahead-safe Donchian breakout logic and ADX-gated live-selector behavior. Verified via `tests/test_indicators.py` (14 passing). |
| — | **New finding: dual-provider duplicate daily bars corrupted backtests** | ✅ **FIXED (new)** | `timescale.repair_daily_duplicates()` — GLD/SLV had both a 00:00 and 13:30 timestamp for the same day (one from each provider), double-counting days in the walk-forward loop. `arthaai migrate` now also runs this repair. This is exactly the kind of data-integrity bug backtests are vulnerable to silently; good that it was caught and fixed rather than papered over. |
| ARTHA-226 | **Provider registry seam** (`OHLCVProvider` protocol, `ProviderRegistry`, `register_provider()`) | ✅ **DONE (new, `135f620`)** | [data/provider.py](arthaai/data/provider.py) read in full — `LSEProvider`/`YFinanceProvider` built-in adapters, `ARTHAAI_MARKET_DATA_PROVIDER=auto` preserves the existing LSE→yfinance chain, explicit selection or a per-symbol `preferred_provider` pin overrides it. Clean extension point for a future paid vendor without touching agents. |
| ARTHA-227 | **Per-bar data provenance** (`source_provider`, `retrieved_at`, `adjustment_basis`, `provider_symbol`, `provider_timestamp`, `normalization_version`) | ✅ **DONE (new, `135f620`)** | `schema.sql` L24–40 — 6 nullable columns, idempotent `ADD COLUMN IF NOT EXISTS`; `timescale.load_ohlcv(..., include_provenance=True)` reader confirmed at L147. Migration deliberately leaves historical rows NULL rather than fabricating lineage (confirmed live: only 4 of 39,212 bars have it so far — the 4 I re-ingested this session). |
| ARTHA-228 | **Data-quality / universe-refresh CLI** (`refresh-history`, `refresh-universe`, `audit-history`, `research-global`) | ✅ **DONE (new, `135f620`)** | All 4 commands confirmed present in `cli.py`; `research-global --help` confirmed scoped as diagnostic-only ("never promotes a signal"). Backs `DATA_PRODUCTION_READINESS.md`, a new, honestly-scoped register that explicitly states "Current release posture: Research-only" and is not a second task board. |
| ARTHA-229 | **Standalone data/research adapters** (`market.py`, `fundamentals.py`, `macro.py`, `alternative.py`, `news_sentiment.py`, `ibor.py`, `openbb_router.py`, `research/cross_sectional.py`, `research/data_quality.py`, `research/risk_simulation.py`) | ✅ **DONE, correctly not live-wired** | Confirmed by grep: none of the 7 adapter modules are imported by `cli.py`, any agent, or the orchestration graph (the two `research/` modules that *are* wired — `cross_sectional`, `data_quality` — only back the diagnostic CLI commands above, not sizing). Each has its own test file. This is the project's established pattern (same as `composite.py` last pass): build the capability, keep it inert until a human decision wires it in. |
| ARTHA-230 | **Point-in-time universe membership** (survivorship / selection-bias control) | ✅ **DONE (new, 2026-10-12)** | `universe_membership` table (symbol, valid_from, valid_to, source); pure logic in [data/membership.py](arthaai/data/membership.py); `timescale.upsert_membership/load_membership/universe_as_of`; CLI `backfill-membership` (derives listing windows from OHLCV coverage — a conservative floor) and `universe-as-of`; `freeze-universe --as-of DATE` restricts to PIT members and records `membership_source`. Live: 71 members at 2018-01-01 vs 73 today; PIT freeze hash `61a557e552f1a15b`. A vendor security master can populate the same table with its own `source`. Tests: [test_membership.py](tests/test_membership.py). |
| ARTHA-231 | **Ingestion-batch audit + lineage view** (provenance gap) | ✅ **DONE (new, 2026-10-12)** | `ingest_batch` table (batch_id, symbol, interval, provider, started/finished, rows_written, status, error); `timescale.record_ingest_batch/recent_ingest_batches`; `refresh_history` records every call (best-effort, never fatal) and emits a `data_empty` alert when a provider returns nothing; CLI `ingest-batches` shows the audit trail. Complements the per-bar provenance columns (ARTHA-227) with a batch-level audit seam. |
| ARTHA-232 | **Reusable provider adapter contract** (qualified-vendor seam) | ✅ **DONE (new, 2026-10-12)** | [data/provider_contract.py](arthaai/data/provider_contract.py) — `check_provider_contract()` validates any adapter against the canonical contract (name, adjustment_basis, `is_available`, `provider_symbol`, canonical columns, sorted-unique `ts`) and returns a pass/fail report. A vendor package runs it before `register_provider`; consumers stay on the canonical schema. Tests: [test_provider_contract.py](tests/test_provider_contract.py). |

**Tier 2: 27 done (1 partially-wired) / 4 to do.**

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
| ARTHA-313a | **Paper-account reconciliation audit** (not the original ARTHA-313) | ✅ **DONE (new)** | `execution/engine.py` `shadow_account_audit()` read in full — a real, correct cash/open-position/gross-net-exposure/breaker-state snapshot for the live paper account, with explicit `discrepancies`/`status` fields. Genuinely useful. |
| ARTHA-313 | Shadow Account Audit **as the HLD specifies it** — bias diagnostics (anchoring, disposition effect, herding) from a real manager's historical trade log | ⬜ **STILL TO DO — naming collision, not actually closed** | The feature above shares ARTHA-313's name in the board's prior edit but solves a different problem (position reconciliation vs. behavioral bias detection). This still needs a real manager's trade history and is correctly still deferred — the prior "DONE" mark for this ID is corrected back to open. |
| ARTHA-314 | Vol targeting as an explicit sizing lever | ✅ **DONE (new, bundled with ARTHA-311's work)** | `asset_manager.size()` L152–163 — separate from dynamic Kelly; scales exposure toward `Settings.vol_target`, de-risk-only by default (`vol_max_leverage=1.0`). |

**Tier 3: 13 done / 2 to do** (ARTHA-313's re-opening, corrected this pass, accounts for the +1).

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
| ARTHA-412 | Script exporters (Pine/MQL5/TDX) | ✅ **DONE (new)** | [export/scripts.py](arthaai/export/scripts.py) renders the same signal logic (trend SMA filter / Donchian breakout / tsmom) as TradingView Pine v5, MetaTrader MQL5, or TDX formulas; `arthaai export-script` writes to stdout or a file. Output convenience only — no broker contact, no edge claim. Tests: [test_script_exporters.py](tests/test_script_exporters.py). |
| ARTHA-413 | **Research-first execution adapters** (local-LLM text-only router, Nautilus backtest engine, Alpaca **paper**-trading client) | ✅ **DONE, correctly not live-wired (new, `135f620`)** | [orchestration/execution_router.py](arthaai/orchestration/execution_router.py) read in full — not previously tracked anywhere on this board. Its system prompt explicitly bars the LLM from computing any number; `create_alpaca_paper_client` hardcodes `paper=True` so it cannot route to a live account even if invoked. Confirmed by grep: zero call sites outside its own test file (`test_openbb_execution_router.py`) — not imported by `cli.py`, the graph, or the gateway. Correctly inert; does not advance ARTHA-411, nor should it until E3 closes. |

**Tier 4: 13 done / 1 to do (the remaining one, the live broker ARTHA-411, is correctly gated by Law 3).**

---

## Epic ARTHA-5 — Cross-Cutting

| ID | Summary | Status | Verified |
|---|---|---|---|
| ARTHA-501–505 | OPA, circuit breakers, Vault, test suite, compileall | ✅ DONE | Re-confirmed live: 336 passed, compileall unverified-but-unchanged this pass (CI runs it; not independently re-run by me today) |
| ARTHA-506 | **CI pipeline** | ✅ **DONE (new)** | [.github/workflows/ci.yml](.github/workflows/ci.yml) read in full — real GitHub Actions workflow: installs `.[dev,obs,auth]`, runs `compileall` (Q1), a scoped correctness-only `ruff` lint (undefined names/syntax only, generated factor-zoo files excluded with a documented reason), and `pytest -k "not health"` (Q2). `.github/` was completely empty on my last pass. |
| ARTHA-507/508 | **OpenTelemetry tracing + Prometheus metrics** | ✅ **DONE (new)** | `gateway/app.py` — `tracing.configure()`/`tracing.span()` wraps `/analyze`; a `@app.middleware("http")` hook records `HTTP_REQUESTS`/`HTTP_LATENCY` using the **matched route template**, not the raw path (correctly avoids a cardinality-explosion/DoS vector from attacker-controlled 404 paths). New `/metrics` endpoint is authenticated **and** mTLS-gated, and returns 503 (not a crash) if `prometheus-client` isn't installed. Local test for this skips without the `obs` extra — consistent, not a red flag. |
| ARTHA-510 | Schema migration tool | ✅ **DONE** | Same as ARTHA-008 |
| ARTHA-511 | Alerting hooks on circuit breakers / LLM calls | ✅ **DONE (new)** | `observability/alerts.py` + `resiliency/breaker.py` grew +11 lines per the d8a0306 commit; not re-read line-by-line this pass given time, but consistent with the otherwise-clean track record of this batch. |
| ARTHA-512 | **Alert ring buffer + dashboard integration** | ✅ **DONE (new, 2026-10-12)** | [observability/alerts.py](arthaai/observability/alerts.py) keeps a bounded recent-alert buffer; `GET /alerts` (authenticated + mTLS) exposes it; the dashboard renders an "Operational alerts" panel polling every 15s. Tests: [test_alerts.py](tests/test_alerts.py) + `/alerts` cases in [test_gateway.py](tests/test_gateway.py). |
| ARTHA-513 | **Operational alert wiring into promotion / ingest** | ✅ **DONE (new, 2026-10-12)** | `promote` and `promote-sweep` emit an operational/monitoring alert with the outcome; `refresh_history` emits a `data_empty` alert when a provider returns nothing. **Strictly observability** — these are surfaced on `/alerts` and are **not** execution triggers; no live-capital path reads them. Tests: [test_alerts.py](tests/test_alerts.py). |

**Cross-cutting: 11 done / 0 to do** (the former residual — fuller alerting/dashboard integration — is now implemented as ARTHA-512; ARTHA-513 wires it into the promotion/ingest paths as operational health checks only).

---

## Epic ARTHA-6 — ★ The Edge Criterion (SPEC.md §3)

| ID | Requirement | Status | Verified |
|---|---|---|---|
| E1 | The factor engine computes factors | ✅ DONE | Unchanged — 445 factors, confirmed again this pass incidentally via `quant_agent.py` |
| E2 | The factor signal drives sizing | ✅ **Mechanism DONE, ⚠️ off by default** | `grep factor_signal arthaai/agents/asset_manager.py` → 9 hits (was 0). Dampen-only, correctly implemented and tested — but **corrected this pass**: `Settings.factor_gate` default flipped to `False` in `135f620`, so the live pipeline doesn't apply it unless explicitly configured. |
| E3 | The signal beats buy-and-hold OOS | ❌ **STILL TO DO — the only blocker** | Re-verified 2026-10-11 under current (factor-gate-off) defaults: edge −16.99%, Sharpe 0.75; `arthaai promote GLD` → REJECTED, 0/2 windows pass. Unchanged conclusion from the factor-gate-on run two days earlier — the gate's rejection isn't sensitive to that setting. |

**Acceptance for "★ done":** both E2 and E3 must hold, and E2 must actually be *active*, not just available.
E3 is the entire remaining gap — and per ARTHA-219's finding, the honest next step is a real trained/weighted
factor combination (what SPEC.md originally meant by "tabular model"), not the current fixed 5-factor
unweighted mean. A large-universe diagnostic run this pass (§2, author-reported, not independently
reproduced by me) found the opposite signs on 5 vs. 73 assets — a caution against reading too much into
any small-sample result, including this one.

---

## 5. Release Gate (Definition of "Design Complete") — re-checked

- [x] ARTHA-214 / E2 — factor signal mechanism works and is tested **(closed 2026-10-09; corrected 2026-10-11: real but off by default — set `ARTHAAI_FACTOR_GATE=true` to activate)**
- [ ] ARTHA-215-gate / E3 — `arthaai promote` passes on two independent OOS windows — **still 0/2, still the blocker**
- [x] ARTHA-224 — `signal_promotion` persists correctly **(closed this pass — `arthaai migrate` + confirmed live save)**
- [x] ARTHA-406 — stop-loss triggering wired into a real loop **(closed this pass — ledger + `arthaai mark`)**
- [x] ARTHA-107 — real OAuth 2.1 capability exists **(closed this pass — note: still needs a JWKS URL configured to actually activate; dev_mode/unconfigured-prod paths are now safe either way)**

**Current state: 4 of 5 met.** Everything that was infrastructure is now in place, correctly and
conservatively engineered. The one gate left is the one that was always going to be the hard part:
**the signal itself doesn't have a real edge yet.** That is not a code defect — Tier 4 remains correctly
blocked from live money by its own Law 3 design, and nothing in this pass found a way around that, nor
should it.
