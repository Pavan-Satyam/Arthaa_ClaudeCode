# Evaluation & Integration Plan — London Strategic Edge market data

**Status:** proposal, nothing implemented. Awaiting a free API key and a licensing decision.
**Candidate source:** [londonstrategicedge.com](https://londonstrategicedge.com/) — free archive of
~133 billion ticks across ~118,000 datasets (stocks, options, FX, crypto, futures, ETFs,
commodities, indices, bonds) plus ~14,600 macro series for 100+ countries, downloadable as
Parquet/CSV, with an HTTP API and WebSocket feed.

---

## 1. The question that started this: "can we fine-tune the model on it?"

**No — that's a category error, and it isn't the bottleneck.**

- Fine-tuning an LLM means training on **text**. This archive is **numeric time-series**.
  There is nothing for a language model to learn from a column of ticks.
- Serialising prices into text to fine-tune on would produce a model that emits
  plausible-looking numbers — precisely the failure mode this architecture exists to prevent
  (see the design rule in [AI_ENGINEER_HANDOFF.md](AI_ENGINEER_HANDOFF.md) §1.1).
- The measured bottleneck is **signal edge, not synthesis quality**: `arthaai backtest GLD`
  currently shows the naive signal at ~+2% vs ~+50% buy-and-hold. A better-tuned explainer
  just narrates a coin flip more eloquently.

**What this data *is* good for:** the deterministic quant layer — real backtesting at depth,
whole-market screening, and a tabular ML signal. That is where the value is.

---

## 2. The licensing constraint (read before anything else)

The official Python client [`lse-data`](https://github.com/londonstrategicedge/lse-data) is
MIT licensed, **but the data is not open**. From the repository:

> "Data retrieved with an LSE key may not be redistributed, resold, or otherwise made
> available to third parties, whether in bulk or by way of any competing feed."

Mapped to ArthaAI's two phases:

| Use | Verdict |
|---|---|
| Personal research, backtesting, signal development | ✅ Fine |
| Showing raw prices/charts to other users in a product | ⚠️ Likely violates "made available to third parties" |
| Publishing only derived output (a verdict/rationale, not the data) | Grey — obtain written clarification before commercialising |

**Implication:** green light for the current phase; a blocker to resolve *before* ArthaAI
becomes a multi-user product. Do not design a product around this feed until clarified.

---

## 3. Phase 0 — Decisions required (you, ~15 min)

1. Obtain the free key at `londonstrategicedge.com/data`; place it in `.env` as
   `LSE_API_KEY=…` (handled like every other secret — Vault with env fallback, never logged).
2. Read their full terms and decide the endgame: **personal-only** or **product**. If product,
   resolve §2 first.

---

## 4. Phase 1 — Validate before integrating (~1 hour)

**Principle: never build on data you have not measured.** Bad data is worse than no data
because it yields confident, wrong backtests. This is a throwaway script, not committed code.

| Check | Method | Pass criteria |
|---|---|---|
| **Accuracy** | GLD / AAPL / NVDA, 2y daily — diff closes against yfinance | mean absolute difference < 0.1% |
| **Corporate actions** | NVDA around its 10:1 split (Jun 2024) | split handled; no phantom crash |
| **Gaps** | compare trading days against the NYSE calendar | < 1% missing sessions |
| **Survivorship bias** | request a known delisted ticker | present = good; absent = major caveat for backtests |
| **History depth** | request 2003 data (their stated coverage) | data actually returned |
| **Quota** | `GET /vault/usage` | know the ceiling before any bulk pull |

**Gate:** if accuracy or corporate actions fail → **stop**, remain on yfinance. Report is
pass/fail with numbers.

---

## 5. Phase 2 — Integrate behind the existing seam (~half day)

Contained and reversible; no changes to agents, orchestration, or the LLM layer.

- **New** `arthaai/data/sources.py` — `fetch_ohlcv()` dispatching on
  `ARTHAAI_MARKET_DATA_PROVIDER` (`yfinance` | `lse`), returning the identical normalised
  frame (`ts, open, high, low, close, volume`, UTC).
- **LSE provider** via the official `lse-data` client, added as optional extra `[lse]`.
  Key resolved through Vault → env.
- [`data/ingest.py`](arthaai/data/ingest.py) calls `sources.fetch_ohlcv()` instead of
  yfinance directly — effectively a one-line change.
- **yfinance remains an automatic fallback** through the existing circuit breaker
  ([`resiliency/breaker.py`](arthaai/resiliency/breaker.py)), so an LSE outage degrades
  rather than breaks.
- Tests covering the normalisation contract.

---

## 6. Phase 3 — What this unlocks

1. **Credible backtests.** Today: ~400 bars from yfinance. With this: US equities back to
   **2003** — enough to span the 2008 and 2020 regimes. That is the difference between a toy
   backtest and one worth acting on.
2. **Whole-market screening.** Their **bulk Parquet export** (not per-symbol API calls) makes
   ranking all ~12,500 catalogued symbols feasible. This collapses the **$1k–5k/month rung**
   of the investment ladder (see [analyze-walkthrough.html](analyze-walkthrough.html)) toward
   **$0** — the single largest item on that roadmap.
3. **A tabular ML signal.** XGBoost / LightGBM on engineered features, living in the
   deterministic quant layer beside [`agents/indicators.py`](arthaai/agents/indicators.py) —
   backtestable, auditable, no hallucination. This is the correct ML for price prediction
   (and notably what LSE's own tooling offers). The LLM continues to explain; it never predicts.

---

## 7. Phase 4 — The real work (ongoing)

Signal research against the look-ahead-guarded harness in
[`backtest/engine.py`](arthaai/backtest/engine.py). Data is the enabler, not the answer.
**Success metric is unchanged: beat buy-and-hold out of sample.**

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| Redistribution clause blocks productisation | Resolve in Phase 0 if a product is the goal |
| Unknown operator durability (free, plain HTTP, little corporate detail) | Keep swappable by design (Phase 2); never a single point of failure |
| Rate limits make a 12,500-symbol backfill a multi-day job | Check `/vault/usage` first; prefer bulk Parquet over per-symbol calls |
| "Free" terms could change | Treat as an accelerator, not a foundation; retain yfinance path |
| Data quality unverified | Phase 1 exists precisely for this; it is a hard gate |

---

## 9. Effort & gates

| Phase | Effort | Gate |
|---|---|---|
| 0 — key + terms | 15 min (you) | licence acceptable for the endgame? |
| 1 — validation | ~1 hr | data quality passes? |
| 2 — integration | ~half day | — |
| 3 — bulk + screening | 1–2 days (+ rate-limit time) | — |
| 4 — signal research | ongoing | beats buy-and-hold? |

**Next action:** place the free key in `.env` as `LSE_API_KEY`, then run Phase 1. No
integration work begins until validation returns clean.

---

## Sources

- [London Strategic Edge — home](https://londonstrategicedge.com/)
- [Free datasets / API key](https://londonstrategicedge.com/data/)
- [API documentation](https://londonstrategicedge.com/api-documentation/)
- [`londonstrategicedge/lse-data` on GitHub](https://github.com/londonstrategicedge/lse-data) — MIT client, data-use restriction
- [`lse-data` on PyPI](https://pypi.org/project/lse-data/0.14.0/)
