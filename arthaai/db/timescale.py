"""TimescaleDB access — connection, OHLCV upsert, and read helpers."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

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
