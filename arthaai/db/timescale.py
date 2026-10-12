"""TimescaleDB access — connection, OHLCV upsert, and read helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pandas as pd
import psycopg

from arthaai.config import get_settings

OHLCV_NORMALIZATION_VERSION = "canonical_ohlcv_v1"


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(get_settings().timescale_dsn)
    try:
        yield conn
    finally:
        conn.close()


def ping() -> str:
    """Return the TimescaleDB extension version; raises if unreachable."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';")
        row = cur.fetchone()
        return row[0] if row else "NOT INSTALLED"


def ensure_asset(
    symbol: str,
    name: str | None = None,
    asset_class: str = "equity",
    exchange: str | None = None,
    currency: str | None = None,
) -> None:
    """Register an asset if it isn't already known, so OHLCV can reference it.

    Lets the platform analyse any ticker, not just the seeded universe. The FK on
    ohlcv(symbol) -> assets(symbol) requires this row to exist first. Existing
    rows are left untouched (metadata enrichment uses ``update_asset_metadata``).
    """
    symbol = symbol.upper()
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO assets (symbol, name, asset_class, exchange, currency) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (symbol) DO NOTHING;",
            (symbol, name or symbol, asset_class, exchange, currency or "USD"),
        )
        conn.commit()


def update_asset_metadata(
    symbol: str,
    *,
    name: str | None = None,
    asset_class: str | None = None,
    exchange: str | None = None,
    currency: str | None = None,
) -> None:
    """Update only the asset metadata fields that are provided (None = unchanged)."""
    assignments: list[str] = []
    params: list = []
    for column, value in (
        ("name", name),
        ("asset_class", asset_class),
        ("exchange", exchange),
        ("currency", currency),
    ):
        if value is not None:
            assignments.append(f"{column} = %s")
            params.append(value)
    if not assignments:
        return
    params.append(symbol.upper())
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE assets SET {', '.join(assignments)} WHERE symbol = %s;", params
        )
        conn.commit()


def list_asset_symbols() -> list[str]:
    """Return every registered symbol, alphabetically."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT symbol FROM assets ORDER BY symbol;")
        return [row[0] for row in cur.fetchall()]


def assets_missing_exchange() -> list[str]:
    """Return registered symbols whose exchange is NULL or empty."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT symbol FROM assets "
            "WHERE exchange IS NULL OR exchange = '' ORDER BY symbol;"
        )
        return [row[0] for row in cur.fetchall()]


def asset_coverage(interval: str = "1d") -> list[dict]:
    """Per-symbol bar count, first/last bar, and asset metadata (universe selection)."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT a.symbol, a.asset_class, a.exchange, count(o.ts) AS bars, "
            "min(o.ts) AS first, max(o.ts) AS last "
            "FROM assets a "
            "LEFT JOIN ohlcv o ON o.symbol = a.symbol AND o.interval = %s "
            "GROUP BY a.symbol, a.asset_class, a.exchange ORDER BY a.symbol;",
            (interval,),
        )
        columns = ("symbol", "asset_class", "exchange", "bars", "first", "last")
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def upsert_membership(rows: list[dict]) -> int:
    """Insert/refresh point-in-time membership windows; returns rows written."""
    if not rows:
        return 0
    with connection() as conn, conn.cursor() as cur:
        for row in rows:
            cur.execute(
                "INSERT INTO universe_membership (symbol, valid_from, valid_to, source) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (symbol, valid_from) DO UPDATE SET "
                "valid_to = EXCLUDED.valid_to, source = EXCLUDED.source, recorded_at = now();",
                (
                    str(row["symbol"]).upper(),
                    row["valid_from"],
                    row.get("valid_to"),
                    row.get("source", "unknown"),
                ),
            )
        conn.commit()
    return len(rows)


def load_membership() -> list[dict]:
    """Every membership window with its asset class, ordered by symbol."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT m.symbol, a.asset_class, m.valid_from, m.valid_to, m.source "
            "FROM universe_membership m JOIN assets a ON a.symbol = m.symbol "
            "ORDER BY m.symbol;"
        )
        columns = ("symbol", "asset_class", "valid_from", "valid_to", "source")
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def universe_as_of(as_of, asset_class: str | None = None) -> list[str]:
    """Symbols whose listing window covers ``as_of`` (optional asset-class filter)."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT m.symbol FROM universe_membership m "
            "JOIN assets a ON a.symbol = m.symbol "
            "WHERE m.valid_from <= %s::timestamptz "
            "AND (m.valid_to IS NULL OR m.valid_to >= %s::timestamptz) "
            "AND (%s::text IS NULL OR a.asset_class = %s::text) ORDER BY m.symbol;",
            (as_of, as_of, asset_class, asset_class),
        )
        return [row[0] for row in cur.fetchall()]


def record_ingest_batch(
    symbol: str,
    interval: str,
    provider: str | None,
    *,
    rows_written: int | None = None,
    status: str = "ok",
    error: str | None = None,
) -> None:
    """Record one ingestion/refresh call for auditability (best-effort seam)."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingest_batch "
            "(symbol, interval, provider, finished_at, rows_written, status, error) "
            "VALUES (%s, %s, %s, now(), %s, %s, %s);",
            (symbol.upper(), interval, provider, rows_written, status, error),
        )
        conn.commit()


