# ArthaAI

Multi-agent LLM framework for analysing equities & commodities — an implementation
of the [architecture blueprint](arthaai-architecture.html) (open it in a browser, or
see the published doc). Runs end-to-end on a laptop with free data and no API key.

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

No `ANTHROPIC_API_KEY`? The Master LLM **falls back to a deterministic offline
reasoner** — the same resilience pattern the blueprint uses (fallback to an
internally-hosted model). Add the key to get real Claude synthesis.

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
