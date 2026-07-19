# ArthaAI — Architecture Review & Phased Build Plan

> Review of the *ArthaAI Production Blueprint* against feasibility and industry
> standards, plus a lean, $0-start plan designed to scale into the original
> enterprise vision without a rewrite.

**Context / constraints (from you):**
- **Audience:** personal use first → scale to enterprise *if it proves genuinely good*.
- **Execution:** advice-only to start; real auto-execution is a long-term goal.
- **Budget:** start at **$0**; invest in data + infra only once the product shows tangible results.

---

## TL;DR verdict

The blueprint is **excellent as a vision statement and mostly wrong as a starting plan.**
It describes the end-state of a funded enterprise quant desk, not something one
person can start building and get value from. Keep it as the v2/v3 north star;
start from a much thinner slice.

---

## The single most important concern

The architecture's core loop is:

> worker agents gather data → **Master Reasoning LLM "predicts the most likely outcome"** → Asset Manager sizes the bet with Kelly → execute.

This is the weakest link, and everything downstream inherits its flaw.

- **LLMs do not forecast asset returns.** They summarize, extract, explain, and
  structure — they do not output a calibrated probability that gold goes up.
- The plan feeds that uncalibrated "confidence interval" straight into the
  **Kelly Criterion**, which is *extremely* sensitive to the accuracy of its
  probability input. Kelly on top of a miscalibrated probability is a
  mathematically-optimal route to ruin.

**Fix (industry standard):** keep the LLM, change its job.
- Deterministic, backtestable quant models produce the numbers and probabilities.
- The LLM **explains, contextualizes, and synthesizes narrative** around them.
- Nothing auto-executes in v1 — decision-support, human-in-the-loop, paper trading
  only, until there is out-of-sample evidence of edge.

---

## Things that are actually wrong or infeasible

- **Institutional alt-data feeds are a hard budget wall.** Kpler, Vortexa,
  Kayrros, Ursa Space, LSEG, S&P Global, Permutable are real but cost tens to
  hundreds of thousands of $/year with commercial contracts. The entire
  **Alternative Data Agent** (satellite oil storage, vessel tracking) is out of
  reach unless funded. **Drop from v1.**
- **Some named tools look fabricated or research-only:**
  - **"TradeTrap"** (online eval framework) — unverified; treat as hallucination
    until a real source is found.
  - **SEAL** (Self-Adapting LLMs) — real 2025 research paper, nowhere near
    production. Fine-tuning a model to make trading decisions from self-generated
    data is a research project, not a foundation. **Cut the entire
    fine-tuning / SEAL / catastrophic-forgetting section.**
  - **"Lumina MCP Gateway"** — unverified.
- **The Kelly formulas are garbled in the source doc.** Correct forms:
  - Discrete: `f = W − (1 − W) / R`
  - Continuous: `f = (μ − r) / σ²`
  - What's printed (`K%=R(W×R)+1−1`) is mangled — fix before implementing.
- **Redundant orchestration layers.** LangGraph *and* Strands Agents *and* MCP
  *and* Kafka is three coordination mechanisms stacked. Pick **one** orchestrator
  (LangGraph) for v1. Kafka and Strands are premature.
- **The zero-trust stack is misordered.** SPIFFE/SPIRE, OPA/Rego, HashiCorp Vault,
  mTLS, Kubernetes, micro-segmentation in *Sprint 1*, before a single price is
  fetched. That's security infra for a system holding **clients' money** and
  executing real trades — months of yak-shaving that delivers zero analytical
  value for a personal tool. **Defer.**

---

## What's genuinely good — keep it

- **TimescaleDB** for tick/OHLCV data and **Qdrant** for news/RAG — correct,
  appropriate choices.
- **FastAPI + circuit breakers (pybreaker) + fallbacks** — good, standard
  resiliency (add when something real needs it, not day one).