def recent_ingest_batches(limit: int = 20) -> list[dict]:
    """Most recent ingestion batches, newest first (audit view)."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT batch_id, symbol, interval, provider, started_at, finished_at, "
            "rows_written, status, error FROM ingest_batch "
            "ORDER BY started_at DESC LIMIT %s;",
            (limit,),
        )
        columns = (
            "batch_id", "symbol", "interval", "provider",
            "started_at", "finished_at", "rows_written", "status", "error",
        )
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def upsert_corporate_actions(rows: list[dict]) -> int:
    """Insert/refresh corporate-action rows; returns rows written."""
    if not rows:
        return 0
    with connection() as conn, conn.cursor() as cur:
        for row in rows:
            cur.execute(
                "INSERT INTO corporate_action "
                "(symbol, ex_date, action_type, ratio, amount, reference_price, source) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (symbol, ex_date, action_type) DO UPDATE SET "
                "ratio = EXCLUDED.ratio, amount = EXCLUDED.amount, "
                "source = EXCLUDED.source, recorded_at = now();",
                (
                    str(row["symbol"]).upper(),
                    row["ex_date"],
                    row["action_type"],
                    row.get("ratio"),
                    row.get("amount"),
                    row.get("reference_price"),
                    row.get("source", "unknown"),
                ),
            )
        conn.commit()
    return len(rows)


def load_corporate_actions(symbol: str | None = None) -> list[dict]:
    """Corporate actions for one symbol (or all), ordered by ex-date."""
    columns = ("symbol", "ex_date", "action_type", "ratio", "amount", "reference_price", "source")
    with connection() as conn, conn.cursor() as cur:
        if symbol:
            cur.execute(
                "SELECT symbol, ex_date, action_type, ratio, amount, reference_price, source "
                "FROM corporate_action WHERE symbol = %s ORDER BY ex_date;",
                (symbol.upper(),),
            )
        else:
            cur.execute(
                "SELECT symbol, ex_date, action_type, ratio, amount, reference_price, source "
                "FROM corporate_action ORDER BY symbol, ex_date;"
            )
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def set_action_reference_prices() -> int:
    """Fill ``reference_price`` from the prior close in stored OHLCV; returns rows set."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE corporate_action ca SET reference_price = ("
            "SELECT o.close FROM ohlcv o WHERE o.symbol = ca.symbol AND o.interval = '1d' "
            "AND o.ts < ca.ex_date ORDER BY o.ts DESC LIMIT 1) "
            "WHERE ca.reference_price IS NULL AND EXISTS ("
            "SELECT 1 FROM ohlcv o WHERE o.symbol = ca.symbol AND o.interval = '1d' "
            "AND o.ts < ca.ex_date);"
        )
        updated = cur.rowcount
        conn.commit()
    return updated


def upsert_issuer(cik: str, name: str | None = None) -> None:
    """Register a legal reporting entity by its SEC CIK."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO issuer (cik, name) VALUES (%s, %s) "
            "ON CONFLICT (cik) DO UPDATE SET name = COALESCE(EXCLUDED.name, issuer.name);",
            (cik, name),
        )
        conn.commit()


def link_asset_issuer(symbol: str, cik: str) -> None:
    """Point an asset at its issuer (many assets may share one CIK)."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE assets SET issuer_cik = %s WHERE symbol = %s;", (cik, symbol.upper())
        )
        conn.commit()


