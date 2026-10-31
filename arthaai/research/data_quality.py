"""Exchange-calendar-aware quality reports for stored OHLCV histories."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class DepthReport:
    """Stored-history depth for one symbol (bars + first/last session)."""

    symbol: str
    bars: int
    first_date: str | None
    last_date: str | None


def history_depth(
    loader: Callable[[str], pd.DataFrame],
    symbols: list[str],
) -> list[DepthReport]:
    """Row count and first/last stored session per symbol (no calendar needed).

    ``loader(symbol)`` must return a frame with a ``ts`` column or a DatetimeIndex.
    For a DB path prefer ``depth_from_rows`` with an aggregate query so full frames
    are not materialized. This is the cheap pre-flight check for an E3 run: it tells
    you whether the stored history can support a ~10-year evaluation, independent of
    the ``--limit`` a command is asked for (``load_ohlcv`` is a SQL LIMIT on the
    most-recent bars and cannot pad a shallow table).
    """
    reports: list[DepthReport] = []
    for raw_symbol in symbols:
        symbol = str(raw_symbol).upper()
        frame = loader(symbol)
        if frame is None or frame.empty:
            reports.append(DepthReport(symbol=symbol, bars=0, first_date=None, last_date=None))
            continue
        if "ts" in frame.columns:
            timestamps = pd.to_datetime(frame["ts"], utc=True, errors="coerce")
        else:
            timestamps = pd.to_datetime(frame.index, utc=True, errors="coerce")
        valid = timestamps[~pd.isna(timestamps)]
        if len(valid) == 0:
            reports.append(DepthReport(symbol=symbol, bars=0, first_date=None, last_date=None))
            continue
        reports.append(
            DepthReport(
                symbol=symbol,
                bars=len(valid),
                first_date=pd.Timestamp(valid.min()).date().isoformat(),
                last_date=pd.Timestamp(valid.max()).date().isoformat(),
            )
        )
    return reports


def depth_from_rows(rows: list[tuple[str, int, Any, Any]]) -> list[DepthReport]:
    """Build ``DepthReport``s from aggregated DB rows ``(symbol, bars, first, last)``.

    Lets the ``history-depth`` command use a single ``GROUP BY`` aggregate instead of
    loading full OHLCV frames per symbol.
    """
    reports: list[DepthReport] = []
    for symbol, bars, first_ts, last_ts in rows:
        first = pd.Timestamp(first_ts).date().isoformat() if first_ts is not None else None
        last = pd.Timestamp(last_ts).date().isoformat() if last_ts is not None else None
        reports.append(
            DepthReport(
                symbol=str(symbol).upper(),
                bars=bars if bars is not None else 0,
                first_date=first,
                last_date=last,
            )
        )
    return reports


def depth_summary(reports: list[DepthReport], *, min_bars: int) -> dict[str, Any]:
    """Summarize depth across symbols and flag a globally shallow history."""
    bars = sorted(r.bars for r in reports if r.bars > 0)
    if not bars:
        return {"count": 0, "min": 0, "median": 0, "max": 0, "below_min": 0, "median_ok": False}
    median = bars[len(bars) // 2]
    return {
        "count": len(bars),
        "min": bars[0],
        "median": median,
        "max": bars[-1],
        "below_min": sum(1 for b in bars if b < min_bars),
        "median_ok": median >= min_bars,
    }


@dataclass
class HistoryCoverage:
    symbol: str
    calendar: str
    bars: int
    first_date: str | None
    last_date: str | None
    expected_sessions: int
    observed_sessions: int
    coverage_ratio: float
    missing_sessions: list[str]
    stale_sessions: int
    duplicate_sessions: list[str]
    invalid_rows: int
    status: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _calendar(calendar_name: str, factory: Callable[[str], Any] | None):
    if factory is not None:
        return factory(calendar_name)
    try:
        import exchange_calendars
    except ImportError as exc:
        raise RuntimeError(
            "History coverage requires `pip install -e '.[market-data]'`."
        ) from exc
    return exchange_calendars.get_calendar(calendar_name)


def _calendar_dates(calendar, start: date, end: date) -> list[date]:
    sessions = calendar.sessions_in_range(start.isoformat(), end.isoformat())
    return [timestamp.date() for timestamp in pd.to_datetime(sessions, utc=True)]


def _invalid_ohlc_rows(frame: pd.DataFrame) -> int:
    values = frame[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    invalid = ~np.isfinite(values.to_numpy(dtype=float)).all(axis=1)
    invalid |= (values <= 0).any(axis=1).to_numpy()
    invalid |= (values["high"] < values[["open", "close", "low"]].max(axis=1)).to_numpy()
    invalid |= (values["low"] > values[["open", "close", "high"]].min(axis=1)).to_numpy()
    if "volume" in frame:
        volume = pd.to_numeric(frame["volume"], errors="coerce")
        invalid |= (~np.isfinite(volume.to_numpy(dtype=float))) | (volume.to_numpy(dtype=float) < 0)
    return int(invalid.sum())


def audit_history(
    data_map: dict[str, pd.DataFrame],
    *,
    calendar_by_symbol: dict[str, str] | None = None,
    default_calendar: str | None = None,
    as_of: date | datetime | None = None,
    max_stale_sessions: int = 1,
    calendar_factory: Callable[[str], Any] | None = None,
) -> list[HistoryCoverage]:
    """Audit daily bars against official sessions for each symbol's exchange.

    Calendar names use ``exchange_calendars`` identifiers such as ``XNYS`` or
    ``XLON``. A single missing session can be treated as a data-quality finding;
    this report never fills or mutates stored bars.
    """
    if max_stale_sessions < 0:
        raise ValueError("max_stale_sessions must be non-negative")
    if as_of is None:
        as_of_date = datetime.now(tz=UTC).date()
    elif isinstance(as_of, datetime):
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of datetime must be timezone-aware")
        as_of_date = as_of.astimezone(UTC).date()
    else:
        as_of_date = as_of

    calendars = {symbol.upper(): name.upper() for symbol, name in (calendar_by_symbol or {}).items()}
    reports = []
    for raw_symbol, raw_frame in data_map.items():
        symbol = raw_symbol.upper()
        calendar_name = calendars.get(symbol, default_calendar)
        if not calendar_name:
            raise ValueError(f"no exchange calendar configured for {symbol}")
        frame = raw_frame.copy()
        if "ts" in frame.columns:
            timestamps = pd.to_datetime(frame["ts"], utc=True, errors="coerce")
        else:
            timestamps = pd.to_datetime(frame.index, utc=True, errors="coerce")
        valid_timestamps = timestamps[~pd.isna(timestamps)]
        frame = frame.loc[~pd.isna(timestamps)].copy()
        frame["_session"] = pd.DatetimeIndex(valid_timestamps).normalize().date

        missing_columns = {"open", "high", "low", "close"} - set(frame.columns)
        if missing_columns:
            raise ValueError(f"{symbol} OHLCV history missing columns: {sorted(missing_columns)}")
        if frame.empty:
            reports.append(
                HistoryCoverage(
                    symbol=symbol, calendar=calendar_name, bars=0, first_date=None,
                    last_date=None, expected_sessions=0, observed_sessions=0,
                    coverage_ratio=0.0, missing_sessions=[], stale_sessions=0,
                    duplicate_sessions=[], invalid_rows=0, status="no_data",
                )
            )
            continue

        session_counts = frame["_session"].value_counts()
        observed_dates = set(session_counts.index)
        first_date, last_date = min(observed_dates), max(observed_dates)
        exchange_calendar = _calendar(calendar_name, calendar_factory)
        expected_range = _calendar_dates(exchange_calendar, first_date, min(last_date, as_of_date))
        expected_all = _calendar_dates(exchange_calendar, first_date, as_of_date)
        expected_set = set(expected_range)
        missing = sorted(expected_set - observed_dates)
        stale = sum(session > last_date for session in expected_all)
        duplicates = sorted(session for session, count in session_counts.items() if count > 1)
        observed_sessions = len(expected_set & observed_dates)
        expected_sessions = len(expected_range)
        ratio = observed_sessions / expected_sessions if expected_sessions else 0.0
        invalid_rows = _invalid_ohlc_rows(frame)
        if invalid_rows or duplicates:
            status = "invalid"
        elif stale > max_stale_sessions:
            status = "stale"
        elif missing:
            status = "incomplete"
        else:
            status = "ready"

        reports.append(
            HistoryCoverage(
                symbol=symbol,
                calendar=calendar_name,
                bars=len(frame),
                first_date=first_date.isoformat(),
                last_date=last_date.isoformat(),
                expected_sessions=expected_sessions,
                observed_sessions=observed_sessions,
                coverage_ratio=ratio,
                missing_sessions=[session.isoformat() for session in missing],
                stale_sessions=stale,
                duplicate_sessions=[session.isoformat() for session in duplicates],
                invalid_rows=invalid_rows,
                status=status,
            )
        )
    return reports