- **Separating deterministic SQL/indicator computation from the LLM** so the model
  never does raw math — exactly right.
- **MCP** as a tool-integration standard — adopt once you expose >1 tool.
- **"Explain why" rationale output** + human-in-the-loop checkpoints — the safest
  parts of the design; keep them.

---

## Guiding principle for the build

**Prove edge cheaply, then scale.** Build a thin, free, decision-support slice
now, but structure it so enterprise pieces (Kafka, zero-trust, alt-data agents,
auto-execution) bolt on later without a rewrite.

The gate between "personal toy" and "spend money / scale" is **one number:**
does a signal show real, out-of-sample edge on paper?

The trap to avoid: building the security tier, Kafka, and satellite agents first,
then discovering the core prediction has no edge.

**The one architectural rule that protects the future:**
Deterministic quant layer **≠** LLM layer. Numbers, signals, and probabilities
come from backtestable statistics. The LLM reads those numbers + news context and
*explains a view* — it never invents a price target or a raw probability fed to
Kelly.

---

## v1 stack — all free, all local (Docker + AWS already available)

| Layer | v1 choice (free) | Scales later to |
|---|---|---|
| Market data | `yfinance` + Alpaca free paper API | Polygon / broker feeds |
| Asset universe | **Commodity ETFs (GLD, SLV, USO, DBC) + a few large-cap stocks** — "commodities & stocks" via free equity data | Real futures / spot feeds |
| Time-series DB | TimescaleDB (Docker, local) | Same, managed / clustered |
| Vector DB | Qdrant (Docker, local) | Same, managed |
| News / sentiment | Free RSS + NewsAPI / Alpha Vantage free tier | Permutable / LSEG (paid) |
| Orchestration | LangGraph (one framework) | + Kafka at real concurrency |
| LLM | Claude API (or Bedrock via AWS creds) | Same |
| Backtest | `vectorbt` / `backtrader` + look-ahead guards | Same |
| Execution | Alpaca **paper** account | Real broker + full compliance / zero-trust tier |

> Commodity **ETFs** let you analyze commodities and stocks through a single free
> equity data source — unblocking the whole pipeline at $0.

---

## Milestones

- **M0** — Repo scaffold + `docker-compose` (TimescaleDB + Qdrant) +
  provider-abstracted config (free→paid is a config change, not a rewrite).
- **M1** — Ingest OHLCV for the ETF+stock universe into Timescale; compute
  indicators in SQL.
- **M2** — **Backtest harness with look-ahead-bias guards.** The foundation.
  Measure whether *any* baseline signal has edge before adding AI.
- **M3** — News → Qdrant RAG with per-asset metadata filtering.
- **M4** — One LangGraph analyst agent: reads M1 signals + M3 news, outputs an
  explained view.
- **M5** — Fractional-Kelly advisor (quarter-Kelly, hard caps, human approval,
  paper-only) + paper-trading loop + performance dashboard.

**→ Money gate:** if M2–M5 show tangible edge on out-of-sample paper trading,
*that* is when to invest in data and the enterprise architecture from the original
blueprint.

---

## Mapping to the original 5-sprint roadmap

The blueprint's roadmap is effectively **inverted**:

| Original blueprint | Reality |
|---|---|
| Sprint 1: zero-trust infra (Vault, SPIFFE, mTLS, k8s) | Do **last** (Sprint 5+), only if handling others' money / auto-executing |
| Sprint 5: analysis + Kelly sizing | Do **first** — it's where the value and the hard lessons live |

Deliver analytical value first; add infrastructure only when something real needs
protecting.

---

## Open decision

- **LLM provider for the analyst agent:** **Claude API** (simplest) vs.
  **AWS Bedrock** (uses existing AWS creds). Default: Claude API unless Bedrock
  preferred.

## Next step

Start **M0**: scaffold the repo (docker-compose, folder structure, config layer,
README capturing this phased plan with the original blueprint preserved as the
v2+ vision).
