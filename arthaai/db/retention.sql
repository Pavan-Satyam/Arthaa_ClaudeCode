-- ArthaAI TimescaleDB retention policy (see docs/OPERATIONAL_STORAGE.md).
--
-- Applied explicitly, NOT via schema.sql, so local dev is not surprised by
-- background deletes:   psql -U arthaai -d arthaai -f arthaai/db/retention.sql
--
-- Principle: intraday detail is short-lived; daily bars and all lineage/decision
-- tables (corporate_action, universe_membership, ingest_batch, signal_promotion)
-- are retained indefinitely.

CREATE OR REPLACE PROCEDURE arthaai_prune_intraday() LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM ohlcv WHERE interval IN ('1m', '5m') AND ts < now() - INTERVAL '30 days';
    DELETE FROM ohlcv WHERE interval = '1h'          AND ts < now() - INTERVAL '730 days';
END; $$;

-- Run daily; idempotent registration (this TimescaleDB build has no if_not_exists).
SELECT add_job('arthaai_prune_intraday'::regproc, INTERVAL '1 day')
WHERE NOT EXISTS (
    SELECT 1 FROM timescaledb_information.jobs
    WHERE proc_name = 'arthaai_prune_intraday'
);
