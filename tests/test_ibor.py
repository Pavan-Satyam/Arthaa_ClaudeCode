"""DuckDB-backed integration tests for the local research store."""

import pandas as pd
import pytest

duckdb = pytest.importorskip("duckdb")

from arthaai.data.ibor import IBORStorageManager


def test_ingest_parquet_and_query_wide_returns(tmp_path):
    source = tmp_path / "bars.parquet"
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2025-01-02", "2025-01-03", "2025-01-02", "2025-01-03"], utc=True
            ),
            "symbol": ["aapl", "aapl", "msft", "msft"],
            "open": [100.0, 110.0, 200.0, 220.0],
            "high": [101.0, 111.0, 201.0, 221.0],
            "low": [99.0, 109.0, 199.0, 219.0],
            "close": [100.0, 110.0, 200.0, 220.0],
            "volume": [1000.0, 1200.0, 2000.0, 2400.0],
        }
    )
    source_db = duckdb.connect()
    source_db.register("source_bars", frame)
    source_db.execute("COPY source_bars TO ? (FORMAT PARQUET)", [str(source)])
    source_db.close()

    with IBORStorageManager(tmp_path / "research.duckdb") as store:
        assert store.ingest_parquet(source) == 4
        bars = store.query_ohlcv("2025-01-02", "2025-01-04", ["AAPL"])
        assert list(bars["ticker"].unique()) == ["AAPL"]
        assert len(bars) == 2

        returns = store.query_returns("2025-01-02", "2025-01-04")
        assert returns.loc[pd.Timestamp("2025-01-03", tz="UTC"), "AAPL"] == pytest.approx(0.1)
        assert returns.loc[pd.Timestamp("2025-01-03", tz="UTC"), "MSFT"] == pytest.approx(0.1)


def test_ingest_rejects_missing_ohlcv_columns(tmp_path):
    source = tmp_path / "incomplete.parquet"
    source_db = duckdb.connect()
    source_db.execute(
        "CREATE TABLE incomplete AS SELECT TIMESTAMP '2025-01-02' AS ts, 'AAPL' AS ticker"
    )
    source_db.execute("COPY incomplete TO ? (FORMAT PARQUET)", [str(source)])
    source_db.close()

    with IBORStorageManager() as store, pytest.raises(
        ValueError, match="open, high, low, close"
    ):
        store.ingest_parquet(source)