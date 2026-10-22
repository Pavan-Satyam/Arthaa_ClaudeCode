# Kilo Marketplace — Fit Against the ArthaAI Codebase

*Prepared 2026-10-21 · covers the **whole** Kilo marketplace (agents, MCP servers, skills, plugins,
modes) and replaces the earlier A–F-only version of this file.*

**Source:** [`Kilo-Org/kilo-marketplace`](https://github.com/Kilo-Org/kilo-marketplace) at commit
`ff51758` (2026-09-28): 336 entries.

**Method:** each entry is judged only on whether it touches code, infrastructure, or workflow that
exists in this repo today. The stack was read from [`pyproject.toml`](../pyproject.toml),
[`docker-compose.yml`](../docker-compose.yml) (TimescaleDB, Qdrant, Redpanda, OPA, Vault), the
`arthaai/` import graph, and [`.github/workflows/ci.yml`](../.github/workflows/ci.yml). Agent edit,
bash, and MCP permissions were read from each agent's definition in the catalog.

| Verdict | Agents | MCP servers | Skills | Plugins | Modes | Total |
|---|---:|---:|---:|---:|---:|---:|
| ✅ **Install** now | 5 | 3 | 4 | 0 | 0 | **12** |
| ⚠️ **Conditional**: install when the trigger happens | 1 | 10 | 11 | 1 | 0 | **23** |
| ↔️ **Alternative**: overlaps a pick; don't install both | 0 | 4 | 2 | 0 | 0 | **6** |
| ❌ **Skip**: no fit | 2 | 111 | 174 | 1 | 7 | **295** |
| **Total** | 8 | 128 | 191 | 2 | 7 | **336** |

Every entry, with its verdict and reason, is listed in the [Appendix](#appendix--all-336-entries).

---

## 1. Final list: install now (12)

### MCP servers

| Entry | Where it lands in the code | Setup |
|---|---|---|
| **Context7** | [`orchestration/graph.py`](../arthaai/orchestration/graph.py) (LangGraph), [`db/qdrant.py`](../arthaai/db/qdrant.py), [`data/consumer.py`](../arthaai/data/consumer.py) (`confluent-kafka`), [`data/openbb_router.py`](../arthaai/data/openbb_router.py), `execution` extra (`nautilus_trader`, `alpaca-py`) | These libraries change their APIs often; outdated signatures are a common source of bugs. |
| **Postgres MCP Pro** | [`db/timescale.py`](../arthaai/db/timescale.py), [`db/migrate.py`](../arthaai/db/migrate.py), TimescaleDB 2.17 on Postgres 16 | `uvx postgres-mcp==0.3.0 --access-mode=restricted`, with `DATABASE_URI` pointing at a **read-only** role. Needs Python 3.12+ and `uv`. |
| **GitHub** | CI quality gates in [`ci.yml`](../.github/workflows/ci.yml), the `feat/arthaai-core` → `main` PR | Use the catalog's official read-only Docker variant with a GitHub token. |

### Skills

| Entry | Where it lands in the code |
|---|---|
| **Vault Api** | [`security/vault.py`](../arthaai/security/vault.py) calls the Vault KV v2 REST API (`/v1/secret/data/...`) directly through `httpx`; this skill covers exactly that API. |
| **Supabase Postgres Best Practices** | Query, schema, and index review for [`db/timescale.py`](../arthaai/db/timescale.py) and migrations. It is general Postgres guidance, not TimescaleDB-specific. |
| **Fastapi Itechmeat** | [`gateway/app.py`](../arthaai/gateway/app.py), [`gateway/auth.py`](../arthaai/gateway/auth.py) (JWT), [`gateway/mtls.py`](../arthaai/gateway/mtls.py), `slowapi` rate limiting. |
| **Data Investigation** | The E3 campaign: [`E3_EVALUATION_PROTOCOL.md`](../E3_EVALUATION_PROTOCOL.md), [`evaluation/`](../evaluation/) sweep outputs, [`evaluation/e3_results.md`](../evaluation/e3_results.md). |

### Agents

| Entry | Use it for | Edit scope |
|---|---|---|
| **Code Reviewer** | Reviewing backtest, execution, and gateway changes | None (read + bash only) |
| **Code Skeptic** | Adversarial review of the look-ahead guards in [`backtest/engine.py`](../arthaai/backtest/engine.py) and the guardrails in [`execution/`](../arthaai/execution/) | `.md` files only |
| **Architect** | Design and migration plans against [`SPEC.md`](../SPEC.md) | `.kilo/plans/*.md` only; no bash, no MCP |
| **Docs Specialist** | `SPEC.md`, `PROJECT_BOARD.md`, `STATUS_REPORT.md`, `docs/` | `.md`, `.txt`, `.rst`, README, CHANGELOG; **not** the `.html` docs or `likec4/` files |
| **Test Engineer** | The 63 pytest files in [`tests/`](../tests/) | **Needs a change, see below** |

**Test Engineer needs a permission change.** As shipped, it may only edit `*.test.{js,ts,jsx,tsx}`
and `*.spec.{js,ts,jsx,tsx}`, so it cannot write a single test in this repo. After installing it,
add the Python test paths to its `edit` allowlist, then confirm it can edit a test file:

```yaml
permission:
  edit:
    "*": deny
    "tests/test_*.py": allow
    "tests/conftest.py": allow
```

---

## 2. Conditional: install when the trigger happens (23)

| Entry | Type | Install when |
|---|---|---|
| **Skill Creator** | Skill | You write the missing ArthaAI-specific skills listed in [§5](#5-gap-nothing-covers-the-core-of-this-repo) |
| **Confluent MCP Server** | MCP | Debugging the Redpanda consumer in [`data/consumer.py`](../arthaai/data/consumer.py). Only the Kafka-API tools apply; not tested against Redpanda |
| **MotherDuck** | MCP | Inspecting the IBOR DuckDB file used by [`data/ibor.py`](../arthaai/data/ibor.py) (use its local-DuckDB mode, no MotherDuck account) |
| **GitMCP** | MCP | Checking factor definitions against upstream repos, e.g. `microsoft/qlib` for the Qlib158 set |
| **Nia** | MCP | You want research-paper context for factor work; needs an account |
| **Playwright** | MCP | Browser checks of the gateway UI at `:8000` or the HTML docs |
| **Vault MCP** | MCP | Inspecting Vault, with a token scoped to approved paths only; never expose real API keys to the agent |
| **Exa** | MCP | Web research while developing. Keep it out of the news pipeline, which follows the free-data goal |
| **Grafana MCP** (`mcp-grafana`) + **Dashboarding** | MCP + Skill | Grafana is added to compose (there is none today) |
| **Prometheus Addxai** | Skill | A Prometheus server scrapes the gateway's `/metrics` endpoint (none in compose today) |
| **LangSmith Fetch** | Skill | LangSmith tracing is enabled for the LangGraph pipeline (it is not today) |
| **Chdb Datastore** | Skill | Factor computation becomes a measured bottleneck. Rolling operations already go through bottleneck in [`factors/_backend.py`](../arthaai/factors/_backend.py) |
| **Secrets Vault Manager** | Skill | Secret rotation or production secret management starts (Vault runs in dev mode today) |
| **Create Pull Request** | Skill | Opening the `feat/arthaai-core` → `main` PR |
| **Changelog Generator** | Skill | Releases start; there is no CHANGELOG yet |
| **Web Design Guidelines** | Skill | Reviewing the gateway UI or the HTML docs |
| **Code Simplifier** | Agent | You want refactors. It has full edit rights, so keep it out of the generated [`factors/zoo/`](../arthaai/factors/zoo/) and run the tests afterwards |
| **Models Discovery** | Plugin | You want Kilo to use the same OpenAI-compatible local server as ArthaAI's `local` LLM provider |
| **Grilling**, **Ponytail**, **Sequential Thinking**, **Memory** | Skills + MCPs | Workflow preference only (plan interrogation, minimal-solution mode, step-by-step reasoning, cross-session memory) |

---

## 3. Pick-one overlaps

| Need | Pick | Instead of | Why |
|---|---|---|---|
| Postgres access | **Postgres MCP Pro** | DBHub ↔️, Postgres ❌ | The stack is Postgres-only, and Pro adds EXPLAIN, index, and health tools. The reference Postgres server is archived upstream. *This replaces DBHub, which the A–F version of this doc recommended.* |
| FastAPI guidance | **Fastapi Itechmeat** | Fastapi Martinholovsky ↔️ | Itechmeat covers OAuth2/JWT, which `gateway/auth.py` implements |
| Library docs | **Context7** | GitMCP ⚠️, Nia ⚠️ | Keep GitMCP and Nia for the specific uses in §2 |
| Web search | **Exa** | Tavily ↔️, Brave Search ↔️, Kagi ↔️ | One search MCP is enough |
| Browser automation | **Playwright MCP** | Webapp Testing skill ↔️, Puppeteer ❌ (archived), Browserbase ❌ (cloud) | The official Microsoft server is the maintained option |
| Agent format | **Agents** | All 7 Modes ❌ | The catalog keeps modes only for legacy Kilo 5.x clients and no longer maintains them |

---

## 4. Skipped (295), by reason

| Reason | Count | Examples |
|---|---:|---|
| Cloud platform not used (AWS, Azure/Microsoft, Google Cloud/Firebase, Oracle/OCI) | 80 | `aws-*`, `azure-*`, `entra-*`, `bigquery-*`, `gcp-*`, `oci-*`, `gemini-api` (targets Vertex AI; the code calls the AI Studio endpoint) |
| Data platform, ETL, orchestration, lakehouse, catalog, or BI tool not used | 74 | Airflow, Dagster, Prefect, dbt, Beam, Flink, NiFi, Airbyte, Fivetran, Databricks, Snowflake, Spark, Hudi, Tableau, Looker, Power BI, `kafka-schema-registry` |
| Datastore or data format not used | 24 | Cassandra, MongoDB, MySQL, Redis, Elasticsearch, Db2, Neon, Supabase, ADBC, Arrow, CSV tools |
| Frontend or Node.js tooling (the UI is one inline `HTMLResponse`) | 20 | All 10 Angular skills, GraphQL, React/Vercel, Figma, the Frontend Specialist agent |
| Redundant with Kilo built-ins, remote sandboxes, scraping services, notebooks | 15 | `filesystem`, `git`, `time`, E2B, Riza, Firecrawl, Apify, Jupyter, nteract, the Data agent |
| Observability vendor not used (Prometheus + OpenTelemetry) | 14 | Datadog, New Relic, Splunk, Sentry, Grafana Cloud, Axiom |
| Specific mismatch with this repo | 13 | Archived Postgres/Puppeteer/SQLite servers; Qdrant MCP (a memory store that writes its own collections, not an inspector for `news`); OpenAPI MCP (refuses loopback targets, and the gateway is local); Composer (live trading, kept away from the paper-only execution path); Agent Md Refactor (`AGENTS.md` is 91 lines) |
| ML platform or training framework not used | 12 | MLflow, DataRobot, PyTorch, TensorFlow, scikit-learn |
| SaaS or productivity tool not used (the board lives in `PROJECT_BOARD.md`) | 12 | Jira/Confluence, Linear, Notion, Slack, ClickUp, Google Workspace, Stripe |
| Business, creative, or content work, not code | 12 | Canvas Design, Competitive Ads Extractor, Internal Comms, YouTube Downloader |
| Unrelated tool or marketplace test fixture | 12 | IDA Pro, Laravel Boost, Cloudflare, GitLab, the companion smoke test |
| Legacy modes | 7 | Same seven roles as the agents |

---

## 5. Gap: nothing covers the core of this repo

No entry in the whole catalog targets quant research, backtesting, pandas, or pytest. Nothing
touches:

- the 445 factor implementations in [`factors/zoo/`](../arthaai/factors/zoo/) (Alpha101, GTJA191, Qlib158)
- the walk-forward backtest and its look-ahead guards in [`backtest/engine.py`](../arthaai/backtest/engine.py)
- fractional Kelly sizing in [`agents/asset_manager.py`](../arthaai/agents/asset_manager.py)
- the execution guardrails in [`execution/`](../arthaai/execution/)

The highest-value next step is to write project-specific skills with **Skill Creator**, for example:

1. **add-factor**: register a factor and add its look-ahead test next to the existing ones in `tests/`.
2. **run-e3-sweep**: run a sweep the way [`E3_EVALUATION_PROTOCOL.md`](../E3_EVALUATION_PROTOCOL.md)
   requires (including `--limit 3100`) and record the result in `evaluation/e3_results.md`.
3. **backtest-review**: a checklist for changes to `backtest/` and `execution/`, for Code Skeptic to use.

---

## Appendix — all 336 entries

Sorted by verdict, then type, then name. `id` is the folder or item id in the marketplace repo.

| # | Type | Entry | Verdict | Reason |
|---|---|---|---|---|
| 1 | Agent | Architect (`architect`) | ✅ Install | Design and migration planning against `SPEC.md`; writes only to `.kilo/plans/*.md` |
| 2 | Agent | Code Reviewer (`code-reviewer`) | ✅ Install | Read + bash, no edits: safe reviewer for backtest, execution, and gateway changes |
| 3 | Agent | Code Skeptic (`code-skeptic`) | ✅ Install | Adversarial review of look-ahead guards and execution guardrails; edits only `.md` |
| 4 | Agent | Documentation Specialist (`docs-specialist`) | ✅ Install | Doc-heavy repo; can edit `.md` but not the `.html` docs or `likec4/` files |
| 5 | Agent | Test Engineer (`test-engineer`) | ✅ Install | 63 pytest files, but its edit allowlist is JS/TS test globs only; add `tests/test_*.py` |
| 6 | MCP | Context7 (`context7`) | ✅ Install | Current docs for LangGraph, qdrant-client, confluent-kafka, OpenBB, nautilus_trader, alpaca-py |
| 7 | MCP | GitHub (`github`) | ✅ Install | Repo and CI live on GitHub (Actions quality gates, PRs); official read-only Docker variant |
| 8 | MCP | Postgres MCP Pro (`postgres-mcp-pro`) | ✅ Install | TimescaleDB (Postgres 16): schema, EXPLAIN plans, index and health checks; restricted read-only by default |
| 9 | Skill | Data Investigation (`data-investigation`) | ✅ Install | E3 sweep analysis: explaining result changes, validating signal hypotheses |
| 10 | Skill | Fastapi Itechmeat (`fastapi-itechmeat`) | ✅ Install | Gateway: FastAPI + Pydantic + OAuth2/JWT, matches `gateway/auth.py` |
| 11 | Skill | Supabase Postgres Best Practices (`supabase-postgres-best-practices`) | ✅ Install | Query/schema/index review for `db/timescale.py` (generic Postgres, not TimescaleDB-specific) |
| 12 | Skill | Vault Api (`vault-api`) | ✅ Install | `security/vault.py` calls the Vault KV v2 REST API directly via httpx |
| 13 | Agent | Code Simplifier (`code-simplifier`) | ⚠️ Conditional | Full edit rights; keep it out of the generated `factors/zoo/` and run the tests after |
| 14 | MCP | Confluent MCP Server (`confluent`) | ⚠️ Conditional | When debugging the Redpanda consumer in `data/consumer.py`; Kafka-API tools only (untested against Redpanda) |
| 15 | MCP | Exa Search (`exa`) | ⚠️ Conditional | Web search for research during development; not for the news pipeline (free-data goal) |
| 16 | MCP | GitMCP (`git-mcp`) | ⚠️ Conditional | Check factor definitions against upstream repos, e.g. microsoft/qlib for Qlib158 |
| 17 | MCP | Grafana MCP (Local) (`mcp-grafana`) | ⚠️ Conditional | Only once Grafana is added to compose |
| 18 | MCP | HashiCorp Vault MCP Server (`vault-mcp`) | ⚠️ Conditional | Read-only Vault inspection; only with a token scoped to approved paths, never real API keys |
| 19 | MCP | Knowledge Graph Memory (`memory`) | ⚠️ Conditional | Workflow preference: persistent knowledge graph across sessions |
| 20 | MCP | MotherDuck (`motherduck`) | ⚠️ Conditional | Local-DuckDB mode can inspect the IBOR DuckDB file used by `data/ibor.py` |
| 21 | MCP | Nia (`nia`) | ⚠️ Conditional | Library docs plus research papers for factor research; needs an account |
| 22 | MCP | Playwright (`playwright`) | ⚠️ Conditional | Browser checks of the gateway UI at `:8000` and the HTML docs |
| 23 | MCP | Sequential Thinking (`sequentialthinking`) | ⚠️ Conditional | Workflow preference: structured step-by-step reasoning |
| 24 | Skill | Changelog Generator (`changelog-generator`) | ⚠️ Conditional | Once releases start; there is no CHANGELOG yet |
| 25 | Skill | Chdb Datastore (`chdb-datastore`) | ⚠️ Conditional | Only if factor computation becomes a measured bottleneck; bottleneck already covers rolling ops |
| 26 | Skill | Create Pull Request (`create-pull-request`) | ⚠️ Conditional | When opening the `feat/arthaai-core` → `main` PR |
| 27 | Skill | Dashboarding (`dashboarding`) | ⚠️ Conditional | Only once Grafana is added to compose |
| 28 | Skill | Grilling (`grilling`) | ⚠️ Conditional | Workflow preference: interview-style plan stress test; overlaps the Architect agent |
| 29 | Skill | Langsmith Fetch (`langsmith-fetch`) | ⚠️ Conditional | Only if LangSmith tracing is enabled for the LangGraph pipeline (it is not today) |
| 30 | Skill | Ponytail (`ponytail`) | ⚠️ Conditional | Workflow preference: minimal-solution mode |
| 31 | Skill | Prometheus Addxai (`prometheus-addxai`) | ⚠️ Conditional | Only once a Prometheus server scrapes the gateway `/metrics` endpoint (none in compose) |
| 32 | Skill | Secrets Vault Manager (`secrets-vault-manager`) | ⚠️ Conditional | When rotation or production secret management work starts (Vault is dev-mode today) |
| 33 | Skill | Skill Creator (`skill-creator`) | ⚠️ Conditional | To write the missing ArthaAI-specific skills (factor, backtest, E3 sweep) |
| 34 | Skill | Web Design Guidelines (`web-design-guidelines`) | ⚠️ Conditional | Only for reviewing the gateway UI or the HTML docs |
| 35 | Plugin | Models Discovery (`opencode-models-discovery`) | ⚠️ Conditional | Only to let Kilo use the same OpenAI-compatible local server as ArthaAI's `local` LLM provider |
| 36 | MCP | Brave Search (`brave-search`) | ↔️ Alternative | Overlaps Exa; install one search MCP |
| 37 | MCP | DBHub (`dbhub`) | ↔️ Alternative | Overlaps Postgres MCP Pro; DBHub is multi-database, Pro is Postgres-specific |
| 38 | MCP | Kagi Search (`kagi`) | ↔️ Alternative | Overlaps Exa; install one search MCP |
| 39 | MCP | Tavily (`tavily`) | ↔️ Alternative | Overlaps Exa; install one search MCP |
| 40 | Skill | Fastapi Martinholovsky (`fastapi-martinholovsky`) | ↔️ Alternative | Overlaps Fastapi Itechmeat; install one |
| 41 | Skill | Webapp Testing (`webapp-testing`) | ↔️ Alternative | Overlaps the Playwright MCP; install one |
| 42 | Agent | Data (`data`) | ❌ Skip | Notebook-first; the repo has no notebooks and E3 analysis is CLI-driven |
| 43 | Agent | Frontend Specialist (`frontend-specialist`) | ❌ Skip | React/TS/CSS edit scope; the UI is inline HTML inside a `.py` file |
| 44 | MCP | Airbyte Agent MCP (`airbyte-agent-mcp`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 45 | MCP | Airbyte Knowledge MCP (`airbyte-knowledge-mcp`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 46 | MCP | Amazon Keyspaces MCP (`amazon-keyspaces-mcp`) | ❌ Skip | Cloud not used (AWS) |
| 47 | MCP | Amazon Kinesis MCP (`awslabs-kinesis-mcp-server`) | ❌ Skip | Cloud not used (AWS) |
| 48 | MCP | Amazon Redshift MCP (`aws-redshift-mcp`) | ❌ Skip | Cloud not used (AWS) |
| 49 | MCP | Anaconda MCP (`anaconda`) | ❌ Skip | Unrelated tool or platform |
| 50 | MCP | Apify Actors (`apify`) | ❌ Skip | Scraping service; news ingest already uses feedparser + trafilatura (free-data goal) |
| 51 | MCP | Astronomer Docs MCP (`astronomer-docs-mcp`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 52 | MCP | Atlassian (`atlassian`) | ❌ Skip | SaaS / productivity tool not used; the board lives in `PROJECT_BOARD.md` |
| 53 | MCP | AWS API MCP (`aws-api-mcp`) | ❌ Skip | Cloud not used (AWS) |
| 54 | MCP | AWS Data Processing MCP (`aws-data-processing`) | ❌ Skip | Cloud not used (AWS) |
| 55 | MCP | AWS Knowledge Base (`aws-kb-retrieval-server`) | ❌ Skip | Cloud not used (AWS) |
| 56 | MCP | AWS Managed MCP Server (`aws`) | ❌ Skip | Cloud not used (AWS) |
| 57 | MCP | AWS S3 Tables MCP Server (`s3-tables-mcp`) | ❌ Skip | Cloud not used (AWS) |
| 58 | MCP | AWS Serverless MCP (`aws-serverless-mcp`) | ❌ Skip | Cloud not used (AWS) |
| 59 | MCP | Axiom (`axiom`) | ❌ Skip | Observability vendor not used (Prometheus + OpenTelemetry) |
| 60 | MCP | Azure DevOps (`azure-devops`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 61 | MCP | Azure MCP Server (`azure`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 62 | MCP | BigQuery Remote MCP (`bigquery-mcp`) | ❌ Skip | Cloud not used (Google Cloud / Firebase) |
| 63 | MCP | Browserbase (`browserbase`) | ❌ Skip | Scraping service; news ingest already uses feedparser + trafilatura (free-data goal) |
| 64 | MCP | ClickUp (`clickup`) | ❌ Skip | SaaS / productivity tool not used; the board lives in `PROJECT_BOARD.md` |
| 65 | MCP | Cloudera NiFi MCP Server (`nifi-mcp-server`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 66 | MCP | Cloudflare (`cloudflare`) | ❌ Skip | Unrelated tool or platform |
| 67 | MCP | Code Interpreter (`e2b`) | ❌ Skip | Remote code sandbox; tests run locally and in CI |
| 68 | MCP | Codegen (`codegen`) | ❌ Skip | Redundant with Kilo's built-in file, git, and terminal tools |
| 69 | MCP | Companion Smoke Test (`companion-smoke-test`) | ❌ Skip | Unrelated tool or platform |
| 70 | MCP | Composer (`composer-trade`) | ❌ Skip | External strategy + live-trading platform; keep it away from the paper-only execution path |
| 71 | MCP | Databricks SQL Managed MCP (`databricks-sql`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 72 | MCP | Databricks Unity Catalog Functions MCP (`unity-catalog-functions`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 73 | MCP | Datadog Managed MCP (`datadog-mcp-datadoghq`) | ❌ Skip | Observability vendor not used (Prometheus + OpenTelemetry) |
| 74 | MCP | DataHub Managed MCP (`datahub-mcp`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 75 | MCP | Datalayer Jupyter MCP (Local stdio) (`jupyter-mcp`) | ❌ Skip | The repo has no notebooks |
| 76 | MCP | DataRobot Global MCP (`datarobot-global-mcp`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 77 | MCP | Dbt (`dbt`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 78 | MCP | Elastic Agent Builder MCP (`elastic-agent-builder-mcp`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 79 | MCP | eSignatures (`esignatures`) | ❌ Skip | SaaS / productivity tool not used; the board lives in `PROJECT_BOARD.md` |
| 80 | MCP | Figma Dev Mode (`figma-dev-mode`) | ❌ Skip | Unrelated tool or platform |
| 81 | MCP | File System (`filesystem`) | ❌ Skip | Redundant with Kilo's built-in file, git, and terminal tools |
| 82 | MCP | Firebase (`firebase`) | ❌ Skip | Cloud not used (Google Cloud / Firebase) |
| 83 | MCP | Firecrawl (`firecrawl`) | ❌ Skip | Scraping service; news ingest already uses feedparser + trafilatura (free-data goal) |
| 84 | MCP | Fireproof (`fireproof`) | ❌ Skip | Datastore not used |
| 85 | MCP | Fivetran MCP Server (Official) (`fivetran-mcp-server`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 86 | MCP | Gemini Enterprise Agent Platform MCP (`agent-platform-mcp`) | ❌ Skip | Cloud not used (Google Cloud / Firebase) |
| 87 | MCP | Genkit Integration (`genkit`) | ❌ Skip | Cloud not used (Google Cloud / Firebase) |
| 88 | MCP | Git Tools (`git`) | ❌ Skip | Redundant with Kilo's built-in file, git, and terminal tools |
| 89 | MCP | GitLab (`gitlab`) | ❌ Skip | Unrelated tool or platform |
| 90 | MCP | Google Cloud Data Lineage MCP (`data-lineage-mcp`) | ❌ Skip | Cloud not used (Google Cloud / Firebase) |
| 91 | MCP | Google Cloud Knowledge Catalog MCP (`knowledge-catalog-mcp`) | ❌ Skip | Cloud not used (Google Cloud / Firebase) |
| 92 | MCP | Google Cloud Pub/Sub Remote MCP (`gcp-pubsub`) | ❌ Skip | Cloud not used (Google Cloud / Firebase) |
| 93 | MCP | Google Drive (`gdrive`) | ❌ Skip | SaaS / productivity tool not used; the board lives in `PROJECT_BOARD.md` |
| 94 | MCP | Google Maps (`google-maps`) | ❌ Skip | Cloud not used (Google Cloud / Firebase) |
| 95 | MCP | Google Maps Platform Code Assist (`google-maps-platform-code-assist`) | ❌ Skip | Cloud not used (Google Cloud / Firebase) |
| 96 | MCP | Google Workspace (`google-workspace`) | ❌ Skip | SaaS / productivity tool not used; the board lives in `PROJECT_BOARD.md` |
| 97 | MCP | Grafana Cloud Managed MCP (`grafana-cloud-mcp`) | ❌ Skip | Observability vendor not used (Prometheus + OpenTelemetry) |
| 98 | MCP | HCP Vault Radar MCP Server (`vault-radar-mcp`) | ❌ Skip | Unrelated tool or platform |
| 99 | MCP | IDA Pro (`ida-pro`) | ❌ Skip | Unrelated tool or platform |
| 100 | MCP | Jupyter AI MCP (`jupyter`) | ❌ Skip | The repo has no notebooks |
| 101 | MCP | Kubeflow Spark History Server MCP (`spark-history`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 102 | MCP | Kubernetes Observer (`metoro`) | ❌ Skip | Observability vendor not used (Prometheus + OpenTelemetry) |
| 103 | MCP | Laravel Boost (`laravel-boost`) | ❌ Skip | Unrelated tool or platform |
| 104 | MCP | Linear (`linear`) | ❌ Skip | SaaS / productivity tool not used; the board lives in `PROJECT_BOARD.md` |
| 105 | MCP | Looker MCP Toolbox (`looker-toolbox`) | ❌ Skip | Cloud not used (Google Cloud / Firebase) |
| 106 | MCP | Matillion MCP Server (`matillion`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 107 | MCP | Membrane Cloud MCP (`membrane-cloud-mcp`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 108 | MCP | Microsoft Learn (`microsoft-learn`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 109 | MCP | Microsoft SQL MCP Server (`microsoft-data-api-builder`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 110 | MCP | MLflow MCP (Official) (`mlflow-mcp`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 111 | MCP | MongoDB MCP Server (`mongodb-mcp-server`) | ❌ Skip | Datastore not used |
| 112 | MCP | n8n-MCP (`n8n-mcp`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 113 | MCP | Needle Search (`needle`) | ❌ Skip | SaaS / productivity tool not used; the board lives in `PROJECT_BOARD.md` |
| 114 | MCP | Neon Database (`neon`) | ❌ Skip | Datastore not used |
| 115 | MCP | New Relic AI MCP (Official Remote) (`new-relic-ai-mcp`) | ❌ Skip | Observability vendor not used (Prometheus + OpenTelemetry) |
| 116 | MCP | Notion (`notion`) | ❌ Skip | SaaS / productivity tool not used; the board lives in `PROJECT_BOARD.md` |
| 117 | MCP | nteract MCP (`nteract`) | ❌ Skip | The repo has no notebooks |
| 118 | MCP | OCI Database Tools Managed MCP (`oci-database-tools-mcp`) | ❌ Skip | Cloud not used (Oracle / OCI) |
| 119 | MCP | Okta MCP Server (Official) (`okta-mcp-server`) | ❌ Skip | Unrelated tool or platform |
| 120 | MCP | OpenAPI MCP Server (`openapi-mcp`) | ❌ Skip | Refuses loopback/private targets by default; the gateway runs on localhost |
| 121 | MCP | OpenMetadata MCP (Community Full CRUD) (`openmetadata-us-all`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 122 | MCP | OpenMetadata MCP (Embedded) (`openmetadata-mcp`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 123 | MCP | Oracle OCI CLI MCP Server (`oci-api-mcp`) | ❌ Skip | Cloud not used (Oracle / OCI) |
| 124 | MCP | Oracle OCI Cloud MCP Server (`oci-cloud-mcp`) | ❌ Skip | Cloud not used (Oracle / OCI) |
| 125 | MCP | Oracle SQLcl MCP Server (`oracle-sqlcl-mcp`) | ❌ Skip | Cloud not used (Oracle / OCI) |
| 126 | MCP | Oxylabs Scraper (`oxylabs`) | ❌ Skip | Scraping service; news ingest already uses feedparser + trafilatura (free-data goal) |
| 127 | MCP | PostgreSQL Reader (`postgres`) | ❌ Skip | Archived upstream (modelcontextprotocol/servers-archived); use Postgres MCP Pro |
| 128 | MCP | Postgrest (`postgrest`) | ❌ Skip | Datastore not used |
| 129 | MCP | Power BI Modeling MCP (Local) (`power-bi-modeling`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 130 | MCP | Power BI Remote MCP (`power-bi-remote`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 131 | MCP | Prefect MCP Server (`prefect-mcp-server`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 132 | MCP | Puppeteer (`puppeteer`) | ❌ Skip | Archived upstream; use the Playwright MCP |
| 133 | MCP | Qdrant (`qdrant`) | ❌ Skip | A memory store that writes its own collections; not an inspector for the existing `news` collection |
| 134 | MCP | Qlik Cloud MCP (Official Remote) (`qlik-mcp`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 135 | MCP | Raygun (`raygun`) | ❌ Skip | Observability vendor not used (Prometheus + OpenTelemetry) |
| 136 | MCP | Redis (`redis`) | ❌ Skip | Datastore not used |
| 137 | MCP | Redis Cloud Administration MCP (`redis-cloud-mcp`) | ❌ Skip | Datastore not used |
| 138 | MCP | Redis Data MCP (Official) (`redis-mcp`) | ❌ Skip | Datastore not used |
| 139 | MCP | Riza (`riza`) | ❌ Skip | Remote code sandbox; tests run locally and in CI |
| 140 | MCP | SageMaker Unified Studio Spark Troubleshooting MCP (`sagemaker-spark-troubleshooting-mcp`) | ❌ Skip | Cloud not used (AWS) |
| 141 | MCP | Sentry (`sentry`) | ❌ Skip | Observability vendor not used (Prometheus + OpenTelemetry) |
| 142 | MCP | Slack (`slack`) | ❌ Skip | SaaS / productivity tool not used; the board lives in `PROJECT_BOARD.md` |
| 143 | MCP | Smartsheet (`smartsheet`) | ❌ Skip | SaaS / productivity tool not used; the board lives in `PROJECT_BOARD.md` |
| 144 | MCP | Snowflake-Managed MCP Server (`snowflake-managed`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 145 | MCP | Splunk MCP Server (Official) (`splunk-mcp-server`) | ❌ Skip | Observability vendor not used (Prometheus + OpenTelemetry) |
| 146 | MCP | SQLite (`sqlite`) | ❌ Skip | Archived upstream, and no SQLite in the stack |
| 147 | MCP | Stripe (`stripe`) | ❌ Skip | SaaS / productivity tool not used; the board lives in `PROJECT_BOARD.md` |
| 148 | MCP | Supabase (`supabase`) | ❌ Skip | Datastore not used |
| 149 | MCP | Tableau MCP (Official) (`tableau-mcp`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 150 | MCP | Time (`time`) | ❌ Skip | Redundant with Kilo's built-in file, git, and terminal tools |
| 151 | MCP | Unstructured Transform MCP (`transform-mcp`) | ❌ Skip | SaaS / productivity tool not used; the board lives in `PROJECT_BOARD.md` |
| 152 | MCP | Verodat (`verodat`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 153 | MCP | WatsonX Flows (`watsonx`) | ❌ Skip | Data platform / ETL / catalog / BI tool not used |
| 154 | MCP | YouTube Subtitles (`youtube`) | ❌ Skip | Unrelated tool or platform |
| 155 | Skill | Adbc (`adbc`) | ❌ Skip | Datastore not used (TimescaleDB via psycopg, Qdrant, DuckDB only) |
| 156 | Skill | Adf Master (`adf-master`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 157 | Skill | Agent Md Refactor (`agent-md-refactor`) | ❌ Skip | `AGENTS.md` is 91 lines; nothing to split |
| 158 | Skill | Aidp Object Storage (`aidp-object-storage`) | ❌ Skip | Cloud not used (Oracle / OCI) |
| 159 | Skill | Airbyte Agent (`airbyte-agent`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 160 | Skill | Airflow (`airflow`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 161 | Skill | Anaconda Intelligence (`anaconda-intelligence`) | ❌ Skip | The env is venv + pip, not conda |
| 162 | Skill | Angular Component (`angular-component`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 163 | Skill | Angular Di (`angular-di`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 164 | Skill | Angular Directives (`angular-directives`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 165 | Skill | Angular Forms (`angular-forms`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 166 | Skill | Angular Http (`angular-http`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 167 | Skill | Angular Routing (`angular-routing`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 168 | Skill | Angular Signals (`angular-signals`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 169 | Skill | Angular Ssr (`angular-ssr`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 170 | Skill | Angular Testing (`angular-testing`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 171 | Skill | Angular Tooling (`angular-tooling`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 172 | Skill | Aoti Debug (`aoti-debug`) | ❌ Skip | ML platform / training framework not used (sentiment runs inference only; statsmodels for research) |
| 173 | Skill | Apache Arrow (`apache-arrow`) | ❌ Skip | No Arrow / CSV pipelines; data flows as pandas frames and DuckDB |
| 174 | Skill | Apache Hudi Lakehouse (`apache-hudi-lakehouse`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 175 | Skill | Apollo Graphql (`apollo-graphql`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 176 | Skill | Artifacts Builder (`artifacts-builder`) | ❌ Skip | Business / creative / content task, not code |
| 177 | Skill | Authoring Dags (`authoring-dags`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 178 | Skill | Aws Cognito Admin (`aws-cognito-admin`) | ❌ Skip | Cloud not used (AWS); the stack runs on local Docker |
| 179 | Skill | Aws Messaging And Streaming (`aws-messaging-and-streaming`) | ❌ Skip | Cloud not used (AWS); the stack runs on local Docker |
| 180 | Skill | Aws Sdk Python Usage (`aws-sdk-python-usage`) | ❌ Skip | Cloud not used (AWS); the stack runs on local Docker |
| 181 | Skill | Azure Compliance (`azure-compliance`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 182 | Skill | Azure Data Factory (`azure-data-factory`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 183 | Skill | Azure Data Share (`azure-data-share`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 184 | Skill | Azure Databricks (`azure-databricks`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 185 | Skill | Azure Event Hubs (`azure-event-hubs`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 186 | Skill | Azure Eventhub Py (`azure-eventhub-py`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 187 | Skill | Azure Key Vault (`azure-key-vault`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 188 | Skill | Azure Machine Learning (`azure-machine-learning`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 189 | Skill | Azure Rbac (`azure-rbac`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 190 | Skill | Azure Storage (`azure-storage`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 191 | Skill | Azure Synapse Analytics (`azure-synapse-analytics`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 192 | Skill | Azureml Scaffolding (`azureml-scaffolding`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 193 | Skill | Beam Concepts (`beam-concepts`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 194 | Skill | Bigquery Ai Ml (`bigquery-ai-ml`) | ❌ Skip | Cloud not used (Google Cloud) |
| 195 | Skill | Bigquery Basics (`bigquery-basics`) | ❌ Skip | Cloud not used (Google Cloud) |
| 196 | Skill | Bootstrapping Agent (`bootstrapping-agent`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 197 | Skill | Build Connector (`build-connector`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 198 | Skill | Canvas Design (`canvas-design`) | ❌ Skip | Business / creative / content task, not code |
| 199 | Skill | Cassandra (`cassandra`) | ❌ Skip | Datastore not used (TimescaleDB via psycopg, Qdrant, DuckDB only) |
| 200 | Skill | Cdc Streaming Pipeline (`cdc-streaming-pipeline`) | ❌ Skip | Cloud not used (AWS); the stack runs on local Docker |
| 201 | Skill | Cheerio Parsing (`cheerio-parsing`) | ❌ Skip | Node.js tooling; the codebase is Python |
| 202 | Skill | Cognito (`cognito`) | ❌ Skip | Cloud not used (AWS); the stack runs on local Docker |
| 203 | Skill | Collibra Chip (`collibra-chip`) | ❌ Skip | Data-quality / catalog framework not used; the repo has its own `research/data_quality.py` |
| 204 | Skill | Companion Smoke Guide (`companion-smoke-guide`) | ❌ Skip | Marketplace test fixture |
| 205 | Skill | Competitive Ads Extractor (`competitive-ads-extractor`) | ❌ Skip | Business / creative / content task, not code |
| 206 | Skill | Connecting To Data Source (`connecting-to-data-source`) | ❌ Skip | Cloud not used (AWS); the stack runs on local Docker |
| 207 | Skill | Content Research Writer (`content-research-writer`) | ❌ Skip | Business / creative / content task, not code |
| 208 | Skill | Cortex Code (`cortex-code`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 209 | Skill | Creating Data Lake Table (`creating-data-lake-table`) | ❌ Skip | Cloud not used (AWS); the stack runs on local Docker |
| 210 | Skill | Creating Secrets Using Best Practices (`creating-secrets-using-best-practices`) | ❌ Skip | Cloud not used (AWS); the stack runs on local Docker |
| 211 | Skill | Csv Query (`csv-query`) | ❌ Skip | No Arrow / CSV pipelines; data flows as pandas frames and DuckDB |
| 212 | Skill | Csv Wrangling (`csv-wrangling`) | ❌ Skip | No Arrow / CSV pipelines; data flows as pandas frames and DuckDB |
| 213 | Skill | Dagster (`dagster`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 214 | Skill | Dagster Expert (`dagster-expert`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 215 | Skill | Data Catalog And Discovery (`data-catalog-and-discovery`) | ❌ Skip | Data-quality / catalog framework not used; the repo has its own `research/data_quality.py` |
| 216 | Skill | Data Distributed Storage (`data-distributed-storage`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 217 | Skill | Data Quality Frameworks Sickn33 (`data-quality-frameworks-sickn33`) | ❌ Skip | Data-quality / catalog framework not used; the repo has its own `research/data_quality.py` |
| 218 | Skill | Database Observability (`database-observability`) | ❌ Skip | Observability vendor not used (Prometheus + OpenTelemetry) |
| 219 | Skill | Database Redshift (`database-redshift`) | ❌ Skip | Cloud not used (AWS); the stack runs on local Docker |
| 220 | Skill | Databricks Core (`databricks-core`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 221 | Skill | Databricks Dbsql (`databricks-dbsql`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 222 | Skill | Databricks Jobs (`databricks-jobs`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 223 | Skill | Databricks Model Serving (`databricks-model-serving`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 224 | Skill | Databricks Pipelines (`databricks-pipelines`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 225 | Skill | Databricks Spark Structured Streaming (`databricks-spark-structured-streaming`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 226 | Skill | Databricks Unity Catalog (`databricks-unity-catalog`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 227 | Skill | Dataplex And Bigquery Governance (`dataplex-and-bigquery-governance`) | ❌ Skip | Cloud not used (Google Cloud) |
| 228 | Skill | Datarobot Data Preparation (`datarobot-data-preparation`) | ❌ Skip | ML platform / training framework not used (sentiment runs inference only; statsmodels for research) |
| 229 | Skill | Datarobot Feature Engineering (`datarobot-feature-engineering`) | ❌ Skip | ML platform / training framework not used (sentiment runs inference only; statsmodels for research) |
| 230 | Skill | Dataset Evaluation (`dataset-evaluation`) | ❌ Skip | ML platform / training framework not used (sentiment runs inference only; statsmodels for research) |
| 231 | Skill | Dataset Transformation (`dataset-transformation`) | ❌ Skip | ML platform / training framework not used (sentiment runs inference only; statsmodels for research) |
| 232 | Skill | Db2 Rhel (`db2-rhel`) | ❌ Skip | Datastore not used (TimescaleDB via psycopg, Qdrant, DuckDB only) |
| 233 | Skill | Dbt (`dbt`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 234 | Skill | Dbt Analytics Engineering (`dbt-analytics-engineering`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 235 | Skill | Dbt Migration (`dbt-migration`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 236 | Skill | Dbt Testing (`dbt-testing`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 237 | Skill | Dd Logs (`dd-logs`) | ❌ Skip | Observability vendor not used (Prometheus + OpenTelemetry) |
| 238 | Skill | Dd Pup (`dd-pup`) | ❌ Skip | Observability vendor not used (Prometheus + OpenTelemetry) |
| 239 | Skill | Delta Sharing (`delta-sharing`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 240 | Skill | Deploy To Vercel (`deploy-to-vercel`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 241 | Skill | Deploying Airflow (`deploying-airflow`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 242 | Skill | Domain Name Brainstormer (`domain-name-brainstormer`) | ❌ Skip | Business / creative / content task, not code |
| 243 | Skill | Dynamic Tables Tutorial (`dynamic-tables-tutorial`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 244 | Skill | Elasticsearch Esql (`elasticsearch-esql`) | ❌ Skip | Datastore not used (TimescaleDB via psycopg, Qdrant, DuckDB only) |
| 245 | Skill | Elasticsearch File Ingest (`elasticsearch-file-ingest`) | ❌ Skip | Datastore not used (TimescaleDB via psycopg, Qdrant, DuckDB only) |
| 246 | Skill | Entra Agent Id (`entra-agent-id`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 247 | Skill | Entra App Registration (`entra-app-registration`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 248 | Skill | Etl Integration Nifi (`etl-integration-nifi`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 249 | Skill | Exploring Data Catalog (`exploring-data-catalog`) | ❌ Skip | Cloud not used (AWS); the stack runs on local Docker |
| 250 | Skill | Figma Implement Design (`figma-implement-design`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 251 | Skill | Flink (`flink`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 252 | Skill | Flink Best Practices (`flink-best-practices`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 253 | Skill | Frontend Design (`frontend-design`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 254 | Skill | Gcloud (`gcloud`) | ❌ Skip | Cloud not used (Google Cloud) |
| 255 | Skill | Gcp Event Driven Architecture Review (`gcp-event-driven-architecture-review`) | ❌ Skip | Cloud not used (Google Cloud) |
| 256 | Skill | Gcp Iam (`gcp-iam`) | ❌ Skip | Cloud not used (Google Cloud) |
| 257 | Skill | Gcp Secret Manager (`gcp-secret-manager`) | ❌ Skip | Cloud not used (Google Cloud) |
| 258 | Skill | Gcs Lifecycle Policy (`gcs-lifecycle-policy`) | ❌ Skip | Cloud not used (Google Cloud) |
| 259 | Skill | Gemini Api (`gemini-api`) | ❌ Skip | Targets Vertex AI; `master_llm._gemini` calls the AI Studio REST endpoint |
| 260 | Skill | Glue Diagnostics (`glue-diagnostics`) | ❌ Skip | Cloud not used (AWS); the stack runs on local Docker |
| 261 | Skill | Graphql (`graphql`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 262 | Skill | Hadoop (`hadoop`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 263 | Skill | Hbase (`hbase`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 264 | Skill | Image Enhancer (`image-enhancer`) | ❌ Skip | Business / creative / content task, not code |
| 265 | Skill | Ingesting Into Data Lake (`ingesting-into-data-lake`) | ❌ Skip | Cloud not used (AWS); the stack runs on local Docker |
| 266 | Skill | Integrate Anything (`integrate-anything`) | ❌ Skip | Membrane CLI integrations; not used |
| 267 | Skill | Internal Comms (`internal-comms`) | ❌ Skip | Business / creative / content task, not code |
| 268 | Skill | Io Connectors (`io-connectors`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 269 | Skill | Jq Json Processing (`jq-json-processing`) | ❌ Skip | JSON handling is in Python; no shell JSON pipelines |
| 270 | Skill | Jupyter Notebook (`jupyter-notebook`) | ❌ Skip | The repo has no notebooks |
| 271 | Skill | Kafka Schema Registry (`kafka-schema-registry`) | ❌ Skip | Generates Confluent Terraform; the Redpanda consumer uses no registered schemas |
| 272 | Skill | Kafka Streams Programming (`kafka-streams-programming`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 273 | Skill | Knowledge Catalog Discovery (`knowledge-catalog-discovery`) | ❌ Skip | Cloud not used (Google Cloud) |
| 274 | Skill | Lead Research Assistant (`lead-research-assistant`) | ❌ Skip | Business / creative / content task, not code |
| 275 | Skill | Lookml Model (`lookml-model`) | ❌ Skip | BI tool not used |
| 276 | Skill | Lookml Tests (`lookml-tests`) | ❌ Skip | BI tool not used |
| 277 | Skill | Mcp Builder (`mcp-builder`) | ❌ Skip | No MCP server is in scope |
| 278 | Skill | Meeting Insights Analyzer (`meeting-insights-analyzer`) | ❌ Skip | Business / creative / content task, not code |
| 279 | Skill | Microsoft Code Reference (`microsoft-code-reference`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 280 | Skill | Microsoft Docs (`microsoft-docs`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 281 | Skill | Mlflow Onboarding (`mlflow-onboarding`) | ❌ Skip | ML platform / training framework not used (sentiment runs inference only; statsmodels for research) |
| 282 | Skill | Mongodb Query Optimizer (`mongodb-query-optimizer`) | ❌ Skip | Datastore not used (TimescaleDB via psycopg, Qdrant, DuckDB only) |
| 283 | Skill | Mongodb Schema Design (`mongodb-schema-design`) | ❌ Skip | Datastore not used (TimescaleDB via psycopg, Qdrant, DuckDB only) |
| 284 | Skill | Mysql (`mysql`) | ❌ Skip | Datastore not used (TimescaleDB via psycopg, Qdrant, DuckDB only) |
| 285 | Skill | Mysql Patterns (`mysql-patterns`) | ❌ Skip | Datastore not used (TimescaleDB via psycopg, Qdrant, DuckDB only) |
| 286 | Skill | Neon Postgres (`neon-postgres`) | ❌ Skip | Datastore not used (TimescaleDB via psycopg, Qdrant, DuckDB only) |
| 287 | Skill | Newrelic Cli Skills (`newrelic-cli-skills`) | ❌ Skip | Observability vendor not used (Prometheus + OpenTelemetry) |
| 288 | Skill | Nifi Flow Layout (`nifi-flow-layout`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 289 | Skill | Okta Identity Integration Patterns (`okta-identity-integration-patterns`) | ❌ Skip | Auth is the gateway's own JWT + mTLS; no Okta |
| 290 | Skill | Oleander Iceberg Catalog (`oleander-iceberg-catalog`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 291 | Skill | Oracle Database (`oracle-database`) | ❌ Skip | Cloud not used (Oracle / OCI) |
| 292 | Skill | Oraclecloud Data Handling (`oraclecloud-data-handling`) | ❌ Skip | Cloud not used (Oracle / OCI) |
| 293 | Skill | Oracledb (`oracledb`) | ❌ Skip | Cloud not used (Oracle / OCI) |
| 294 | Skill | Powerbi Documentation (`powerbi-documentation`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 295 | Skill | Powerbi Mcp (`powerbi-mcp`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 296 | Skill | Prefect (`prefect`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 297 | Skill | Purview Data Catalog (`purview-data-catalog`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 298 | Skill | Purview Data Map (`purview-data-map`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 299 | Skill | Pytorch Patterns (`pytorch-patterns`) | ❌ Skip | ML platform / training framework not used (sentiment runs inference only; statsmodels for research) |
| 300 | Skill | Qlik Load Script (`qlik-load-script`) | ❌ Skip | BI tool not used |
| 301 | Skill | Query Tableau Data (`query-tableau-data`) | ❌ Skip | BI tool not used |
| 302 | Skill | Redis Core (`redis-core`) | ❌ Skip | Datastore not used (TimescaleDB via psycopg, Qdrant, DuckDB only) |
| 303 | Skill | Redis Observability (`redis-observability`) | ❌ Skip | Datastore not used (TimescaleDB via psycopg, Qdrant, DuckDB only) |
| 304 | Skill | Redshift (`redshift`) | ❌ Skip | Cloud not used (AWS); the stack runs on local Docker |
| 305 | Skill | Scikit Learn (`scikit-learn`) | ❌ Skip | ML platform / training framework not used (sentiment runs inference only; statsmodels for research) |
| 306 | Skill | Scikit Learn Best Practices (`scikit-learn-best-practices`) | ❌ Skip | ML platform / training framework not used (sentiment runs inference only; statsmodels for research) |
| 307 | Skill | Searching Mlflow Docs (`searching-mlflow-docs`) | ❌ Skip | ML platform / training framework not used (sentiment runs inference only; statsmodels for research) |
| 308 | Skill | Securing S3 Buckets (`securing-s3-buckets`) | ❌ Skip | Cloud not used (AWS); the stack runs on local Docker |
| 309 | Skill | Senior Data Engineer (`senior-data-engineer`) | ❌ Skip | Orchestration is LangGraph and ingest is in-process Python; no ETL/ELT tool, no JVM streaming |
| 310 | Skill | Skill Share (`skill-share`) | ❌ Skip | Shares skills to Slack via Rube; not used |
| 311 | Skill | Slack Gif Creator (`slack-gif-creator`) | ❌ Skip | Business / creative / content task, not code |
| 312 | Skill | Snowflake Expert (`snowflake-expert`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 313 | Skill | Snowpipe Bcdr (`snowpipe-bcdr`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 314 | Skill | Soda Cli (`soda-cli`) | ❌ Skip | Data-quality / catalog framework not used; the repo has its own `research/data_quality.py` |
| 315 | Skill | Spark Engineer (`spark-engineer`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 316 | Skill | Splunk Ingest Processor Setup (`splunk-ingest-processor-setup`) | ❌ Skip | Observability vendor not used (Prometheus + OpenTelemetry) |
| 317 | Skill | Splunk Spl2 Pipeline Kit (`splunk-spl2-pipeline-kit`) | ❌ Skip | Observability vendor not used (Prometheus + OpenTelemetry) |
| 318 | Skill | Sql Server Table Reconciliation (`sql-server-table-reconciliation`) | ❌ Skip | Cloud not used (Azure / Microsoft) |
| 319 | Skill | Tableau Dashboard Creator (`tableau-dashboard-creator`) | ❌ Skip | BI tool not used |
| 320 | Skill | Tensorflow Data Pipelines (`tensorflow-data-pipelines`) | ❌ Skip | ML platform / training framework not used (sentiment runs inference only; statsmodels for research) |
| 321 | Skill | Tensorflow Model Deployment (`tensorflow-model-deployment`) | ❌ Skip | ML platform / training framework not used (sentiment runs inference only; statsmodels for research) |
| 322 | Skill | Theme Factory (`theme-factory`) | ❌ Skip | Business / creative / content task, not code |
| 323 | Skill | Troubleshoot Cassandra (`troubleshoot-cassandra`) | ❌ Skip | Datastore not used (TimescaleDB via psycopg, Qdrant, DuckDB only) |
| 324 | Skill | Udf Benchmark (`udf-benchmark`) | ❌ Skip | Lakehouse / Spark / warehouse platform not used |
| 325 | Skill | Validating Json Data (`validating-json-data`) | ❌ Skip | Node.js tooling; the codebase is Python |
| 326 | Skill | Vercel Composition Patterns (`vercel-composition-patterns`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 327 | Skill | Vercel React Best Practices (`vercel-react-best-practices`) | ❌ Skip | Frontend stack not used; the UI is one inline `HTMLResponse` in `gateway/app.py` |
| 328 | Skill | Youtube Downloader (`youtube-downloader`) | ❌ Skip | Business / creative / content task, not code |
| 329 | Plugin | Kilo Marketplace Test Plugin (`git/github.com/Kilo-Org/kilo-marketplace-test-plugin`) | ❌ Skip | Marketplace test fixture |
| 330 | Mode | Architect (`architect`) | ❌ Skip | Legacy Kilo 5.x copy of the agent with the same name; use the agent |
| 331 | Mode | Code Reviewer (`code-reviewer`) | ❌ Skip | Legacy Kilo 5.x copy of the agent with the same name; use the agent |
| 332 | Mode | Code Simplifier (`code-simplifier`) | ❌ Skip | Legacy Kilo 5.x copy of the agent with the same name; use the agent |
| 333 | Mode | Code Skeptic (`code-skeptic`) | ❌ Skip | Legacy Kilo 5.x copy of the agent with the same name; use the agent |
| 334 | Mode | Documentation Specialist (`docs-specialist`) | ❌ Skip | Legacy Kilo 5.x copy of the agent with the same name; use the agent |
| 335 | Mode | Frontend Specialist (`frontend-specialist`) | ❌ Skip | Legacy Kilo 5.x copy of the agent with the same name; use the agent |
| 336 | Mode | Test Engineer (`test-engineer`) | ❌ Skip | Legacy Kilo 5.x copy of the agent with the same name; use the agent |