def issuer_securities(cik: str) -> list[str]:
    """Every tradeable symbol linked to one issuer CIK (one-to-many check)."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT symbol FROM assets WHERE issuer_cik = %s ORDER BY symbol;", (cik,)
        )
        return [row[0] for row in cur.fetchall()]


def assets_missing_issuer() -> list[str]:
    """Registered symbols not yet linked to an issuer."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT symbol FROM assets WHERE issuer_cik IS NULL ORDER BY symbol;")
        return [row[0] for row in cur.fetchall()]


def _canonical_ts(ts, interval: str):
    """Canonicalise a bar timestamp.

    Daily bars are keyed to midnight UTC so providers that timestamp the same
    session differently (LSE at 00:00, yfinance at 13:30) collapse onto ONE row
    per (symbol, interval, day) via the primary key, instead of silently
    doubling the series (which corrupts backtests and cross-sectional panels).
    """
    ts = pd.Timestamp(ts)
    if interval == "1d":
        return (ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")).normalize()
    return ts


def upsert_ohlcv(
    symbol: str,
    interval: str,
    rows: pd.DataFrame,
    *,
    source_provider: str | None = None,
    adjustment_basis: str | None = None,
    provider_symbol: str | None = None,
    retrieved_at: datetime | None = None,
    normalization_version: str = OHLCV_NORMALIZATION_VERSION,
) -> int:
    """Insert/update OHLCV bars and optional batch provenance.

    Existing rows written before lineage support remain NULL for provenance;
    this function never retroactively guesses their source or adjustment basis.
    """
    if rows.empty:
        return 0
    retrieval_time = retrieved_at or datetime.now(UTC)
    records = [
        (
            symbol, _canonical_ts(r.ts, interval).to_pydatetime(), interval,
            r.open, r.high, r.low, r.close, r.volume,
            source_provider, retrieval_time, adjustment_basis, provider_symbol,
            (
                pd.Timestamp(r.ts).tz_localize("UTC")
                if pd.Timestamp(r.ts).tzinfo is None
                else pd.Timestamp(r.ts).tz_convert("UTC")
            ).to_pydatetime(),
            normalization_version,
        )
        for r in rows.itertuples(index=False)
    ]
    sql = """
        INSERT INTO ohlcv
            (symbol, ts, interval, open, high, low, close, volume,
               source_provider, retrieved_at, adjustment_basis, provider_symbol,
               provider_timestamp, normalization_version)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, interval, ts) DO UPDATE
          SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
              close = EXCLUDED.close, volume = EXCLUDED.volume,
              source_provider = EXCLUDED.source_provider,
              retrieved_at = EXCLUDED.retrieved_at,
              adjustment_basis = EXCLUDED.adjustment_basis,
              provider_symbol = EXCLUDED.provider_symbol,
              provider_timestamp = EXCLUDED.provider_timestamp,
              normalization_version = EXCLUDED.normalization_version;
    """
    with connection() as conn, conn.cursor() as cur:
        cur.executemany(sql, records)
        conn.commit()
        return cur.rowcount


def repair_daily_duplicates() -> int:
    """Collapse legacy daily duplicates to one row per (symbol, day).

    Older ingests stored both the 00:00 and 13:30 timestamps for the same day.
    Keeps the latest timestamp per day and deletes the rest; returns rows deleted.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM ohlcv o USING (
                SELECT ctid, row_number() OVER (
                    PARTITION BY symbol, ts::date ORDER BY ts DESC
                ) AS rn
                FROM ohlcv WHERE interval = '1d'
            ) d
            WHERE o.ctid = d.ctid AND d.rn > 1;
            """
        )
        deleted = cur.rowcount
        conn.commit()
    return deleted


