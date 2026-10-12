"""SEC EDGAR point-in-time fundamentals for a value/quality axis (free, keyless).

Uses SEC's public XBRL APIs (no API key; a descriptive User-Agent is required).
A fact becomes available on its **filing date** (``filed``), so every series here
is point-in-time: a value at date *t* uses only facts filed on or before *t*.
That is the property that makes fundamentals safe to feed a walk-forward backtest
without look-ahead.

Only companies have fundamentals, so this axis applies to the **equity subset**
of a universe (ETFs are excluded by the caller).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from arthaai.factors.base import zscore

_HEADERS = {"User-Agent": "ArthaAI research contact@example.com"}
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/{tax}/{tag}.json"
_CACHE = Path(".cache/sec")

_METRIC_TAGS: dict[str, tuple[str, str]] = {
    "equity": ("us-gaap", "StockholdersEquity"),
    "income": ("us-gaap", "NetIncomeLoss"),
    "shares": ("dei", "EntityCommonStockSharesOutstanding"),
}


def ticker_to_cik(*, force: bool = False) -> dict[str, str]:
    """Return ``{TICKER: zero-padded CIK}`` from SEC's public mapping."""
    _CACHE.mkdir(parents=True, exist_ok=True)
    path = _CACHE / "company_tickers.json"
    if force or not path.exists():
        resp = httpx.get(_TICKERS_URL, headers=_HEADERS, timeout=30.0)
        resp.raise_for_status()
        path.write_text(resp.text, encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(v["ticker"]).upper(): str(v["cik_str"]).zfill(10) for v in data.values()}


def fetch_concept(
    cik: str, tag: str, taxonomy: str = "us-gaap", *, force: bool = False
) -> pd.DataFrame:
    """Fetch one XBRL concept as a ``filed, end, val, form`` frame (cached)."""
    _CACHE.mkdir(parents=True, exist_ok=True)
    path = _CACHE / f"{cik}_{taxonomy}_{tag}.json"
    if force or not path.exists():
        resp = httpx.get(
            _CONCEPT_URL.format(cik=cik, tax=taxonomy, tag=tag),
            headers=_HEADERS,
            timeout=30.0,
        )
        path.write_text(resp.text if resp.status_code == 200 else "{}", encoding="utf-8")
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for unit_obs in raw.get("units", {}).values():
        for obs in unit_obs:
            if "filed" in obs and "val" in obs:
                rows.append(
                    {
                        "end": obs.get("end"),
                        "val": obs.get("val"),
                        "filed": obs.get("filed"),
                        "form": obs.get("form"),
                    }
                )
    if not rows:
        return pd.DataFrame(columns=["end", "val", "filed", "form"])
    frame = pd.DataFrame(rows)
    frame["filed"] = pd.to_datetime(frame["filed"], utc=True, errors="coerce").dt.normalize()
    frame["end"] = pd.to_datetime(frame["end"], utc=True, errors="coerce").dt.normalize()
    return frame.dropna(subset=["filed", "val"]).sort_values("filed").reset_index(drop=True)


def pit_latest(obs: pd.DataFrame, dates, *, prefer_annual: bool = False) -> pd.Series:
    """Latest fact value available at each date (filed <= date).

    ``prefer_annual`` restricts to 10-K filings when any exist, so income-statement
    flows are a yearly figure rather than a mixed quarterly/annual series.
    """
    index = pd.DatetimeIndex(pd.to_datetime(dates, utc=True)).normalize()
    if obs is None or obs.empty:
        return pd.Series(np.nan, index=index)
    o = obs
    if prefer_annual:
        annual = o[o["form"] == "10-K"]
        if not annual.empty:
            o = annual
    o = o.dropna(subset=["filed", "val"]).sort_values("filed").drop_duplicates("filed", keep="last")
    left = pd.DataFrame({"date": index}).sort_values("date")
    merged = pd.merge_asof(
        left,
        o[["filed", "val"]].rename(columns={"filed": "date"}),
        on="date",
        direction="backward",
    )
    return pd.Series(merged["val"].to_numpy(), index=index)


def value_panel(
    symbols: list[str],
    close: pd.DataFrame,
    *,
    cik_map: dict[str, str] | None = None,
    concept_fetcher: Callable[[str, str, str], pd.DataFrame] | None = None,
) -> dict[str, pd.DataFrame]:
    """Build wide ``book_to_price``, ``earnings_yield`` and ``roe`` frames (PIT)."""
    cik_map = cik_map if cik_map is not None else ticker_to_cik()
    fetcher = concept_fetcher or fetch_concept
    dates = close.index
    bp: dict[str, pd.Series] = {}
    ep: dict[str, pd.Series] = {}
    roe: dict[str, pd.Series] = {}
    for sym in symbols:
        upper = str(sym).upper()
        cik = cik_map.get(upper)
        if not cik or upper not in close.columns:
            continue
        equity_tax, equity_tag = _METRIC_TAGS["equity"]
        income_tax, income_tag = _METRIC_TAGS["income"]
        shares_tax, shares_tag = _METRIC_TAGS["shares"]
        equity = pit_latest(fetcher(cik, equity_tag, equity_tax), dates)
        income = pit_latest(fetcher(cik, income_tag, income_tax), dates, prefer_annual=True)
        shares = pit_latest(fetcher(cik, shares_tag, shares_tax), dates)
        market_cap = shares * close[upper]
        bp[upper] = equity / market_cap
        ep[upper] = income / market_cap
        roe[upper] = income / equity.replace(0.0, np.nan)
    return {
        "book_to_price": pd.DataFrame(bp),
        "earnings_yield": pd.DataFrame(ep),
        "roe": pd.DataFrame(roe),
    }


def value_signal_map(
    symbols: list[str],
    *,
    top_quantile: float = 0.30,
    limit: int = 520,
    cik_map: dict[str, str] | None = None,
    concept_fetcher: Callable[[str, str, str], pd.DataFrame] | None = None,
) -> dict[str, pd.Series]:
    """Cross-sectional value/quality signal: long the top ``top_quantile`` each date.

    Each metric is cross-sectionally z-scored, the three are summed, and the top
    fraction of the universe is held long (flat otherwise). Causal: PIT metrics
    only; the z-score uses the same date's cross-section.
    """
    from arthaai.factors.panel import build_panel_from_symbols

    panel = build_panel_from_symbols(list(symbols), limit=limit)
    close = panel.get("close")
    if close is None or close.empty:
        return {}
    metrics = value_panel(
        list(close.columns), close, cik_map=cik_map, concept_fetcher=concept_fetcher
    )
    standardized = [zscore(m) for m in metrics.values() if m is not None and not m.empty]
    if not standardized:
        return {}
    index = standardized[0].index
    columns = standardized[0].columns
    for frame in standardized[1:]:
        index = index.union(frame.index)
        columns = columns.union(frame.columns)
    composite = sum(frame.reindex(index=index, columns=columns) for frame in standardized)

    ranks = composite.rank(axis=1, ascending=False, method="first")
    counts = composite.notna().sum(axis=1)
    keep = np.ceil(counts * top_quantile).clip(lower=1)
    selected = ranks.le(keep, axis=0).astype(float)
    wide = selected.where(composite.notna())
    return {str(sym): wide[sym].dropna() for sym in wide.columns}
