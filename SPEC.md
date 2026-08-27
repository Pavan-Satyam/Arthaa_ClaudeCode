# ArthaAI — Conformance Spec & End-to-End Verification

Defines what "conformant and working" means for ArthaAI as **testable criteria**,
and records the end-to-end verification of the current branch against them.

- **Verified:** `HEAD` (Siddhu's batch, `0b0c539`) vs **baseline** `d7d39d6`
- **Method:** static (git/grep/compile), unit (`pytest`), and live end-to-end (`analyze`, `backtest`) on real GLD data
- **Environment note:** run every command via `arch -x86_64 .venv/bin/…` (this Mac's shell is x86_64/Rosetta). Numbers marked *(data-dependent)* move as the market data updates.

Legend: ✅ pass · ❌ fail · ⚠️ conformant-but-incomplete

---

## 1. Invariants — the three laws (MUST hold on every change)

### L1 — Numbers are deterministic; the LLM only explains
| # | Requirement | Verification | Result |
|---|---|---|---|
| L1a | The LLM node and the orchestrator produce **no** trade numbers | `git diff --quiet d7d39d6 HEAD -- arthaai/agents/master_llm.py arthaai/orchestration/` | ✅ both identical to baseline |
| L1b | Position sizing is a **pure function** of deterministic stats — never reads the LLM or an un-backtested signal | `grep factor_signal arthaai/agents/asset_manager.py` → **0**; sizing inputs are only `win_prob`, `win_loss_ratio`, `mu`, `variance` | ✅ |
| L1c | The verdict narrates evidence; `verdict.source` records the model, not a computation | `analyze GLD` → rationale cites agent evidence, `source=offline-fallback` | ✅ |

### L2 — A reproducible graph, not an agent free-loop
| # | Requirement | Verification | Result |
|---|---|---|---|
| L2a | Orchestration topology unchanged | `git diff --quiet d7d39d6 HEAD -- arthaai/orchestration/` | ✅ |
| L2b | Same input → same output (deterministic chain) | `ARTHAAI_LLM_CHAIN=offline analyze GLD` ×2 → identical direction | ✅ `bullish == bullish` |

### L3 — Nothing is trusted until it beats buy-and-hold (the gate)
| # | Requirement | Verification | Result |
|---|---|---|---|
| L3a | Backtest is look-ahead-safe (signal at day *t* sees only bars ≤ *t*) | code review of `backtest/engine.py`; asserted in output banner | ✅ |
| L3b | Backtest reports strategy vs benchmark(s) | `backtest GLD` emits strategy / long-short / long-only / buy&hold / edge / Sharpe / hit-rate | ✅ mechanism works |
| L3c | **Gate status:** does the current signal pass? | GLD edge vs buy&hold = **−32.34%** *(data-dependent)* | ❌ **does NOT pass** — not promotable to real money |

---

## 2. Tier conformance (finalized architecture)

| Tier | Component | Spec | Verified state |
|---|---|---|---|
| 1 | FastAPI gateway, httpOnly-cookie auth, `/ohlcv` authenticated, `dev_mode` prod guard | running | ✅ (gateway tests pass) |
| 2 | LangGraph orchestrator + GraphState | running | ✅ (unchanged) |
| 2 | DB_Agent — indicators + ADX regime (trend/breakout) | running | ✅ (`ADX 30.2 (trending)` observed) |
| 2 | **★ Quant_Agent — Alpha-Zoo factor engine → signal model** | build-next | ⚠️ engine ✅ / **signal ❌** (see §3) |
| 2 | News_Agent (Qdrant hybrid), Master LLM chain, Timescale, Qdrant | running/partial | ✅ |
| 3 | Asset Manager — signal-conditioned discrete Kelly + hard 5% cap | running | ✅ |
| 4 | Paper execution guardrails | running | ✅ |
| — | LSE multi-source provider | **deferred** in spec | ⚠️ built anyway; carries the 2 failing tests (D2) |

---

## 3. ★ The edge criterion (the whole point of the system)

The finalized architecture's priority is: *Alpha-Zoo factors → tabular model →
**signal** → (only if it beats buy-and-hold) live use.*

| # | Requirement | Verification | Result |
|---|---|---|---|
| E1 | The factor engine computes factors | registry loads **445** (alpha101 101 · gtja191 190 · qlib158 154); `quant_agent.run('GLD')` returns `factors` + `factor_signal` | ✅ |
| E2 | The factor signal **drives sizing** | `factor_signal = −9.778` produced, but `asset_manager` reads it **0** times; sizing uses `win_prob/win_loss_ratio` only | ❌ **orphaned** |
| E3 | The signal beats buy-and-hold out of sample | backtest edge = **−32.34%** *(data-dependent)* | ❌ |

**Observation:** on GLD the orphaned factor signal is **bearish (−9.78)** while the
shipped verdict is **bullish** — i.e. the factors currently *disagree* with the
signal that actually sizes the trade. Wiring E2 is not cosmetic; it changes outputs.

**Acceptance for "★ done":** E2 wired into signal-conditioned Kelly **and** E3 edge > 0
on out-of-sample data. Until both hold, the factor engine is infrastructure, not edge.

---

## 4. Quality gates (MUST pass to merge to a "working" branch)

| # | Gate | Command | Result |
|---|---|---|---|
| Q1 | All source compiles | `python -m compileall arthaai` | ✅ clean (24 junk-line files fixed) |
| Q2 | Test suite green | `pytest` | ✅ **88 passed** (stable across 2 runs) |
| Q3 | No dead / bloat files | repo scan | ✅ `ALPHA_ZOO_EXTRACTION.md` removed (in git history) |
| Q4 | No orphaned outputs feeding money | grep + review | ✅ orphaned `factor_signal` is inert (does not reach sizing) — safe, but see E2 |

---

## 5. Verification log (evidence)

```
# L1a / L2a
git diff --quiet d7d39d6 HEAD -- arthaai/agents/master_llm.py   → identical
git diff --quiet d7d39d6 HEAD -- arthaai/orchestration/          → identical

# L1b / E2   grep factor_signal arthaai/agents/asset_manager.py  → 0
#            sizing inputs: win_prob, win_loss_ratio, mu, variance

# Q1  broken qlib158 files (py_compile loop)                     → 24
# E1  registry.list: alpha101 101 · gtja191 190 · qlib158 154    → 445
# Q2  pytest                                                     → 2 failed, 86 passed

# L1c/L2b  ARTHAAI_LLM_CHAIN=offline analyze GLD (×2)
#   DB_Agent bullish · RSI 66.0 · ADX 30.2 (trending)
#   Quant μ +31.94% · σ 25.80% · W 0.56 · R 0.96
#   Verdict BULLISH · confidence 78% · offline-fallback
#   run1=bullish run2=bullish  → identical

# L3/E3  backtest GLD
#   strategy (Kelly) +0.66% · long/short +38.47% · long-only +51.16%
#   buy & hold +70.81% · edge vs B&H −32.34% · Sharpe 0.47 · hit 54.5%

# E2  quant_agent.run('GLD')
#   factor_signal = −9.778 · top: alpha101_024/009/012/023/031
#   asset_manager.size(q) → win_prob 0.56, win_loss_ratio 0.96, final 0.0259
#   factor_signal changes sizing? NO
```

---

## 6. Defects & acceptance criteria for "fixed"

| ID | Defect | Fixed when | Status |
|---|---|---|---|
| **D1** | 24 `qlib158/*60.py` files carry a trailing non-code line (U+2014) → won't compile; silently dead at runtime | `compileall` clean; the 24 factors compute a value | ✅ fixed (junk lines removed) |
| **D2** | `test_provider.py` fails — non-hermetic: `provider.py` bound `get_settings` at import, so `arthaai.config.get_settings` patches were inert (tests leaked to real yfinance) | `pytest` green and stable | ✅ fixed — `provider.py` now calls `arthaai.config.get_settings()` (patchable); `test_no_lse_key_uses_yfinance` retargeted to match |
| **D3** | `ALPHA_ZOO_EXTRACTION.md` (31,331 lines) is a raw dump / noise | removed from the tree (recoverable via git history) | ✅ removed |
| **D4** *(design, not a bug)* | ★ `factor_signal` is orphaned (E2) | factor signal wired into sizing **and** backtest edge > 0 (E3) | ⬜ open — the real remaining work |

**Summary:** the three laws hold (L1/L2 ✅, L3 mechanism ✅), and the factor engine +
eval harness are real, on-spec additions. Quality gates **Q1/Q2/Q3 now all pass**
(D1–D3 resolved). The one thing still outstanding is the headline **edge**:
`factor_signal` remains orphaned (E2) and the signal does not yet beat buy-and-hold
(E3). That — wiring factors into sizing and proving edge — is **D4**, the real work,
deliberately kept as a separate change because it alters trading outputs.
