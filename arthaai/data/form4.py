"""SEC Form 4 insider-transaction adapter — free EDGAR, point-in-time.

Form 4 discloses insider purchases/sales. The trade happens on ``transaction_date``
but only becomes public when EDGAR accepts the filing (``filing_date`` /
``acceptanceDateTime``), so aligning on ``transaction_date`` is a look-ahead. Every
series here is keyed by the disclosure date — the first session the data is usable.

Source: SEC EDGAR (free, keyless; descriptive User-Agent required). Form 4 is filed
within two business days, so the lag is short. Full multi-decade history is available
via EDGAR's nightly bulk submissions.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from arthaai.data.cache import ensure_dir, is_fresh
from arthaai.data.pit import effective_dates_are_public

# Insider filings refresh within two business days; a short TTL keeps repeated E3
# runs from refetching the whole universe.
_CACHE = Path(".cache/insider")
_MAX_CACHE_AGE_DAYS = 1

# EDGAR treats a filing accepted after 16:00 ET as effective the next business day
# for a market participant, even though the filing date is the same calendar day.
INSIDER_FILING_CLOSE_HOUR_ET = 16

# Transaction codes that add to an insider's position (open-market buys, grants,
# option exercises) vs. reduce it (open-market sales, tax withholding). "G"
# (bona fide gift) is deliberately in neither set: a gift is a transfer, not a
# bearish open-market signal, so it signs neutral (0) and does not fabricate flow.
_ACQUIRE_CODES = frozenset({"P", "A", "M", "C"})
_DISPOSE_CODES = frozenset({"S", "F", "D", "E"})


def effective_from_filing(filing) -> pd.DatetimeIndex:
    """Effective (public) date for Form 4 filing dates/acceptance datetimes.

    A filing accepted after the 16:00 ET close is pushed to the next business day,
    matching when the market could first act on it. Date-only values (EDGAR
    ``filing_date``) are already the acceptance date and pass through unchanged.
    """
    parsed = pd.DatetimeIndex(pd.to_datetime(pd.Index(filing), utc=True))
    day = parsed.normalize()
    next_day = day + pd.offsets.BDay(1)
    late = np.asarray(parsed.hour) >= INSIDER_FILING_CLOSE_HOUR_ET
    result = pd.DatetimeIndex(
        [nxt if is_late else d for d, nxt, is_late in zip(day, next_day, late)]
    )
    # Self-check: a filing may never become effective before it was accepted.
    effective_dates_are_public(pd.Index(filing), result)
    return result


def signed_shares(
    frame: pd.DataFrame,
    *,
    code_field: str = "transaction_code",
    shares_field: str = "shares",
    disposed_field: str = "acquired_disposed",
) -> pd.Series:
    """Signed insider share delta (+acquire / -dispose) per filing row.

    Prefers the explicit ``acquired_disposed`` flag (A/D) and falls back to the
    transaction code when the flag is absent.
    """
    if frame is None or frame.empty or shares_field not in frame.columns:
        return pd.Series(dtype="float64")
    shares = pd.to_numeric(frame[shares_field], errors="coerce").abs()
    sign = pd.Series(0.0, index=frame.index)
    if disposed_field in frame.columns:
        flag = frame[disposed_field].astype("string").str.upper()
        # .fillna(False): a nullable boolean with <NA> must not trigger mask.
        is_acquire = (flag == "A").fillna(False)
        is_dispose = (flag == "D").fillna(False)
        sign = sign.mask(is_acquire, 1.0).mask(is_dispose, -1.0)
    if code_field in frame.columns:
        code = frame[code_field].astype("string").str.upper()
        inferred = pd.Series(0.0, index=frame.index)
        inferred = inferred.mask(code.isin(_ACQUIRE_CODES), 1.0).mask(
            code.isin(_DISPOSE_CODES), -1.0
        )
        sign = sign.where(sign != 0.0, inferred)
    return (sign * shares).dropna()


def insider_net_buy(
    frame: pd.DataFrame,
    *,
    date_field: str = "filing_date",
) -> pd.Series:
    """Net insider shares filed per effective disclosure date.

    The PIT anchor is the filing/acceptance date (front-run safe), never
    ``transaction_date``.
    """
    if frame is None or frame.empty or date_field not in frame.columns:
        return pd.Series(dtype="float64")
    signed = signed_shares(frame)
    if signed.empty:
        return pd.Series(dtype="float64")
    # signed_shares() drops rows with unusable shares, so restrict the dates to the
    # surviving index; otherwise the value/date arrays misalign (or raise).
    effective = effective_from_filing(frame.loc[signed.index, date_field])
    series = pd.Series(signed.to_numpy(), index=effective).dropna()
    series = series[~series.index.isna()]
    return series.groupby(level=0).sum().sort_index()


def fetch_insider_trades(
    ticker: str,
    *,
    limit: int = 100,
    processor=None,
    force: bool = False,
) -> pd.DataFrame:
    """Fetch recent Form 4 transactions for ``ticker``, cached on disk.

    The cache is best-effort (a read-only CWD just skips it) and short-lived, so
    repeated E3 runs don't refetch the whole universe. Pass a shared ``processor``
    to reuse one SEC client across symbols.
    """
    from arthaai.data.fundamentals import SECDataProcessor

    path = _CACHE / f"{ticker.upper()}_{limit}.csv"
    if not force and path.exists() and is_fresh(path, max_age_days=_MAX_CACHE_AGE_DAYS):
        try:
            return pd.read_csv(path)
        except (OSError, ValueError):
            pass
    proc = processor or SECDataProcessor()
    frame = proc.get_insider_trades(ticker, limit=limit)
    if ensure_dir(_CACHE):
        try:
            frame.to_csv(path, index=False)
        except OSError:
            pass
    return frame


def insider_effective_series(
    ticker: str,
    *,
    limit: int = 100,
    frame: pd.DataFrame | None = None,
    processor=None,
) -> pd.Series:
    """Net insider buying for ``ticker``, dated at the effective (filing) date."""
    data = frame if frame is not None else fetch_insider_trades(
        ticker, limit=limit, processor=processor
    )
    return insider_net_buy(data)
