# Data Production Readiness Register

**Purpose:** Record how ArthaAI obtains and stores research data today, what must change before production use, and how to replace or supplement open sources without rewriting agents.

**Snapshot date:** 2026-10-11  
**Scope:** Option B — global equities, ETFs, and index proxies  
**Current release posture:** Research-only. Paper/live execution stays subject to the existing E3 gate in `SPEC.md` and `PROJECT_BOARD.md`.

This is a readiness and decision register, not a task board or a claim that a provider is production-qualified. `PROJECT_BOARD.md` tracks committed work; `STATUS_REPORT.md` describes implemented behavior and verification. When a readiness item is approved for implementation, create/update its board task and then record its code and verification outcome in the status report.

## Executive State

ArthaAI can currently collect and research a limited US-listed universe from free sources, but the present system is **not production-ready as a global market-data platform**. The latest read-only audit found 73 of 75 registered assets with stored prices and clean recent NYSE sessions; two placeholder symbols (`SILVER`, `XAG`) had no bars. Sixty-eight catalog rows had no exchange metadata. The 73 histories are not a survivorship-safe, point-in-time global universe, and clean recent coverage does not prove historical corporate-action or licensing quality.

Use open sources for exploration, adapter development, and research where their terms and data quality fit. Production does not automatically require paid APIs, but each source must pass the coverage, licensing, reliability, auditability, support, and security criteria below. A paid source is not inherently accurate; it must be validated too.

## Current-State Inventory

| Capability | Current implementation | Current limitations / production gap |
|---|---|---|
| Equity/ETF OHLCV | `arthaai.data.provider` defines `OHLCVProvider`, `ProviderRegistry`, `LSEProvider`, and `YFinanceProvider`. `ARTHAAI_MARKET_DATA_PROVIDER` selects a configured registered provider; default `auto` preserves the LSE-when-configured → yfinance chain. Host startup can register custom adapters using `register_provider()`. Fetch, ingest, and refresh entry points accept an injected registry. | Only built-in adapters ship in the current CLI/orchestration process. A future vendor package must be explicitly installed and registered by trusted host startup. Yahoo availability/terms and symbol coverage are not a production entitlement. Provider failures can degrade to empty data; callers need observable freshness/quality outcomes. |
| Provider selection and provenance | `assets.preferred_provider` supports per-symbol routing. `ohlcv` now has nullable `source_provider`, `retrieved_at`, `adjustment_basis`, `provider_symbol`, `provider_timestamp`, and `normalization_version`; LSE/yfinance direct and registry upserts populate them. `timescale.load_ohlcv(..., include_provenance=True)` exposes them without changing the default OHLCV frame. | Migration deliberately leaves old rows NULL. Live check: 4/39,212 rows have new lineage; 39,208 legacy bars remain unknown. `provider_symbol` is the ticker string sent, not a guaranteed stable vendor security ID. Revision IDs, raw payloads, action factors, and correction history are not captured. |
| Security master / universe | `arthaai.data.universe` can load a US symbol directory; `assets` stores symbol, name, asset class, exchange. | Current catalog is not global or point-in-time. Historical index membership, delisted securities, ticker changes, share classes, MICs, currencies, country, listing validity, and symbol mappings are incomplete. Most current records lack exchange metadata. |
| Calendar and session audit | `exchange_calendars` powers `audit-history`; per-symbol calendar overrides are supported. | Calendar assignment is operator-supplied, not resolved from a governed security master. Current broad audit used XNYS as the assumption for the US-listed sample. |
| Operational storage | TimescaleDB is the primary application OHLCV store. | Retention, backups, recovery objectives, HA, read replicas, migration rehearsals, and data reconciliation requirements need production decisions and deployment verification. |
| Research storage | Optional DuckDB/Parquet in `arthaai.data.ibor`. | Research-only local analytical store; not a TimescaleDB replacement, shared authoritative book, or managed production warehouse. |
| Cross-sectional research | `arthaai.research.cross_sectional` evaluates lagged IC-weighted scores in sequential OOS windows with costs. | It is diagnostic, uses a current fixed factor set and current available symbols, and is not formal E3. The five-symbol positive diagnostic reversed on the 73-symbol sample, demonstrating universe/sample sensitivity. |
| Optional adapters | Standalone modules exist for OpenBB, SEC, FRED/DBnomics, RSS/FinBERT, EIA/ECB, QuantLib and Sentinel metadata. | They are not generally wired to the operational ingest graph. Optional package presence does not prove provider endpoint coverage, correctness, licensing, reliability, or production approval. |
| Execution | Research-first; paper interface is explicitly opt-in; live broker adapter remains unimplemented. | No live orders until existing E3 passes. This record does not authorize a new benchmark or promote the cross-sectional diagnostic. |

