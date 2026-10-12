# Operational Storage Decisions (TimescaleDB)

**Status:** Draft decision register. This defines the intended production posture for
the TimescaleDB application store. It is **not** yet validated in a live HA/backup
environment; the Docker configurations below are blueprints to rehearse and verify
before any production use.

**Scope:** the primary OHLCV/quant store (`arthaai/db/schema.sql`). Qdrant (narrative
RAG), Redpanda (event bus), OPA, and Vault are out of scope here.

**Current posture:** single-node `timescale/timescaledb:2.17.2-pg16` from
`docker-compose.yml`, a named volume, no retention policy, no backups. Research-only.

---

## 1. Data classes and retention policy

Retention is chosen per data class. The principle: **intraday detail is short-lived,
daily history is retained indefinitely** (it is the research/backtest substrate).

| Data class | Table / `interval` | Hot retention | Then |
|---|---|---|---|
| Raw tick (future) | `tick` (not yet implemented) | **30 days** | downsampled to 1-minute bars |
| Intraday 1m / 5m | `ohlcv` (`1m`, `5m`) | **30 days** | dropped |
| Intraday 1h | `ohlcv` (`1h`) | **2 years** | dropped |
| Daily | `ohlcv` (`1d`) | **indefinite** | retained (backtest basis) |
| Corporate actions | `corporate_action` | **indefinite** | retained (adjustment audit) |
| Membership windows | `universe_membership` | **indefinite** | retained (PIT survivorship) |
| Lineage / audit | `ingest_batch`, provenance columns | **indefinite** | retained (auditability) |
| Promotion results | `signal_promotion` | **indefinite** | retained (release evidence) |

**Rationale:** daily bars and all lineage/decision tables are small and are the
evidence base for E3 and audits, so they are never pruned. Intraday bars dominate
volume and are only needed for recent execution/fills analysis.

### Retention implementation

TimescaleDB's `add_retention_policy` operates on a whole hypertable, so per-interval
retention uses a scheduled job that deletes only the intraday classes. Apply with
`psql -f arthaai/db/retention.sql` (kept out of the auto-run `schema.sql` so local dev
is not surprised by background deletes).

```sql
-- arthaai/db/retention.sql
CREATE OR REPLACE PROCEDURE arthaai_prune_intraday() LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM ohlcv WHERE interval IN ('1m','5m') AND ts < now() - INTERVAL '30 days';
    DELETE FROM ohlcv WHERE interval = '1h'       AND ts < now() - INTERVAL '730 days';
END $$;

-- Run daily. Daily bars, corporate actions, membership, and audit tables are never pruned.
SELECT add_job('arthaai_prune_intraday', '1 day', if_not_exists => TRUE);
```

**Downsampling (future):** when tick data lands, a continuous aggregate
`ohlcv_1m` (from tick) and `ohlcv_1d` (from 1m) should be materialised so the 30-day
tick window is preserved as 1-minute/daily history. Not implemented yet.

---

## 2. High availability

**Decision (target):** one **primary** + one **streaming replica** with synchronous
commit off by default (async replication) — availability over zero-RPO for a research
store. A connection pooler (PgBouncer) fronts the primary; read-only analytical work
can target the replica.

- `wal_level = replica`, `max_wal_senders = 4`, `hot_standby = on`.
- Replica bootstrapped with `pg_basebackup -R` and kept current via streaming replication.
- **Failover:** manual promotion for now (documented runbook); automated failover
  (Patroni/repmgr) is a later decision, not in this draft.

Blueprint: [`docker-compose.ha.yml`](../docker-compose.ha.yml) (override layer:
`docker compose -f docker-compose.yml -f docker-compose.ha.yml up -d`).

---

## 3. Backups and recovery

**Decision (target):** continuous **WAL archiving** (point-in-time recovery) **plus**
a nightly logical `pg_dump` for portability.

| Control | Choice | Target |
|---|---|---|
| Physical / PITR | WAL archiving + base backup (`pgBackRest` or `wal-g`) | RPO ≤ 5 min, RTO ≤ 1 h |
| Logical | nightly `pg_dump -Fc` to object storage | 30 daily + 12 monthly retained |
| Rehearsal | restore into a scratch DB and run `arthaai migrate` + `audit-history` | monthly |

Backups must include the lineage tables so a restore is auditable. Secrets (DB
credentials, storage keys) come from Vault, never from the compose file in production.

Blueprint: the `backup` service in [`docker-compose.ha.yml`](../docker-compose.ha.yml)
runs `pg_dump` on a schedule; WAL archiving is configured on the primary via
`archive_command`.

---

## 4. Verification requirements before production

This draft is a decision record, not evidence. Before any production cutover:

1. Stand up the HA override in a staging environment; confirm replication lag stays
   within target under load.
2. Restore from a WAL archive and from a logical dump; verify row counts and that
   `arthaai migrate` reports a clean schema.
3. Confirm the retention job prunes only intraday classes (assert daily/lineage rows
   are untouched).
4. Record measured RPO/RTO and the failover runbook in this document.

Until those are done, this remains **draft**. No claim of production readiness.
