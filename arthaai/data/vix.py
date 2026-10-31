"""Cboe volatility-index adapter — free daily CSVs, point-in-time.

VIX is the 30-day implied-volatility index; VIX3M is the 3-month one. Their ratio
(VIX / VIX3M) is a term-structure regime gauge: > 1 means the curve is inverted
(near-term stress), < 1 means calm/contango. Both are published after the close of
their own session, so a date-*t* value describes session *t* and is usable from the
following session — the level is a price-like, non-revised series.

Source: Cboe daily-price CSV (`VIX_History.csv`, `VIX3M_History.csv`), free.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import httpx
import pandas as pd

from arthaai.data.cache import ensure_dir, is_fresh

# Relative ``.cache`` matches the repo convention (macro_series, fundamentals_pit).
_CACHE = Path(".cache/cboe")
# Cboe history files are full snapshots refreshed daily; treat older as stale.
_MAX_CACHE_AGE_DAYS = 1
_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv"


def _read_cache(path: Path) -> pd.Series | None:
    try:
        series = parse_cboe_csv(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    return series if not series.empty else None


def parse_cboe_csv(text: str) -> pd.Series:
    """Parse a Cboe ``*_History.csv`` body into a date-indexed close series."""
    if text is None or text.lstrip().startswith("<"):
        return pd.Series(dtype="float64")
    frame = pd.read_csv(StringIO(text))
    cols = {c.strip().upper(): c for c in frame.columns}
    if "DATE" not in cols or "CLOSE" not in cols:
        return pd.Series(dtype="float64")
    index = pd.to_datetime(frame[cols["DATE"]], utc=True, errors="coerce")
    close = pd.to_numeric(frame[cols["CLOSE"]], errors="coerce")
    series = pd.Series(close.to_numpy(), index=index).dropna()
    series.index = series.index.normalize()
    return series[~series.index.isna()].sort_index()


def fetch_cboe_index(symbol: str, *, client=None, force: bool = False) -> pd.Series:
    """Fetch one Cboe index's daily close history as a cached ``pd.Series``.

    Cache failures degrade gracefully: a read-only working directory skips caching
    (still returns fresh data), and a fetch failure falls back to a stale cache
    rather than erroring the whole axis.
    """
    path = _CACHE / f"{symbol.upper()}_History.csv"
    cached = _read_cache(path) if path.exists() else None
    if cached is not None and not force and is_fresh(path, max_age_days=_MAX_CACHE_AGE_DAYS):
        return cached
    http = client or httpx
    try:
        resp = http.get(_URL.format(symbol=symbol.upper()), timeout=30.0)
        resp.raise_for_status()
    except (httpx.HTTPError, OSError):
        if cached is not None:
            return cached
        raise
    series = parse_cboe_csv(resp.text)
    if series.empty:
        if cached is not None:
            return cached
        raise ValueError(f"Cboe returned no parseable data for {symbol!r}")
    if ensure_dir(_CACHE):
        try:
            path.write_text(resp.text, encoding="utf-8")
        except OSError:
            pass  # read-only CWD: serve fresh data without caching
    return series


def term_structure_ratio(vix: pd.Series, vix3m: pd.Series) -> pd.Series:
    """VIX / VIX3M ratio aligned on the intersection of the two series."""
    if vix is None or vix3m is None or vix.empty or vix3m.empty:
        return pd.Series(dtype="float64")
    frame = pd.concat({"vix": vix, "vix3m": vix3m}, axis=1).dropna()
    if frame.empty:
        return pd.Series(dtype="float64")
    return (frame["vix"] / frame["vix3m"]).sort_index()


def vix_term_structure(*, client=None) -> pd.Series:
    """VIX/VIX3M term-structure ratio from Cboe CSVs (cached)."""
    return term_structure_ratio(
        fetch_cboe_index("VIX", client=client),
        fetch_cboe_index("VIX3M", client=client),
    )
