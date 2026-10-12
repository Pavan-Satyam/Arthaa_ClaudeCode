"""Provider adapter contract checks (ARTHA-232)."""

import pandas as pd

from arthaai.data.provider_contract import CANONICAL_COLUMNS, check_provider_contract


class _GoodProvider:
    name = "good"
    adjustment_basis = "raw"

    def is_available(self) -> bool:
        return True

    def provider_symbol(self, symbol: str) -> str:
        return f"{symbol}.X"

    def fetch_ohlcv(self, symbol, start, end, timeframe):
        ts = pd.date_range("2024-01-01", periods=5, freq="B", tz="UTC")
        return pd.DataFrame(
            {"ts": ts, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}
        )


class _EmptyProvider(_GoodProvider):
    name = "empty"

    def fetch_ohlcv(self, *args, **kwargs):
        return pd.DataFrame(columns=list(CANONICAL_COLUMNS))


class _BadProvider(_GoodProvider):
    name = "bad"

    def fetch_ohlcv(self, *args, **kwargs):
        return pd.DataFrame({"close": [1.0, 2.0]})  # missing canonical columns


class _RaisingProvider(_GoodProvider):
    name = "raising"

    def is_available(self) -> bool:
        raise RuntimeError("boom")


def test_good_provider_passes():
    report = check_provider_contract(_GoodProvider(), fetch=True)
    assert report.ok, report.checks


def test_empty_provider_passes_without_column_check():
    assert check_provider_contract(_EmptyProvider()).ok


def test_bad_provider_fails_canonical_columns():
    report = check_provider_contract(_BadProvider())
    assert not report.ok
    assert any(name == "canonical_columns" and not passed for name, passed, _ in report.checks)


def test_raising_provider_fails_is_available():
    report = check_provider_contract(_RaisingProvider(), fetch=False)
    assert not report.ok
    assert any(name == "is_available" and not passed for name, passed, _ in report.checks)
