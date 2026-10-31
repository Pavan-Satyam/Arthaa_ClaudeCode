"""CFTC Commitments of Traders (COT) adapter — free, weekly, point-in-time.

The COT report shows futures positioning (non-commercial/speculator vs commercial).
Records are keyed by the **Tuesday** report date, but the report is **released the
following Friday at 3:30pm ET**. Joining on the Tuesday date would let a backtest
trade on positioning three days before it was public, so every series here is
shifted to its ``effective_date`` (Tuesday + 3 business days) before it touches a
signal.

Source: CFTC Public Reporting Environment (Socrata), free since 1995.
"""

from __future__ import annotations

import pandas as pd

from arthaai.data.pit import effective_dates_are_public, release_lag_shift

# Tuesday report -> Friday 3:30pm ET release = 3 business days.
CFTC_RELEASE_BUSINESS_DAYS = 3

COT_DATASET_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

# Frozen-universe commodity ETFs -> CFTC futures-only market name. DBC is a broad
# basket with no single contract, so it is intentionally absent (best-effort only).
COMMODITY_COT_CONTRACTS: dict[str, str] = {
    "GLD": "GOLD - COMMODITY EXCHANGE INC.",
    "SLV": "SILVER - COMMODITY EXCHANGE INC.",
    "USO": "CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE",
}

_DATE_FIELD = "report_date_as_yyyy_mm_dd"
_LONG_FIELD = "noncomm_positions_long_all"
_SHORT_FIELD = "noncomm_positions_short_all"


def net_noncommercial(
    frame: pd.DataFrame,
    *,
    date_field: str = _DATE_FIELD,
    long_field: str = _LONG_FIELD,
    short_field: str = _SHORT_FIELD,
) -> pd.Series:
    """Net non-commercial positioning (long - short) indexed by Tuesday report date."""
    if frame is None or frame.empty:
        return pd.Series(dtype="float64")
    if not {date_field, long_field, short_field}.issubset(frame.columns):
        raise ValueError(
            f"COT frame missing one of {date_field!r}, {long_field!r}, {short_field!r}"
        )
    index = pd.DatetimeIndex(pd.to_datetime(frame[date_field], utc=True, errors="coerce"))
    net = (
        pd.to_numeric(frame[long_field], errors="coerce")
        - pd.to_numeric(frame[short_field], errors="coerce")
    )
    series = pd.Series(net.to_numpy(), index=index).dropna()
    series.index = series.index.normalize()
    return series[~series.index.isna()].sort_index()


def to_effective(series: pd.Series) -> pd.Series:
    """Shift Tuesday report dates to Friday effective (tradeable) dates."""
    if series is None or series.empty:
        return pd.Series(dtype="float64")
    out = series.copy()
    shifted = release_lag_shift(out.index, business_days=CFTC_RELEASE_BUSINESS_DAYS)
    # Self-check: the Tuesday report must only become effective on the Friday release.
    effective_dates_are_public(
        out.index, shifted, min_business_days=CFTC_RELEASE_BUSINESS_DAYS
    )
    out.index = shifted
    return out.sort_index()


def positioning_zscore(series: pd.Series, *, window: int = 156) -> pd.Series:
    """Causal rolling z-score of net positioning (default ~3y of weekly reports).

    Uses a trailing window only (a value at week *t* sees weeks <= *t*), so it is
    safe to feed a walk-forward backtest.
    """
    if series is None or series.empty:
        return pd.Series(dtype="float64")
    mean = series.rolling(window, min_periods=max(2, window // 4)).mean()
    std = series.rolling(window, min_periods=max(2, window // 4)).std(ddof=0)
    return ((series - mean) / std.replace(0.0, float("nan"))).dropna()


def fetch_cot(
    market: str,
    *,
    client=None,
    limit: int = 100000,
) -> pd.DataFrame:
    """Fetch one market's futures-only COT history from the CFTC Socrata API."""
    import httpx

    http = client or httpx
    params = {
        "$where": f"upper(market_and_exchange_names) like '%{market.upper()}%'",
        "$order": f"{_DATE_FIELD} ASC",
        "$limit": limit,
    }
    resp = http.get(COT_DATASET_URL, params=params, timeout=60.0)
    resp.raise_for_status()
    return pd.DataFrame(resp.json())


def cot_effective_series(
    market: str,
    *,
    client=None,
    frame: pd.DataFrame | None = None,
) -> pd.Series:
    """Net positioning for ``market``, dated at its effective (Friday) release."""
    data = frame if frame is not None else fetch_cot(market, client=client)
    return to_effective(net_noncommercial(data))
