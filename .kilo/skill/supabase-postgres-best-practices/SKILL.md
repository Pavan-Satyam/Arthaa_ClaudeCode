---
name: supabase-postgres-best-practices
description: Postgres query, schema, and index review (general, not TimescaleDB-specific). Use for arthaai/db/timescale.py, arthaai/db/schema.sql, and migrations.
---

# Postgres review checklist (ArthaAI's timescale store)

General Postgres guidance for Postgres 16 / TimescaleDB. TimescaleDB adds hypertables and
continuous aggregates on top of these basics.

## Checklist
- **Indexes**: every hot predicate has a supporting index. Here: `ohlcv(symbol, interval, ts)`,
  `universe_membership(valid_from, valid_to)`, `ingest_batch(symbol, started_at DESC)`,
  `corporate_action(symbol, ex_date DESC)`, `assets(issuer_cik)`.
- **Set-based, not loops**: `upsert_ohlcv` batches its inserts — keep it that way instead of per-row round-trips.
- **Parameter typing**: cast explicitly (`%s::timestamptz`, `%s::text`) when a value can be `NULL`,
  otherwise psycopg raises "could not determine data type of parameter".
- **Idempotent migrations**: `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, `ON CONFLICT`.
  Migrations are re-applied by `arthaai migrate`.
- **Time**: store `timestamptz`; normalize to UTC day boundaries; de-duplicate by day on read.
- **EXPLAIN before indexing**: read the plan on a slow path instead of guessing.
