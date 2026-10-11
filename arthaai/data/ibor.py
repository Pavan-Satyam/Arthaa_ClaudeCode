"""Local DuckDB Investment Book of Record for offline research datasets."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Self

import pandas as pd


class IBORStorageManager:
    """Store ticks and OHLCV bars in an optional local DuckDB database.

    This analytical store is separate from the operational TimescaleDB path.
    Install the ``research`` extra to use it.
    """

    def __init__(self, database: str | Path = ":memory:") -> None:
        try:
            import duckdb
        except ImportError as exc:
            raise RuntimeError(
                "DuckDB support requires `pip install -e '.[research]'`."
            ) from exc
        self._connection = duckdb.connect(str(database))
        self._connection.execute("SET TimeZone = 'UTC'")
        self.create_schema()

    def create_schema(self) -> None:
        """Create idempotent, columnar-friendly tick and OHLCV tables."""
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tick_data (
                timestamp TIMESTAMPTZ NOT NULL,
                ticker VARCHAR NOT NULL,
                price DOUBLE NOT NULL,
                volume DOUBLE,
                venue VARCHAR NOT NULL,
                PRIMARY KEY (timestamp, ticker, venue)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS ohlcv_bars (
                timestamp TIMESTAMPTZ NOT NULL,
                ticker VARCHAR NOT NULL,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                PRIMARY KEY (timestamp, ticker)
            )
            """
        )

    @staticmethod
    def _quote_identifier(identifier: str) -> str:
        return '"' + identifier.replace('"', '""') + '"'

    def ingest_parquet(self, file_path: str | Path) -> int:
        """Bulk upsert a Parquet OHLCV file and return its source row count.

        Accepted timestamp columns are ``timestamp``, ``ts``, ``datetime``,
        or ``date``; accepted symbol columns are ``ticker``, ``symbol``, or
        ``instrument``. OHLCV columns are required except volume.
        """
        path = str(Path(file_path).expanduser().resolve())
        description = self._connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [path]
        ).fetchall()
        columns = {str(row[0]).lower(): str(row[0]) for row in description}

        def find_column(candidates: tuple[str, ...]) -> str | None:
            for candidate in candidates:
                if candidate in columns:
                    return columns[candidate]
            return None

        timestamp = find_column(("timestamp", "ts", "datetime", "date"))
        ticker = find_column(("ticker", "symbol", "instrument"))
        required = {name: find_column((name,)) for name in ("open", "high", "low", "close")}
        missing = [name for name, value in required.items() if value is None]
        if timestamp is None or ticker is None or missing:
            missing_fields = missing
            if timestamp is None:
                missing_fields.append("timestamp/ts/datetime/date")
            if ticker is None:
                missing_fields.append("ticker/symbol/instrument")
            raise ValueError(f"Parquet file is missing required fields: {', '.join(missing_fields)}")

        volume = find_column(("volume",))
        source = self._quote_identifier
        volume_expression = f"CAST({source(volume)} AS DOUBLE)" if volume else "NULL::DOUBLE"
        select_sql = f"""
            SELECT
                CAST({source(timestamp)} AS TIMESTAMPTZ),
                upper(CAST({source(ticker)} AS VARCHAR)),
                CAST({source(required['open'])} AS DOUBLE),
                CAST({source(required['high'])} AS DOUBLE),
                CAST({source(required['low'])} AS DOUBLE),
                CAST({source(required['close'])} AS DOUBLE),
                {volume_expression}
            FROM read_parquet(?)
            WHERE {source(timestamp)} IS NOT NULL AND {source(ticker)} IS NOT NULL
        """
        row_count = self._connection.execute(
            "SELECT count(*) FROM read_parquet(?)", [path]
        ).fetchone()[0]
        self._connection.execute(
            f"INSERT OR REPLACE INTO ohlcv_bars {select_sql}", [path]
        )
        return int(row_count)

    def query_ohlcv(
        self,
        start: str | date | datetime,
        end: str | date | datetime,
        tickers: list[str] | None = None,
    ) -> pd.DataFrame:
        """Return a tidy OHLCV time slice for one or more assets."""
        sql = """
            SELECT timestamp AS ts, ticker, open, high, low, close, volume
            FROM ohlcv_bars
            WHERE timestamp >= CAST(? AS TIMESTAMPTZ)
              AND timestamp < CAST(? AS TIMESTAMPTZ)
        """
        parameters: list[Any] = [str(start), str(end)]
        if tickers is not None:
            if not tickers:
                return pd.DataFrame(columns=["ts", "ticker", "open", "high", "low", "close", "volume"])
            sql += " AND ticker IN (" + ", ".join("?" for _ in tickers) + ")"
            parameters.extend(ticker.upper() for ticker in tickers)
        sql += " ORDER BY timestamp, ticker"
        return self._connection.execute(sql, parameters).fetchdf()

    def query_returns(
        self,
        start: str | date | datetime,
        end: str | date | datetime,
        tickers: list[str] | None = None,
    ) -> pd.DataFrame:
        """Return a wide daily return frame suitable for factor correlations."""
        bars = self.query_ohlcv(start, end, tickers)
        if bars.empty:
            return pd.DataFrame()
        close = bars.pivot(index="ts", columns="ticker", values="close").sort_index()
        return close.pct_change(fill_method=None)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()