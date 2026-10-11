"""Tests for OHLCV per-bar provenance persistence."""

from contextlib import contextmanager
from datetime import UTC, datetime

import pandas as pd

from arthaai.db import timescale


class _Cursor:
    rowcount = 2

    def __init__(self):
        self.sql = None
        self.records = None
        self.description = None
        self.rows = []

    def executemany(self, sql, records):
        self.sql = sql
        self.records = records

    def execute(self, sql, params):
        self.sql = sql
        self.params = params
        selected = sql.partition("FROM")[0].replace("SELECT", "").replace("DISTINCT ON (ts::date)", "")
        names = [name.strip() for name in selected.split(",") if name.strip()]
        self.description = [type("Column", (), {"name": name})() for name in names]
        self.rows = [tuple(range(len(names)))]

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, cursor):
        self.cursor_value = cursor
        self.committed = False

    def cursor(self):
        return _CursorContext(self.cursor_value)

    def commit(self):
        self.committed = True


class _CursorContext:
    def __init__(self, cursor):
        self.value = cursor

    def __enter__(self):
        return self.value

    def __exit__(self, exc_type, exc, traceback):
        return False


def _frame():
    return pd.DataFrame(
        {
            "ts": pd.to_datetime(["2025-01-02", "2025-01-03"], utc=True),
            "open": [10.0, 11.0],
            "high": [12.0, 13.0],
            "low": [9.0, 10.0],
            "close": [11.0, 12.0],
            "volume": [100.0, 110.0],
        }
    )


def _capture_upsert(monkeypatch, rows, **metadata):
    cursor = _Cursor()
    connection = _Connection(cursor)

    @contextmanager
    def fake_connection():
        yield connection

    monkeypatch.setattr(timescale, "connection", fake_connection)
    count = timescale.upsert_ohlcv("AAPL", "1d", rows, **metadata)
    return count, cursor, connection


def test_upsert_records_provider_retrieval_and_adjustment_basis(monkeypatch):
    retrieved_at = datetime(2025, 1, 4, 12, 0, tzinfo=UTC)
    count, cursor, connection = _capture_upsert(
        monkeypatch,
        _frame(),
        source_provider="vendor_x",
        adjustment_basis="split_adjusted_unadjusted_for_dividends",
        provider_symbol="vendor_x:AAPL",
        retrieved_at=retrieved_at,
    )

    assert count == 2
    assert connection.committed
    assert "source_provider" in cursor.sql
    assert "retrieved_at" in cursor.sql
    assert "adjustment_basis" in cursor.sql
    assert "source_provider = EXCLUDED.source_provider" in cursor.sql
    assert all(record[0] == "AAPL" for record in cursor.records)
    assert all(record[8] == "vendor_x" for record in cursor.records)
    assert all(record[9] == retrieved_at for record in cursor.records)
    assert all(
        record[10] == "split_adjusted_unadjusted_for_dividends"
        for record in cursor.records
    )
    assert all(record[11] == "vendor_x:AAPL" for record in cursor.records)
    assert all(record[12] == pd.Timestamp(record[1]) for record in cursor.records)
    assert all(record[13] == "canonical_ohlcv_v1" for record in cursor.records)


def test_unknown_legacy_source_is_persisted_as_null_not_guessed(monkeypatch):
    _, cursor, _ = _capture_upsert(monkeypatch, _frame())

    assert all(record[8] is None for record in cursor.records)
    assert all(record[10] is None for record in cursor.records)
    assert all(record[11] is None for record in cursor.records)
    assert all(record[9] is not None for record in cursor.records)
    assert all(record[13] == "canonical_ohlcv_v1" for record in cursor.records)


def test_empty_frame_does_not_open_database(monkeypatch):
    def fail_connection():
        raise AssertionError("empty upsert must not connect")

    monkeypatch.setattr(timescale, "connection", fail_connection)
    assert timescale.upsert_ohlcv("AAPL", "1d", _frame().iloc[:0]) == 0


def test_provenance_read_is_opt_in_and_preserves_default_columns(monkeypatch):
    cursor = _Cursor()
    connection = _Connection(cursor)

    @contextmanager
    def fake_connection():
        yield connection

    monkeypatch.setattr(timescale, "connection", fake_connection)
    standard = timescale.load_ohlcv("AAPL", limit=1)
    provenance = timescale.load_ohlcv("AAPL", limit=1, include_provenance=True)

    assert list(standard.columns) == ["ts", "open", "high", "low", "close", "volume"]
    assert list(provenance.columns) == [
        "ts", "open", "high", "low", "close", "volume",
        "source_provider", "retrieved_at", "adjustment_basis",
        "provider_symbol", "provider_timestamp", "normalization_version",
    ]