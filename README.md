# ArthaAI


Multi-agent LLM framework for analysing equities & commodities — an implementation
of the [architecture blueprint](arthaai-architecture.html) (open it in a browser, or
see the published doc). Runs end-to-end on a laptop with free data and no API key.

**Docs**
- [`arthaai-architecture.html`](arthaai-architecture.html) — the finalized architecture (status-annotated)
- [`arthaai-architecture-live.html`](arthaai-architecture-live.html) — the same architecture as an animated, interactive node graph
- [`AI_ENGINEER_HANDOFF.md`](AI_ENGINEER_HANDOFF.md) — AI/ML handoff: prompts, provider layer, RAG, evaluation, known gaps
- [`analyze-walkthrough.html`](analyze-walkthrough.html) — non-technical walkthrough for product/ops stakeholders
- [`PROJECT_BOARD.md`](PROJECT_BOARD.md) — actionable task backlog and release-gate state
- [`STATUS_REPORT.md`](STATUS_REPORT.md) — implemented code state and verification evidence
- [`DATA_PRODUCTION_READINESS.md`](DATA_PRODUCTION_READINESS.md) — current data-source state, production replacement seams, qualification, security, and migration evidence

## What actually runs

A single command drives the full blueprint pipeline:

```
arthaai analyze GLD
```

```
 ingest (yfinance → TimescaleDB)
        │  fan-out (LangGraph, mirrors Kafka dispatch)
        ├── DB_Agent      → technical indicators   (TimescaleDB)
        ├── Quant Agent   → μ / σ² / Kelly inputs   (TimescaleDB)
        ├── News_Agent    → hybrid-search sentiment (Qdrant)
        └── Alt_Agent     → physical signal         (stub)
        │  converge → State Store (GraphState)
        ▼
   Master Reasoning LLM  → direction + confidence + explicit rationale
        ▼
   Asset Manager Agent   → fractional Kelly + policy cap → allocation
```

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .

cp .env.example .env          # defaults work as-is; add ANTHROPIC_API_KEY for the real Brain
docker compose up -d          # TimescaleDB + Qdrant + Redpanda (schema auto-applied)

