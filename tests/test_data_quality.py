"""Tests for calendar-aware OHLCV quality auditing."""

from datetime import date, datetime

import pandas as pd
import pytest

from arthaai.research.data_quality import audit_history, depth_summary, history_depth


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


def test_history_depth_reports_counts_and_bounds():
    dates = pd.date_range("2020-01-01", periods=6, freq="D", tz="UTC")
    frames = {
        "AAA": _bars(dates),
        "BBB": pd.DataFrame(),
    }
    reports = history_depth(lambda sym: frames[sym], ["AAA", "BBB"])
    assert reports[0].bars == 6
    assert reports[0].first_date == "2020-01-01"
    assert reports[0].last_date == "2020-01-06"
    assert reports[1].bars == 0


def test_depth_from_rows_builds_reports():
    from arthaai.research.data_quality import depth_from_rows

    rows = [
        ("aaa", 3000, pd.Timestamp("2016-01-04", tz="UTC"), pd.Timestamp("2026-01-02", tz="UTC")),
        ("BBB", 0, None, None),
    ]
    reports = depth_from_rows(rows)
    assert reports[0].symbol == "AAA"
    assert reports[0].bars == 3000
    assert reports[0].first_date == "2016-01-04"
    assert reports[1].bars == 0
    assert reports[1].first_date is None


def test_depth_summary_flags_a_shallow_table():
    from arthaai.research.data_quality import DepthReport

    reports = [
        DepthReport("AAA", 600, "2024-01-01", "2025-01-01"),
        DepthReport("BBB", 520, "2024-01-01", "2025-01-01"),
        DepthReport("CCC", 480, "2024-01-01", "2025-01-01"),
    ]
    summary = depth_summary(reports, min_bars=2520)
    assert summary["min"] == 480
    assert summary["median"] == 520
    assert summary["below_min"] == 3
    assert summary["median_ok"] is False
    ok = depth_summary([DepthReport("AAA", 3000, "a", "b")], min_bars=2520)
    assert ok["median_ok"] is True