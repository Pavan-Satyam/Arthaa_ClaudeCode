"""Tests for calendar-aware OHLCV quality auditing."""

from datetime import date, datetime

import pandas as pd
import pytest

from arthaai.research.data_quality import audit_history


class WeekdayCalendar:
    def sessions_in_range(self, start, end):
        return pd.bdate_range(start, end, tz="UTC")


def _bars(dates, *, high=None):
    count = len(dates)
    frame = pd.DataFrame(
        {
            "ts": pd.to_datetime(dates, utc=True),
            "open": [10.0] * count,
            "high": high or [11.0] * count,
            "low": [9.0] * count,
            "close": [10.5] * count,
            "volume": [100.0] * count,
        }
    )
    return frame


def test_complete_history_is_ready():
    report = audit_history(
        {"aapl": _bars(["2025-01-06", "2025-01-07", "2025-01-08"])},
        default_calendar="XNYS",
        as_of=date(2025, 1, 8),
        calendar_factory=lambda name: WeekdayCalendar(),
    )[0]

    assert report.symbol == "AAPL"
    assert report.expected_sessions == 3
    assert report.coverage_ratio == 1.0
    assert report.status == "ready"


def test_missing_session_and_staleness_are_reported_separately():
    report = audit_history(
        {"AAPL": _bars(["2025-01-06", "2025-01-08"])},
        default_calendar="XNYS",
        as_of=date(2025, 1, 10),
        max_stale_sessions=0,
        calendar_factory=lambda name: WeekdayCalendar(),
    )[0]

    assert report.missing_sessions == ["2025-01-07"]
    assert report.stale_sessions == 2
    assert report.status == "stale"


def test_duplicate_sessions_and_invalid_ohlc_are_flagged():
    frame = _bars(["2025-01-06", "2025-01-06"], high=[8.0, 11.0])
    report = audit_history(
        {"AAPL": frame},
        default_calendar="XNYS",
        as_of=date(2025, 1, 6),
        calendar_factory=lambda name: WeekdayCalendar(),
    )[0]

    assert report.duplicate_sessions == ["2025-01-06"]
    assert report.invalid_rows == 1
    assert report.status == "invalid"


def test_calendar_can_be_selected_per_symbol_and_empty_history_is_reported():
    reports = audit_history(
        {
            "AAPL": _bars(["2025-01-06"]),
            "VOD.L": pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"]),
        },
        calendar_by_symbol={"AAPL": "XNYS", "VOD.L": "XLON"},
        as_of=date(2025, 1, 6),
        calendar_factory=lambda name: WeekdayCalendar(),
    )

    assert reports[0].calendar == "XNYS"
    assert reports[1].calendar == "XLON"
    assert reports[1].status == "no_data"


def test_audit_requires_aware_as_of_datetime():
    with pytest.raises(ValueError, match="timezone-aware"):
        audit_history({}, as_of=datetime(2025, 1, 1))  # noqa: DTZ001 - verifies naive input rejection