arthaai health                # datastores reachable?
arthaai seed-news             # load illustrative news into Qdrant
arthaai analyze GLD           # run the pipeline (ingests automatically)
arthaai execute GLD           # analyze -> PAPER order through Tier 4 guardrails
arthaai backtest GLD          # walk-forward backtest (look-ahead guarded)
arthaai seed-secrets          # store dev secrets in Vault
arthaai serve                 # Tier 1 gateway + UI at http://localhost:8000/
```

### Optional global research adapters

The research adapters are opt-in so the base ArthaAI install stays small. On
Windows, install only the integrations needed for the research workspace:

```powershell
pip install -e ".[research,market-data,fundamentals,macro,news,openbb,alternatives,execution]"
pip install -e ".[sentiment]"  # only when local FinBERT inference is needed
```

They live under `arthaai.data`: `MarketDataFetcher`, `SECDataProcessor`,
`MacroEconomicsEngine`, `NewsSentimentAnalyzer`, `OpenBBRouter`,
`AlternativeAssetFetcher`, and `IBORStorageManager`. OLS and Monte Carlo tools
are in `arthaai.research.RiskSimulationEngine`. Providers load only when called.
SEC requests require `ARTHAAI_SEC_IDENTITY`; EIA requests require `EIA_API_KEY`;
FRED can use `FRED_API_KEY`. Never commit credentials.

The operational OHLCV provider default is selected with
`ARTHAAI_MARKET_DATA_PROVIDER` (`auto` by default, preserving LSE-if-configured
then yfinance). A named value must match a registered adapter. Built-ins are
`lse` and `yfinance`; a trusted host integration can implement `OHLCVProvider`
and call `arthaai.data.provider.register_provider()` during startup before
selecting that adapter. The CLI and orchestration currently register only the
built-ins; a future vendor adapter must be installed and explicitly registered
by trusted host startup. `--provider` on ingest/refresh commands overrides the
global setting for that invocation, while a stored per-symbol preference takes
precedence during ordinary `ingest`. Unregistered or unavailable explicit
providers fail clearly rather than silently routing to a different source.

New OHLCV upserts retain `source_provider`, `retrieved_at`, `adjustment_basis`,
`provider_symbol`, `provider_timestamp`, and `normalization_version` in TimescaleDB.
`timescale.load_ohlcv(..., include_provenance=True)` exposes these fields for audits;
default reads preserve the existing OHLCV frame. `provider_symbol` is currently the
symbol sent to the provider, not a guaranteed stable vendor ID. Historical bars
without verified lineage remain NULL and are not retroactively attributed to a guessed provider.

DuckDB is a local analytical store and does not replace operational TimescaleDB.
OpenBB extensions must be installed and endpoint coverage verified for each
market. Free feeds are research inputs, not guaranteed production entitlements.

Phase 2 cross-sectional research is available for symbols with stored history:

```powershell
arthaai research-global --symbols GLD,SLV,USO,XOM,AAPL --limit 520 --cost-bps 10
```

This is a diagnostic long-only top-quantile study against a daily rebalanced,
equal-weight portfolio of the same complete-data universe. It is not the formal
per-symbol E3 promotion benchmark. One missing session may be carried at the last
close; assets with longer gaps are excluded, and a window is skipped if too few
assets remain. Global-market claims require broader, point-in-time universe and
corporate-action-clean history than the current local sample provides.

Before expanding that universe, inspect and repair stored history explicitly:

```powershell
arthaai audit-history --symbols GLD,SLV,USO,XOM,AAPL --calendar XNYS
arthaai audit-history --symbols AAPL,VOD.L --calendar-map VOD.L=XLON
arthaai refresh-history GLD --lookback-days 180 --provider yfinance
arthaai refresh-universe --symbols GLD,SLV,USO,XOM,AAPL --lookback-days 180 --provider yfinance
```

The audit is read-only and checks official exchange sessions, gaps, stale bars,
duplicate sessions, and invalid OHLCV. The refresh command re-fetches a bounded
overlap and upserts returned bars; it does not delete data and is never run
automatically by ordinary ingest. `refresh-universe` processes symbols
sequentially and continues after individual failures, reporting each outcome.

Execution remains staged: research only by default; Alpaca client construction
requires explicit paper-mode opt-in and always requests paper trading. No live
broker route is implemented. Nautilus engine construction is an integration seam,
not evidence that a strategy passes E3. Paper operations and live execution remain
blocked until the promotion gate passes.

The stack now includes **5 services**: TimescaleDB, Qdrant, Redpanda (Kafka),
**OPA** (policy engine, :8181) and **Vault** (secrets, :8200). Zero-trust is live:
OPA evaluates every agent tool call against [policy/arthaai.rego](policy/arthaai.rego),
and the gateway/LLM credentials are fetched from Vault. Both degrade to safe
in-process/env fallbacks if a service is down.

On this Mac (Intel Homebrew → Rosetta shell) use the arch-safe wrappers instead:
`make setup && make up && make analyze SYM=GLD` — the Makefile pins Python to
x86_64 so the venv wheels always match your shell.

### HTTP gateway

```bash
arthaai serve
curl -X POST "localhost:8000/analyze/GLD" -H "Authorization: Bearer dev-token"
```

### Choose your LLM (Claude · Gemini · local · offline)

The Master Reasoning LLM is provider-agnostic with a **fallback chain** — set
`ARTHAAI_LLM_CHAIN` and it tries each in order, always ending at the deterministic
offline reasoner so a verdict is guaranteed:

| Want | Set in `.env` |
|---|---|
| **Google Gemini**, fall back to local | `ARTHAAI_LLM_CHAIN=gemini,local,offline` + `GEMINI_API_KEY=…` |
| **Local model only** (Ollama/LM Studio/vLLM) | `ARTHAAI_LLM_CHAIN=local,offline` + `ARTHAAI_LOCAL_MODEL=llama3.1` |
| **Claude**, fall back to Gemini | `ARTHAAI_LLM_CHAIN=anthropic,gemini,offline` |
| Nothing configured | offline deterministic reasoner (runs with no key) |

- **Local** hits any OpenAI-compatible endpoint. With Ollama: `ollama serve && ollama pull llama3.1` — the default `ARTHAAI_LOCAL_BASE_URL` already points at it. A local model is the blueprint's *"internally-hosted open-weight model"* — zero external dependency or data egress.
- Keys can live in **Vault** (`arthaai seed-secrets` picks up `GEMINI_API_KEY` etc.) or plain env. The `verdict.source` field tells you which provider actually answered (`gemini`, `local:llama3.1`, `claude`, or `offline-fallback`).

## Blueprint → code → status

| Blueprint element | Where | Status |
|---|---|---|
| Tier 2 orchestration (**LangGraph**, GraphState) | [orchestration/graph.py](arthaai/orchestration/graph.py), [state.py](arthaai/orchestration/state.py) | ✅ implemented |
| **DB_Agent** (SQL, indicators) | [agents/db_agent.py](arthaai/agents/db_agent.py), [indicators.py](arthaai/agents/indicators.py) | ✅ implemented |
| **Quant Agent** (μ, σ², Kelly inputs) | [agents/quant_agent.py](arthaai/agents/quant_agent.py) | ✅ implemented |
| **News_Agent** (Qdrant hybrid search) | [agents/news_agent.py](arthaai/agents/news_agent.py), [db/qdrant.py](arthaai/db/qdrant.py) | ✅ implemented (seed data) |
| **Master Reasoning LLM** (rationale) | [agents/master_llm.py](arthaai/agents/master_llm.py) | ✅ Claude + offline fallback |
| **Asset Manager** (Kelly + policy cap) | [agents/asset_manager.py](arthaai/agents/asset_manager.py) | ✅ implemented |
| **TimescaleDB** (hypertable, OHLCV) | [db/schema.sql](arthaai/db/schema.sql), [db/timescale.py](arthaai/db/timescale.py) | ✅ implemented |
| **Qdrant** (payload-filtered vectors) | [db/qdrant.py](arthaai/db/qdrant.py) | ✅ implemented |
| **Circuit breaker** (CLOSED/OPEN/HALF-OPEN) | [resiliency/breaker.py](arthaai/resiliency/breaker.py) | ✅ implemented |
| **Tier 1 gateway** (FastAPI, OAuth 2.1/MCP auth, rate limit) + **UI** | [gateway/app.py](arthaai/gateway/app.py), [dashboard.html](arthaai/gateway/static/dashboard.html) | ✅ implemented (mTLS = infra) |
| **Tier 4 execution** (drawdown breaker, stop-loss) | [execution/engine.py](arthaai/execution/engine.py) | ✅ paper-only |
| **OPA policy-as-code** (live Rego, every tool call) | [policy/arthaai.rego](policy/arthaai.rego), [security/opa.py](arthaai/security/opa.py) | ✅ live OPA server + fallback |
| **HashiCorp Vault** (secrets: gateway token, LLM key) | [security/vault.py](arthaai/security/vault.py) | ✅ live Vault + env fallback |
| **Offline evaluation** (walk-forward backtest, look-ahead guard) | [backtest/engine.py](arthaai/backtest/engine.py) | ✅ implemented |
| **Kafka event bus** (producer + consumer) | [data/ingest.py](arthaai/data/ingest.py), [data/consumer.py](arthaai/data/consumer.py) | ✅ Redpanda |
| **Alt_Agent** (Kpler/Vortexa/Kayrros/Ursa) | [agents/alt_agent.py](arthaai/agents/alt_agent.py) | ○ stub (paid feeds) |
| **SPIFFE/SPIRE identity · mTLS · Kubernetes** | [security/policy.py](arthaai/security/policy.py) | ○ ops infra (seam ready) |

✅ runs · ◐ partial · ○ interface/stub

### Why the stubs
Satellite/cargo feeds (Kpler, Ursa) require commercial contracts; SPIFFE/SPIRE,
Vault, OPA sidecars, mTLS and Kubernetes micro-segmentation are deployment
infrastructure, not application code, and can't run meaningfully on one machine.
Each is a real seam in the code (least-privilege tool scopes are already enforced
in-process via `security/policy.py`), so the enterprise layer plugs in at Sprint 5
without refactoring the agents.

## Design rule honoured throughout
The **deterministic quant layer** ([indicators.py](arthaai/agents/indicators.py),
DB/Quant/Asset-Manager) computes every number; the **Master LLM only synthesises
and explains**. Kelly sizing runs on statistics, never on an LLM-invented
probability — and a deterministic policy cap always overrides the model.