def load_ohlcv(
    symbol: str,
    interval: str = "1d",
    limit: int = 400,
    *,
    include_provenance: bool = False,
) -> pd.DataFrame:
    """Return the most recent `limit` bars ascending by time.

    Daily series are de-duplicated by calendar day (one bar per day, latest
    timestamp wins) so legacy double-ingested days cannot distort analytics.
    Set ``include_provenance`` to include source provider, retrieval timestamp,
    and adjustment basis. The default result schema remains unchanged.
    """
    columns = "ts, open, high, low, close, volume"
    if include_provenance:
        columns += (
            ", source_provider, retrieved_at, adjustment_basis, provider_symbol, "
            "provider_timestamp, normalization_version"
        )
    if interval == "1d":
        sql = f"""
            SELECT {columns} FROM (
                SELECT DISTINCT ON (ts::date) {columns}
                FROM ohlcv WHERE symbol = %s AND interval = %s
                ORDER BY ts::date DESC, ts DESC
                LIMIT %s
            ) t ORDER BY ts ASC;
        """
    else:
        sql = f"""
            SELECT {columns}
            FROM ohlcv WHERE symbol = %s AND interval = %s
            ORDER BY ts DESC LIMIT %s;
        """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, (symbol, interval, limit))
        cols = [c.name for c in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
    return df.iloc[::-1].reset_index(drop=True) if interval != "1d" else df.reset_index(drop=True)


def asset_meta(symbol: str) -> dict | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, name, asset_class, exchange FROM assets WHERE symbol = %s;",
            (symbol.upper(),),
        )
        row = cur.fetchone()
    if not row:
        return None
    return dict(zip(["symbol", "name", "asset_class", "exchange"], row))


def latest_ts(symbol: str, interval: str = "1d") -> datetime | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT max(ts) FROM ohlcv WHERE symbol = %s AND interval = %s;", (symbol, interval)
        )
        return cur.fetchone()[0]


# ---- Signal promotion (OOS gate) --------------------------------------------

def upsert_signal_promotion(
    symbol: str,
    signal: str,
    qualified: bool,
    sharpe: float,
    max_drawdown: float,
    oos_return: float,
    buy_hold_return: float,
) -> None:
    """Record an OOS promotion evaluation for (symbol, signal)."""
    symbol = symbol.upper()
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO signal_promotion
                (symbol, signal, qualified, sharpe, max_drawdown,
                 oos_return, buy_hold_return, evaluated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (symbol, signal) DO UPDATE
              SET qualified = EXCLUDED.qualified,
                  sharpe = EXCLUDED.sharpe,
                  max_drawdown = EXCLUDED.max_drawdown,
                  oos_return = EXCLUDED.oos_return,
                  buy_hold_return = EXCLUDED.buy_hold_return,
                  evaluated_at = now();
            """,
            (symbol, signal, bool(qualified), sharpe, max_drawdown, oos_return, buy_hold_return),
        )
        conn.commit()


def get_signal_promotion(symbol: str, signal: str = "trend") -> dict | None:
    """Return the most recent OOS promotion record for (symbol, signal)."""
    symbol = symbol.upper()
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT qualified, sharpe, max_drawdown, oos_return,
                   buy_hold_return, evaluated_at
            FROM signal_promotion
            WHERE symbol = %s AND signal = %s;
            """,
            (symbol, signal),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "symbol": symbol,
        "signal": signal,
        "qualified": bool(row[0]),
        "sharpe": row[1],
        "max_drawdown": row[2],
        "oos_return": row[3],
        "buy_hold_return": row[4],
        "evaluated_at": row[5],
    }


def list_qualified_symbols(signal: str = "trend") -> list[str]:
    """Return all symbols whose latest (symbol, signal) promotion is qualified."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT symbol FROM signal_promotion WHERE signal = %s AND qualified = TRUE;",
            (signal,),
        )
        return [r[0] for r in cur.fetchall()]


# ---- Preferred provider per asset -------------------------------------------

def set_preferred_provider(symbol: str, provider: str) -> None:
    """Pin a preferred data provider for the asset; empty string clears it."""
    symbol = symbol.upper()
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE assets SET preferred_provider = %s WHERE symbol = %s;",
            (provider or None, symbol),
        )
        conn.commit()


def get_preferred_provider(symbol: str) -> str | None:
    """Return the preferred provider for the asset, or None if not set."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT preferred_provider FROM assets WHERE symbol = %s;",
            (symbol.upper(),),
        )
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def record_ingest_provider(symbol: str, provider: str, ts: datetime | None = None) -> None:
    """Record the provider used for the latest ingest run."""
    symbol = symbol.upper()
    ts = ts or datetime.now(UTC)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE assets SET last_provider = %s, last_ingest_at = %s WHERE symbol = %s;",
            (provider, ts, symbol),
        )
        conn.commit()


def get_provider_status(symbol: str) -> dict | None:
    """Return the stored provider info for an asset, or None if unknown."""
    symbol = symbol.upper()
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT preferred_provider, last_provider, last_ingest_at "
            "FROM assets WHERE symbol = %s;",
            (symbol,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "symbol": symbol,
        "preferred_provider": row[0],
        "last_provider": row[1],
        "last_ingest_at": row[2],
    }
