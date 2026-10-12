"""Canonical OHLCV provider contract (ARTHA-232).

Any adapter — built-in or a future vendor package — must satisfy this contract so
consumers never depend on vendor SDK types. ``check_provider_contract`` is the
reusable acceptance test a vendor package should run before it is registered via
``register_provider``; it makes the ingestion interface explicit so future data
procurement plugs in without schema refactoring.

Contract:
- ``name`` and ``adjustment_basis`` are present, non-empty strings.
- ``is_available()`` returns a bool without raising.
- ``provider_symbol(symbol)`` returns a non-empty string.
- ``fetch_ohlcv(symbol, start, end, timeframe)`` returns a DataFrame with the
  canonical columns or an empty DataFrame; when non-empty, ``ts`` is ascending
  with no duplicate timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

CANONICAL_COLUMNS = ("ts", "open", "high", "low", "close", "volume")


@dataclass
class ContractReport:
    provider: str
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(passed for _, passed, _ in self.checks)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append((name, bool(passed), detail))


def check_provider_contract(
    provider: Any,
    *,
    symbol: str = "GLD",
    start: datetime | None = None,
    end: datetime | None = None,
    timeframe: str = "1d",
    fetch: bool = True,
) -> ContractReport:
    """Run the provider acceptance checks; returns a pass/fail report."""
    report = ContractReport(provider=str(getattr(provider, "name", type(provider).__name__)))
    report.add("name", bool(getattr(provider, "name", "")))
    report.add("adjustment_basis", bool(getattr(provider, "adjustment_basis", "")))

    try:
        report.add("is_available", isinstance(provider.is_available(), bool))
    except Exception as exc:  # noqa: BLE001 - a raising provider fails the contract
        report.add("is_available", False, str(exc))

    try:
        provider_symbol = provider.provider_symbol(symbol)
        report.add("provider_symbol", isinstance(provider_symbol, str) and bool(provider_symbol))
    except Exception as exc:  # noqa: BLE001
        report.add("provider_symbol", False, str(exc))

    if fetch:
        end = end or datetime.now(UTC)
        start = start or (end - timedelta(days=30))
        try:
            frame = provider.fetch_ohlcv(symbol, start, end, timeframe)
            report.add("fetch_returns_frame", isinstance(frame, pd.DataFrame))
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                report.add("canonical_columns", set(CANONICAL_COLUMNS).issubset(frame.columns))
                if "ts" in frame.columns:
                    ts = pd.to_datetime(frame["ts"], utc=True, errors="coerce")
                    report.add(
                        "ts_sorted_unique",
                        bool(ts.is_monotonic_increasing and not ts.duplicated().any()),
                    )
        except Exception as exc:  # noqa: BLE001
            report.add("fetch_returns_frame", False, str(exc))
    return report
