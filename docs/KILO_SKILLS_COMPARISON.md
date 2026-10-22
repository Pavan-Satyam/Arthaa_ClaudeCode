# Kilo Code Skills — Fit Against the ArthaAI Codebase

*Prepared 2026-10-21 · decides which Kilo Code marketplace skills and MCP servers are worth installing
for this repo.*

**Method:** each catalog entry is judged only on whether it touches code, infrastructure, or workflow
that exists in this repo today. The stack was read from [`pyproject.toml`](../pyproject.toml),
[`docker-compose.yml`](../docker-compose.yml) (TimescaleDB, Qdrant, Redpanda, OPA, Vault), the
`arthaai/` import graph, and [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

> **Scope note.** Only the A–F part of the catalog was reviewed, from *Adbc* through *Frontend
> Specialist*; the listing was cut off there. Entries from G to Z have not been assessed yet.

Legend: ✅ install · ⚠️ conditional · ❌ no fit.

---

## 1. Direct fit ✅

| Skill / MCP | Where it lands in the code | Note |
|---|---|---|
| **Context7** | [`orchestration/graph.py`](../arthaai/orchestration/graph.py) (LangGraph), [`db/qdrant.py`](../arthaai/db/qdrant.py) (`qdrant-client`), [`data/consumer.py`](../arthaai/data/consumer.py) (`confluent-kafka`), [`data/openbb_router.py`](../arthaai/data/openbb_router.py), `execution` extra (`nautilus_trader`, `alpaca-py`) | Highest value. These libraries change their APIs often, and outdated signatures are a common source of bugs. |
| **DBHub** (Bytebase) | [`db/timescale.py`](../arthaai/db/timescale.py), [`db/migrate.py`](../arthaai/db/migrate.py), TimescaleDB 2.17 / Postgres 16 in compose | Lets an agent check hypertables, ingest gaps, and backtest inputs directly. Connect it through a **read-only** database role. |
| **Fastapi Itechmeat** | [`gateway/app.py`](../arthaai/gateway/app.py), [`gateway/auth.py`](../arthaai/gateway/auth.py) (JWT via `pyjwt`), [`gateway/mtls.py`](../arthaai/gateway/mtls.py), `slowapi` rate limiting | Covers OAuth2/JWT, which is what `auth.py` implements. *Fastapi Martinholovsky* overlaps with it, so install only one. |
| **Confluent MCP Server** | Redpanda + [`data/consumer.py`](../arthaai/data/consumer.py) | Redpanda speaks the Kafka API, so topic and consumer inspection should work (untested). The Schema Registry, Connect, and Flink tools do not apply. |
| **Data Investigation** | E3 campaign: [`E3_EVALUATION_PROTOCOL.md`](../E3_EVALUATION_PROTOCOL.md), [`evaluation/`](../evaluation/) sweep outputs, [`evaluation/e3_results.md`](../evaluation/e3_results.md) | A structured workflow for explaining why a sweep result changed or for validating a signal hypothesis. |

---

## 2. Conditional fit ⚠️

| Skill / MCP | Why it's conditional |
|---|---|
| **Chdb Datastore** | The code is pandas-heavy: 480 modules import pandas, mostly the factor zoo. But the hot rolling operations already go through bottleneck in [`factors/_backend.py`](../arthaai/factors/_backend.py), and switching to chDB would mean rewriting factor code. Revisit only if factor computation becomes a measured bottleneck. |
| **Exa Search / Brave Search / Firecrawl** | News ingestion uses `feedparser` + `trafilatura` in [`data/news_feed.py`](../arthaai/data/news_feed.py). These are paid APIs, which conflicts with the "free data, no API key" goal. Use them for research during development, not in the pipeline. |
| **Dashboarding** (Grafana) | [`observability/metrics.py`](../arthaai/observability/metrics.py) exports Prometheus metrics, but there is no Grafana service in compose. Useful only once Grafana is added. |
| **Data Quality Frameworks** | The repo already has [`research/data_quality.py`](../arthaai/research/data_quality.py). Great Expectations or dbt tests would add a new framework rather than support the existing one. |
| **Code Skeptic / Code Reviewer** | Generic, but most useful on the look-ahead guards in [`backtest/engine.py`](../arthaai/backtest/engine.py) and the execution guardrails in [`execution/`](../arthaai/execution/). |
| **Documentation Specialist** | Generic, but the repo is documentation-heavy: `SPEC.md`, `PROJECT_BOARD.md`, `STATUS_REPORT.md`, the HTML architecture docs, and the [`likec4/`](../likec4/) model. |
| **Create Pull Request / Changelog Generator** | Generic git workflow. There is no `CHANGELOG` yet, so the generator would start from scratch. |

---

## 3. No fit ❌

| Group | Entries | Reason |
|---|---|---|
| Cloud platforms | All AWS, Azure, Databricks, BigQuery, Snowflake (Cortex Code), Firebase, Cloudflare, Vercel, Cognito, Entra entries | None are used; the stack runs on local Docker. |
| Pipeline / orchestration | Airflow (+ Authoring / Deploying Dags), Dagster, dbt, Beam, Flink, NiFi, Fivetran, Airbyte, ADF, CDC Streaming Pipeline, Hudi, Delta Sharing | Orchestration is LangGraph; ingest is in-process Python. |
| Datastores | Cassandra, Keyspaces, Redshift, Elasticsearch, Db2, Fireproof, ADBC | The datastores are TimescaleDB (via `psycopg`) and Qdrant. |
| Secrets | Azure Key Vault, Creating Secrets Using Best Practices (AWS Secrets Manager) | Secrets live in HashiCorp Vault ([`security/vault.py`](../arthaai/security/vault.py)). |
| Frontend | All 10 Angular skills | The UI is one inline `HTMLResponse` in [`gateway/app.py`](../arthaai/gateway/app.py). |
| Observability | Datadog Managed MCP, Dd Logs, Dd Pup, Database Observability (Grafana Cloud) | Observability uses Prometheus + OpenTelemetry. |
| Tooling mismatches | Agent Md Refactor, Anaconda, Aoti Debug, Datalayer Jupyter | `AGENTS.md` is 91 lines, so there is nothing to split; the env is venv + pip; no AOTInductor; no notebooks. |
| Trading platform | Composer | An external strategy and live-trading platform. Leave it out: it would sit next to an execution path that is meant to place only paper orders. |
| Unrelated | Competitive Ads Extractor, Domain Name Brainstormer, eSignatures, Canvas Design, Artifacts Builder, ClickUp, Atlassian, Collibra, DataHub, DataRobot, Dataset Evaluation / Transformation, and similar | No matching code or workflow. The project board lives in [`PROJECT_BOARD.md`](../PROJECT_BOARD.md). |

---

## 4. Gap

None of the A–F entries cover the core of this repo:

- the 445 factor implementations in [`factors/zoo/`](../arthaai/factors/zoo/) (Alpha101, GTJA191, Qlib158)
- the walk-forward backtest and its look-ahead guards in [`backtest/engine.py`](../arthaai/backtest/engine.py)
- fractional Kelly sizing in [`agents/asset_manager.py`](../arthaai/agents/asset_manager.py)
- the execution guardrails in [`execution/`](../arthaai/execution/)

When the G–Z part of the catalog is reviewed, look first for quant, backtesting, pandas, pytest,
Postgres, and Qdrant skills; any of those would matter more than everything in sections 1–2.

---

## 5. Recommended install set

1. **Context7**
2. **DBHub**, through a read-only TimescaleDB role
3. **Fastapi Itechmeat**
4. **Data Investigation**, for E3 sweep analysis
5. **Confluent MCP Server**, only when debugging the Kafka dispatch path
