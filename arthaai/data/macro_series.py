"""Keyless macro series via FRED's public CSV endpoint.

No API key required. The daily treasury series used here (yields and spreads) are
market data and non-revised, so they are point-in-time safe for regime signals.
Responses are cached on disk.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pandas as pd

_CACHE = Path(".cache/fred")
_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"


def fred_series(series_id: str, *, force: bool = False) -> pd.Series:
    """Fetch a FRED series as a date-indexed ``pd.Series`` (cached)."""
    _CACHE.mkdir(parents=True, exist_ok=True)
    path = _CACHE / f"{series_id}.csv"
    if force or not path.exists():
        resp = httpx.get(
            _URL.format(sid=series_id), timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}
        )
        resp.raise_for_status()
        path.write_text(resp.text, encoding="utf-8")
    frame = pd.read_csv(path)
    if frame.shape[1] < 2:
        return pd.Series(dtype=float)
    index = pd.to_datetime(frame.iloc[:, 0], utc=True, errors="coerce")
    values = pd.to_numeric(frame.iloc[:, 1], errors="coerce")
    series = pd.Series(values.to_numpy(), index=index)
    series = series[~series.index.isna()].dropna().sort_index()
    return series
