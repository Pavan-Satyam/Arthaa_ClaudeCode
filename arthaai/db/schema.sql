-- ArthaAI TimescaleDB schema (Tier 2 quantitative persistence).
-- Auto-applied on first container start; idempotent.

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS assets (
    symbol       TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    asset_class  TEXT NOT NULL,        -- 'equity' | 'commodity_etf'
    exchange     TEXT,
    currency     TEXT DEFAULT 'USD',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ohlcv (
    symbol    TEXT        NOT NULL REFERENCES assets(symbol),
    ts        TIMESTAMPTZ NOT NULL,
    interval  TEXT        NOT NULL,
    open      DOUBLE PRECISION NOT NULL,
    high      DOUBLE PRECISION NOT NULL,
    low       DOUBLE PRECISION NOT NULL,
    close     DOUBLE PRECISION NOT NULL,
    volume    DOUBLE PRECISION NOT NULL,
    source_provider TEXT,
    retrieved_at TIMESTAMPTZ,
    adjustment_basis TEXT,
    provider_symbol TEXT,
    provider_timestamp TIMESTAMPTZ,
    normalization_version TEXT,
    PRIMARY KEY (symbol, interval, ts)
);

-- Nullable provenance leaves historical rows explicitly unknown rather than
-- fabricating source/retrieval details during migration.
ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS source_provider TEXT;
ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS retrieved_at TIMESTAMPTZ;
ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS adjustment_basis TEXT;
ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS provider_symbol TEXT;
ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS provider_timestamp TIMESTAMPTZ;
ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS normalization_version TEXT;

SELECT create_hypertable('ohlcv', 'ts', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ohlcv_symbol_ts_idx ON ohlcv (symbol, ts DESC);

INSERT INTO assets (symbol, name, asset_class, exchange) VALUES
    ('GLD',  'SPDR Gold Shares',           'commodity_etf', 'NYSEARCA'),
    ('SLV',  'iShares Silver Trust',       'commodity_etf', 'NYSEARCA'),
    ('USO',  'United States Oil Fund',     'commodity_etf', 'NYSEARCA'),
    ('DBC',  'Invesco DB Commodity Index', 'commodity_etf', 'NYSEARCA'),
    ('AAPL', 'Apple Inc.',                 'equity',        'NASDAQ'),
    ('MSFT', 'Microsoft Corporation',      'equity',        'NASDAQ'),
    ('XOM',  'Exxon Mobil Corporation',    'equity',        'NYSE')
ON CONFLICT (symbol) DO NOTHING;

-- Signal promotion tracking: OOS evaluation results for each symbol/signal pair.
CREATE TABLE IF NOT EXISTS signal_promotion (
    symbol          TEXT        NOT NULL,
    signal          TEXT        NOT NULL DEFAULT 'trend',
    qualified       BOOLEAN     NOT NULL,
    sharpe          DOUBLE PRECISION,
    max_drawdown    DOUBLE PRECISION,
    oos_return      DOUBLE PRECISION,
    buy_hold_return DOUBLE PRECISION,
    evaluated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, signal)
);
CREATE INDEX IF NOT EXISTS signal_promotion_qualified_idx ON signal_promotion (qualified) WHERE qualified = TRUE;

-- Preferred data provider per asset (provider chain fallback).
ALTER TABLE assets ADD COLUMN IF NOT EXISTS preferred_provider TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS last_provider    TEXT;
ALTER TABLE assets ADD COLUMN IF NOT EXISTS last_ingest_at  TIMESTAMPTZ;

-- Point-in-time universe membership (survivorship / selection-bias control).
-- A security is a member over [valid_from, valid_to); valid_to NULL = still listed.
-- Populated from a governed security master, or (absent a vendor) derived from
-- observed OHLCV coverage as a conservative floor. Consumers query membership
-- as of a date, so a backtest never sees a not-yet-listed or already-delisted name.
CREATE TABLE IF NOT EXISTS universe_membership (
    symbol      TEXT        NOT NULL REFERENCES assets(symbol),
    valid_from  TIMESTAMPTZ NOT NULL,
    valid_to    TIMESTAMPTZ,
    source      TEXT        NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, valid_from)
);
CREATE INDEX IF NOT EXISTS universe_membership_window_idx
    ON universe_membership (valid_from, valid_to);

-- Ingestion batch audit: one row per ingest/refresh call (auditability seam).
CREATE TABLE IF NOT EXISTS ingest_batch (
    batch_id     BIGSERIAL   PRIMARY KEY,
    symbol       TEXT        NOT NULL,
    interval     TEXT        NOT NULL,
    provider     TEXT,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    rows_written INTEGER,
    status       TEXT        NOT NULL DEFAULT 'running',  -- running | ok | empty | error
    error        TEXT
);
CREATE INDEX IF NOT EXISTS ingest_batch_symbol_idx
    ON ingest_batch (symbol, started_at DESC);

-- Corporate actions (splits/dividends) for adjustment auditability. ``ratio`` is
-- new shares per old share (splits); ``amount`` is cash per share (dividends).
-- ``reference_price`` is the prior close the adjustment is applied against, so a
-- split factor or dividend yield can be reproduced and audited.
CREATE TABLE IF NOT EXISTS corporate_action (
    symbol          TEXT        NOT NULL REFERENCES assets(symbol),
    ex_date         TIMESTAMPTZ NOT NULL,
    action_type     TEXT        NOT NULL,        -- 'split' | 'dividend'
    ratio           DOUBLE PRECISION,
    amount          DOUBLE PRECISION,
    reference_price DOUBLE PRECISION,
    source          TEXT        NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, ex_date, action_type)
);
CREATE INDEX IF NOT EXISTS corporate_action_symbol_idx
    ON corporate_action (symbol, ex_date DESC);

-- Issuer (legal reporting entity) identified by SEC CIK. One CIK can map to many
-- tradeable securities (e.g. GOOG and GOOGL share a CIK), so the relationship is
-- issuer 1 -> N assets, not a column on assets that assumes one-to-one.
CREATE TABLE IF NOT EXISTS issuer (
    cik         TEXT PRIMARY KEY,       -- zero-padded 10-digit SEC CIK
    name        TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE assets ADD COLUMN IF NOT EXISTS issuer_cik TEXT REFERENCES issuer(cik);
CREATE INDEX IF NOT EXISTS assets_issuer_cik_idx ON assets (issuer_cik);


