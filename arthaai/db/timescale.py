"""TimescaleDB access — connection, OHLCV upsert, and read helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

import pandas as pd
import psycopg

from arthaai.config import get_settings


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


def ensure_asset(symbol: str, name: str | None = None, asset_class: str = "equity") -> None:
    """Register an asset if it isn't already known, so OHLCV can reference it.

    Lets the platform analyse any ticker, not just the seeded universe. The FK on
    ohlcv(symbol) -> assets(symbol) requires this row to exist first.
    """
    symbol = symbol.upper()
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO assets (symbol, name, asset_class) VALUES (%s, %s, %s) "
            "ON CONFLICT (symbol) DO NOTHING;",
            (symbol, name or symbol, asset_class),
        )
        conn.commit()


def upsert_ohlcv(symbol: str, interval: str, rows: pd.DataFrame) -> int:
    """Insert/update OHLCV bars. `rows` has columns ts, open, high, low, close, volume."""
    if rows.empty:
        return 0
    records = [
        (symbol, r.ts.to_pydatetime(), interval, r.open, r.high, r.low, r.close, r.volume)
        for r in rows.itertuples(index=False)
    ]
    sql = """
        INSERT INTO ohlcv (symbol, ts, interval, open, high, low, close, volume)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, interval, ts) DO UPDATE
          SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
              close = EXCLUDED.close, volume = EXCLUDED.volume;
    """
    with connection() as conn, conn.cursor() as cur:
        cur.executemany(sql, records)
        conn.commit()
        return cur.rowcount


def load_ohlcv(symbol: str, interval: str = "1d", limit: int = 400) -> pd.DataFrame:
    """Return the most recent `limit` bars ascending by time."""
    sql = """
        SELECT ts, open, high, low, close, volume
        FROM ohlcv WHERE symbol = %s AND interval = %s
        ORDER BY ts DESC LIMIT %s;
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, (symbol, interval, limit))
        cols = [c.name for c in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
    return df.iloc[::-1].reset_index(drop=True)


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
    ts = ts or datetime.now(timezone.utc)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE assets SET last_provider = %s, last_ingest_at = %s WHERE symbol = %s;",
            (provider, ts, symbol),
        )
        conn.commit()
