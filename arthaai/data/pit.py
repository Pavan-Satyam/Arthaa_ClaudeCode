"""Point-in-time alignment shared by exogenous data adapters.

The E3 protocol forbids look-ahead: a value is usable only from the moment it was
*publicly released*, not the period it describes. Official datasets are keyed by a
reference/period date (CFTC's Tuesday report, EIA's Friday period, FINRA's
settlement date), but the numbers only reach the market after a publication lag.
Each adapter therefore maps its reference dates to an ``effective_date`` — the
first session on which the data was tradeable — and aligns to OHLCV with a
backward as-of join, so a bar can never see data that was not yet public.

This mirrors the discipline already used for fundamentals
(``arthaai.data.fundamentals_pit.pit_latest``: a fact is usable from its filing
date onward).
"""

from __future__ import annotations

import pandas as pd


def release_lag_shift(
    reference,
    *,
    business_days: int = 0,
    calendar_days: int = 0,
) -> pd.DatetimeIndex:
    """Map reference/period dates to effective (release) dates.

    ``business_days`` skips weekends/holidays (e.g. CFTC's Tue report -> Fri
    release); ``calendar_days`` is a plain day offset (e.g. EIA's Fri period ->
    Wed release). Both may be combined. The result is normalized to UTC midnight.
    """
    index = pd.DatetimeIndex(pd.to_datetime(reference, utc=True)).normalize()
    out = index
    if business_days:
        out = out + pd.offsets.BDay(business_days)
    if calendar_days:
        out = out + pd.Timedelta(days=calendar_days)
    return out


def asof_align(series: pd.Series | None, dates) -> pd.Series:
    """Backward as-of align a release-date-indexed series onto ``dates``.

    A date *t* in ``dates`` receives the most recent series value whose effective
    (release) date is <= *t*; dates before any release are NaN. This is the
    point-in-time join that keeps an exogenous axis causal.
    """
    index = pd.DatetimeIndex(pd.to_datetime(dates, utc=True)).normalize()
    if series is None or series.empty:
        return pd.Series(index=index, dtype="float64")
    s = series.copy()
    s.index = pd.DatetimeIndex(pd.to_datetime(s.index, utc=True)).normalize()
    s = s[~s.index.isna()].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    union = index.union(s.index)
    return s.reindex(union).ffill().reindex(index)


def effective_dates_are_public(
    reference, effective, *, min_business_days: int = 0
) -> bool:
    """Guard: every effective date is on/after its reference date (+ lag).

    Raises ``ValueError`` if any effective date precedes its reference date, which
    would be a look-ahead bug. Returns True otherwise. Used by adapter tests and
    by the adapters themselves as a self-check.
    """
    ref = pd.DatetimeIndex(pd.to_datetime(reference, utc=True)).normalize()
    eff = pd.DatetimeIndex(pd.to_datetime(effective, utc=True)).normalize()
    if len(ref) != len(eff):
        raise ValueError("reference and effective date arrays differ in length")
    if (eff < ref).any():
        raise ValueError("effective_date precedes reference date: look-ahead")
    if min_business_days:
        floor = ref + pd.offsets.BDay(min_business_days)
        if (eff < floor).any():
            raise ValueError(
                f"effective_date is less than reference + {min_business_days} "
                "business days: release lag not applied"
            )
    return True