## Replacement Seams

Keep agents dependent on canonical ArthaAI contracts, not vendor SDKs. The target boundary is:

1. **Provider adapters** fetch a requested instrument, range, interval, and data basis, returning canonical bars plus structured provenance and typed errors.
2. **Normalization/validation** maps vendor identifiers to ArthaAI instrument IDs; normalizes timestamps, sessions, currencies, corporate actions, units, nulls, duplicates, and adjustment policy.
3. **Quality and reconciliation** checks schema, freshness, expected sessions, OHLC invariants, coverage, source disagreements, and correction behavior before data is accepted or promoted.
4. **Persistence** writes validated canonical rows and lineage to the selected store; ingestion must be idempotent and safe to replay.
5. **Consumers** (agents, factors, backtests) read only the canonical contract and receive explicit data quality/provenance metadata where needed.

### Current code replacement map

| Concern | Current seam | Planned production change |
|---|---|---|
| OHLCV source routing | `arthaai/data/provider.py`: `OHLCVProvider`, `ProviderRegistry`, `register_provider()`, built-in adapters, `fetch_ohlcv()`, `ingest_resilient()`, `refresh_history()` | Configuration-driven selection and registration hook exist. Remaining work: implement/register a qualified vendor adapter, deployment bootstrap/allowlist, health/coverage policy, lineage, and cutover controls. |
| Yahoo normalization | `arthaai/data/ingest.py`: `_download()` | Make adjustment mode explicit and tested; preserve raw and adjusted semantics and corporate-action events without double-adjusting. |
| LSE normalization | `arthaai/data/lse.py`: `download()` | Conform to the same adapter contract and shared validation rather than provider-specific assumptions leaking into callers. |
| Symbol/exchange mapping | `arthaai/data/universe.py`, `arthaai/db/schema.sql`, `arthaai/db/timescale.py:assets` | Add governed instrument identifiers, MIC, currency, country, asset type, validity dates, symbol aliases, and point-in-time membership/constituent history. |
| Lineage | `arthaai/db/schema.sql`: source provider, retrieval timestamp, adjustment basis, provider ticker string, original provider timestamp, normalization version; `arthaai/db/timescale.py:upsert_ohlcv()`; opt-in `load_ohlcv(..., include_provenance=True)` | Basic per-bar lineage is implemented for new/upserted rows. Remaining work: stable vendor security ID, corporate-action factors/events, provider revision/correction identity, raw-response/vendor revision reference, source request metadata, and a policy for legacy rows (do not guess missing provenance). |
| Data readiness | `arthaai/research/data_quality.py`, `arthaai/cli.py:audit-history` | Resolve calendars from security master; add source freshness, correction/reconciliation, action-adjustment, and completeness checks. Gate research runs on declared quality thresholds. |
| Research panel | `arthaai/factors/panel.py`, `arthaai/research/cross_sectional.py` | Require point-in-time constituents, consistent instrument identities, delisted assets, and explicit benchmark/portfolio methodology before drawing global conclusions. |
| OpenBB | `arthaai/data/openbb_router.py` | Treat as an optional adapter only. Verify exact endpoint/provider entitlements and normalized outputs; do not make agent code depend on OpenBB result types. |
| Fundamentals/news/macro/alternative | `arthaai/data/fundamentals.py`, `macro.py`, `news_sentiment.py`, `alternative.py` | Wire each only through explicit interfaces, source attribution, timestamps, retry/rate limits, licensing review, and dataset-specific validation. |

## Production Qualification Checklist

A provider or dataset is not production-approved until the relevant items are evidenced and recorded:

- **Coverage:** agreed exchanges, instruments, asset types, history depth, intraday intervals, currencies, and service hours.
- **Rights:** written review of storage, derived data, redistribution/display, model/research use, user count, retention, and termination/export rights.
- **Identity:** stable vendor IDs mapped to ArthaAI IDs; MIC/exchange, currency, region, timezone, symbol history, corporate actions, delistings, and point-in-time index membership where required.
- **Accuracy:** sample reconciliation across representative instruments, dates, corporate actions, holidays, suspensions, corrections, and extreme values against an independent source or official reference.
- **Adjusted-data semantics:** documented raw/adjusted price behavior, dividend and split handling, delisting treatment, and reproducible backtest basis.
- **Operations:** published and measured rate limits, latency, uptime/support commitments, outage behavior, retry/backoff, idempotency, backfill/revision behavior, status monitoring, and cost limits.
- **Security:** credentials in Vault or a managed secret store, least-privilege credentials, TLS, no secrets in logs or notebooks, outbound network allowlists where feasible, and key rotation/revocation procedures.
- **Auditability:** data batch IDs, provider/version, retrieval timestamps, quality reports, transformations, and reproducible source snapshots or vendor revision references.
- **Resilience:** explicit primary/fallback policy, compatible canonical semantics, conflict/reconciliation rules, and alerts. Do not silently merge unlike adjustment bases or choose the source that makes a backtest look best.
- **Acceptance:** contract tests, adapter tests, historical replay, data-quality audit, and backtest regression on a frozen sample before switching any default.

