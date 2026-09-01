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
    PRIMARY KEY (symbol, interval, ts)
);

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
