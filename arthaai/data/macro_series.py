"""Keyless macro series via FRED's public CSV endpoint.

No API key required. The daily treasury series used here (yields and spreads) are
market data and non-revised, so they are point-in-time safe for regime signals.
Responses are cached on disk.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import httpx
import pandas as pd

_CACHE = Path(".cache/fred")
_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"


def _parse(text: str) -> pd.Series | None:
    """Parse FRED CSV text into a date-indexed series; None if it isn't FRED CSV."""
    if text.lstrip().startswith("<"):
        return None  # an HTML page (e.g. FRED maintenance) served with HTTP 200
    try:
        frame = pd.read_csv(StringIO(text))
    except (pd.errors.ParserError, pd.errors.EmptyDataError):
        return None
    if frame.shape[1] < 2:
        return None
    index = pd.to_datetime(frame.iloc[:, 0], utc=True, errors="coerce")
    values = pd.to_numeric(frame.iloc[:, 1], errors="coerce")
    series = pd.Series(values.to_numpy(), index=index)
    return series[~series.index.isna()].dropna().sort_index()


def fred_series(series_id: str, *, force: bool = False) -> pd.Series:
    """Fetch a FRED series as a date-indexed ``pd.Series`` (cached).

    Only a response that parses as FRED CSV is cached, and an unparseable cache
    file is discarded and re-fetched, so a transient error page can't stick.
    """
    _CACHE.mkdir(parents=True, exist_ok=True)
    path = _CACHE / f"{series_id}.csv"
    if not force and path.exists():
        cached = _parse(path.read_text(encoding="utf-8"))
        if cached is not None:
            return cached
        path.unlink()
    resp = httpx.get(
        _URL.format(sid=series_id), timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}
    )
    resp.raise_for_status()
    series = _parse(resp.text)
    if series is None:
        raise ValueError(
            f"FRED returned a non-CSV response for {series_id} (site maintenance or "
            "an error page); nothing cached — retry later."
        )
    path.write_text(resp.text, encoding="utf-8")
    return series