## Open-Source and Paid-Source Policy

- Continue with free/open sources for development and exploratory research when their licenses permit the intended use and they meet the experiment's stated quality bar.
- A production switch may use paid APIs, licensed institutional feeds, or hardened open sources. Decide per dataset, market, and use case rather than assuming one vendor covers everything.
- Evaluate vendors through a documented request-for-coverage and sample reconciliation. Compare identifiers, corporate actions, delisted history, point-in-time membership, corrections, latency, uptime/support, redistribution terms, and total cost.
- Do not expose vendor selection directly to agents. Select providers in configuration/registry; keep canonical normalized data and provenance stable.
- Never describe the current free-source history as institution-grade or globally representative without completed qualification evidence.

## Migration Procedure

1. Record intended production use and required exchanges, instruments, intervals, freshness, history depth, and licensing rights.
2. Choose a vendor-neutral canonical schema and define adapter/provenance contracts before adding another SDK to agent code.
3. Implement the candidate adapter as opt-in; keep current source defaults unchanged during shadow collection.
4. Collect overlapping data from old and candidate sources. Reconcile identifiers, timestamps, OHLCV, volume, corporate actions, and corrections; publish coverage/error distributions.
5. Run history audits and frozen-sample backtests. Any strategy change must use predeclared, sequential OOS windows; do not tune on a reported OOS window.
6. Review licensing, security, operations, and cost evidence. Obtain explicit owner approval for production provider/default changes.
7. Create board tasks for approved implementation/deployment work. Update this register with decisions and evidence, and update `STATUS_REPORT.md` after implementation. Do not close E3 or enable paper/live paths unless the existing release policy is satisfied.
8. Roll out with a reversible configuration change, monitored shadow comparison, alerting, rollback instructions, and an operator runbook.

## Decision and Evidence Log

| Date | Decision / evidence | State |
|---|---|---|
| 2026-10-11 | Continue free sources for research only. Refreshed 73 data-bearing registered assets with yfinance; recent XNYS-session audit is clean. | Implemented for research sample; not a global or production qualification. |
| 2026-10-11 | Added `ARTHAAI_MARKET_DATA_PROVIDER` (default `auto`), a custom `register_provider()` hook, and registry selection across fetch/ingest/refresh. Existing default fallback order is preserved; configured, explicit, per-symbol pinned, unavailable, and unregistered-provider cases are tested. | Provider selection is configurable when an adapter is registered. Production vendor adapter/package, deployment registration, per-bar lineage, qualification, and cutover remain open. |
| 2026-10-11 | Added nullable OHLCV source, retrieval time, adjustment basis, provider symbol, source timestamp, and normalization version; direct and registry LSE/yfinance writes populate available facts. The opt-in reader preserves the old default frame. Applied the idempotent schema migration and refreshed four GLD bars to verify the live write/read path. Full DB-independent suite: 418 passed, 1 deselected. | Live DB: 39,212 total bars, 4 recent GLD rows have the six basic provenance fields, 39,208 historical rows remain NULL/unknown. Provider symbol is not a stable vendor ID; action factors/events, revision IDs, and raw payloads remain open. |
| 2026-10-11 | 73-asset cross-sectional diagnostic trailed equal-weight in both tested OOS windows; formal trend and breakout sweeps had no qualifiers. | E3 remains blocked; existing gate unchanged. |
| TBD | Select initial production coverage and approve source/data-rights requirements. | Open decision; no vendor or credentials selected. |
| TBD | Establish point-in-time global constituents, exchange/MIC metadata, and delisted/security-master history. | Open data-readiness work. |
| TBD | Approve adapter protocol, per-bar lineage schema, reconciliation thresholds, and operational SLOs. | Open design work before production provider integration. |

## Update Discipline

- Update this file when source status, security, licensing, provider decisions, replacement seams, or production evidence changes.
- Add actionable, approved implementation work to `PROJECT_BOARD.md`; do not use this register as a second backlog.
- Update `STATUS_REPORT.md` with code actually implemented and the commands/tests/data used to verify it.
- If those records disagree, reconcile them against code, tests, provider terms, and observed data; record the date and evidence. Never resolve a disagreement by silently changing the E3 criteria.
