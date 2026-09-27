"""Daily-bar canonicalisation and de-duplication (dual-provider ingest fix)."""

import pandas as pd

from arthaai.db.timescale import _canonical_ts
from arthaai.factors.panel import build_panel


def test_daily_ts_floors_to_midnight_utc():
    ts = pd.Timestamp("2025-01-02 13:30:00", tz="UTC")
    out = _canonical_ts(ts, "1d")
    assert out == pd.Timestamp("2025-01-02 00:00:00", tz="UTC")


def test_daily_ts_is_timezone_normalised():
    ts = pd.Timestamp("2025-01-02 09:30:00", tz="America/New_York")  # 14:30 UTC
    out = _canonical_ts(ts, "1d")
    assert out.tz is not None
    assert (out.hour, out.minute) == (0, 0)
    assert out.tz_convert("UTC").day == 2


def test_intraday_ts_is_unchanged():
    ts = pd.Timestamp("2025-01-02 13:30:00", tz="UTC")
    assert _canonical_ts(ts, "1h") == ts


def test_same_day_bar_times_collapse_to_one_key():
    am = _canonical_ts(pd.Timestamp("2025-01-02 00:00:00", tz="UTC"), "1d")
    pm = _canonical_ts(pd.Timestamp("2025-01-02 13:30:00", tz="UTC"), "1d")
    assert am == pm


def test_build_panel_collapses_duplicate_dates():
    dates = pd.to_datetime(["2025-01-02", "2025-01-02 13:30", "2025-01-03"], utc=True, format="mixed")
    df = pd.DataFrame({
        "open": [1.0, 1.1, 2.0], "high": [1.0, 1.1, 2.0], "low": [1.0, 1.1, 2.0],
        "close": [1.0, 1.1, 2.0], "volume": [10.0, 11.0, 20.0],
    }, index=dates)
    panel = build_panel({"GLD": df})
    assert len(panel["close"]) == 2  # duplicate day collapsed
    # keep='last' -> the later 13:30 bar wins
    assert panel["close"].iloc[0, 0] == 1.1
