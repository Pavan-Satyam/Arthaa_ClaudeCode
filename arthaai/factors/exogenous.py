"""Exogenous E3 signal maps (pre-registered free axes).

Each function takes an optional injected exogenous series so it is unit-testable
without network or a database, mirroring ``macro_regime.macro_regime``. In
production the series comes from the corresponding ``arthaai.data`` adapter, which
has already mapped it to its point-in-time *effective* (release) date.

Axes (all free, PIT, enterprise-licensable):

- ``cftc``     — CFTC COT speculator positioning, commodity ETFs (GLD/SLV/USO).
- ``eia``      — EIA weekly crude inventories, energy names (USO/XOM).
- ``insider``  — SEC Form 4 net insider buying, equity subset (cross-sectional).
- ``vix_regime`` — Cboe VIX/VIX3M term structure, market-wide regime gate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from arthaai.data.cftc import COMMODITY_COT_CONTRACTS, positioning_zscore
from arthaai.data.pit import asof_align

ENERGY_UNIVERSE = ("USO", "XOM")
VIX_INVERSION_THRESHOLD = 1.0


def _panel_close(symbols: list[str], limit: int) -> pd.DataFrame:
    from arthaai.factors.panel import build_panel_from_symbols

    panel = build_panel_from_symbols(list(symbols), limit=limit)
    close = panel.get("close")
    return close if close is not None else pd.DataFrame()


def _effective_series_from_frame(frame: pd.DataFrame, value_field: str = "value") -> pd.Series:
    """Build an effective-date-indexed series from an EIA-style frame."""
    if frame is None or frame.empty or "effective_ts" not in frame.columns:
        return pd.Series(dtype="float64")
    index = pd.DatetimeIndex(pd.to_datetime(frame["effective_ts"], utc=True, errors="coerce"))
    values = pd.to_numeric(frame[value_field], errors="coerce")
    series = pd.Series(values.to_numpy(), index=index).dropna()
    series.index = series.index.normalize()
    return series[~series.index.isna()].sort_index()


def _events_to_sessions(series: pd.Series, sessions: pd.DatetimeIndex) -> pd.Series:
    """Place each filing event on the first session on/after its effective date.

    Non-event sessions are NaN (so availability is ``notna``); summing the *events*
    avoids the over-count you get by summing a forward-filled level.
    """
    out = pd.Series(np.nan, index=sessions, dtype="float64")
    if series is None or series.empty or len(sessions) == 0:
        return out
    s = series.dropna().sort_index()
    if s.empty:
        return out
    pos = sessions.searchsorted(s.index, side="left")
    valid = pos < len(sessions)
    if not valid.any():
        return out
    pos_valid = pos[valid]
    values = s.to_numpy()[valid]
    totals = np.bincount(pos_valid, weights=values, minlength=len(sessions))
    hit = np.zeros(len(sessions), dtype=bool)
    hit[pos_valid] = True
    return pd.Series(np.where(hit, totals, np.nan), index=sessions, dtype="float64")


def cftc_signal_map(
    symbols: list[str],
    *,
    limit: int = 520,
    cot: dict[str, pd.Series] | None = None,
    z_window: int = 156,
) -> dict[str, pd.Series]:
    """Long a commodity ETF when speculators are net-long vs their own history.

    Applies only to the symbols with a mapped CFTC contract (GLD/SLV/USO); other
    symbols simply have no signal.
    """
    close = _panel_close(symbols, limit)
    if close.empty:
        return {}
    out: dict[str, pd.Series] = {}
    for sym in close.columns:
        market = COMMODITY_COT_CONTRACTS.get(str(sym).upper())
        if market is None:
            continue
        if cot is not None and sym in cot:
            series = cot[sym]
        elif cot is None:
            from arthaai.data.cftc import cot_effective_series

            series = cot_effective_series(market)
        else:
            continue
        if series is None or series.empty:
            continue
        z = positioning_zscore(series, window=z_window)
        aligned = asof_align(z, close.index)
        signal = (aligned > 0).astype(float).where(aligned.notna())
        out[str(sym)] = signal.dropna()
    return out


def eia_signal_map(
    symbols: list[str],
    *,
    limit: int = 520,
    inventory: pd.Series | None = None,
    change_window: int = 4,
) -> dict[str, pd.Series]:
    """Long energy names when crude inventories are drawing (WoW decline).

    ``inventory`` is an effective-date-indexed crude-stocks series; a trailing
    ``change_window``-week change < 0 (a draw) is bullish for USO/XOM.
    """
    close = _panel_close(symbols, limit)
    if close.empty:
        return {}
    if inventory is None:
        from arthaai.data.alternative import AlternativeAssetFetcher

        fetcher = AlternativeAssetFetcher()
        inventory = _effective_series_from_frame(fetcher.get_crude_oil_inventory())
    if inventory is None or inventory.empty:
        return {}
    change = inventory.diff(change_window)
    bullish = (change < 0).astype(float).where(change.notna())
    out: dict[str, pd.Series] = {}
    for sym in close.columns:
        if str(sym).upper() not in ENERGY_UNIVERSE:
            continue
        out[str(sym)] = asof_align(bullish, close.index).dropna()
    return out


def insider_signal_map(
    symbols: list[str],
    *,
    limit: int = 520,
    insider: dict[str, pd.Series] | None = None,
    lookback: int = 63,
    top_quantile: float = 0.30,
) -> dict[str, pd.Series]:
    """Cross-sectional insider-buying signal: long the top ``top_quantile``.

    ``insider`` maps symbol -> effective-date-indexed net insider shares; the
    trailing ``lookback`` window sum is cross-sectionally ranked each date, and the
    top fraction is held long. Symbols without insider data are excluded (ETFs).
    """
    close = _panel_close(symbols, limit)
    if close.empty:
        return {}
    if insider is None:
        from arthaai.data.form4 import insider_effective_series
        from arthaai.data.fundamentals import SECDataProcessor

        processor = SECDataProcessor()  # one client reused across the universe
        insider = {}
        for sym in close.columns:
            try:
                insider[str(sym)] = insider_effective_series(str(sym), processor=processor)
            except Exception:  # noqa: BLE001, S112 - a missing filing set must not kill the axis
                continue
    if not insider:
        return {}

    sessions = pd.DatetimeIndex(close.index)
    events = {
        str(sym): _events_to_sessions(series, sessions)
        for sym, series in insider.items()
        if series is not None and not series.empty
    }
    if not events:
        return {}
    wide = pd.DataFrame(events, index=sessions)
    # Sum filing *events* in the trailing window (0 where no event), not a filled
    # level, so a single filing is counted once rather than once per remaining day.
    flow = wide.fillna(0.0).rolling(lookback, min_periods=1).sum()
    # Only rank symbols that already have at least one filing on/before the date.
    available = wide.notna().cummax()
    ranks = flow.rank(axis=1, ascending=False, method="first")
    counts = available.sum(axis=1)
    keep = np.ceil(counts * top_quantile).clip(lower=1)
    selected = ranks.le(keep, axis=0).astype(float).where(available)
    return {sym: selected[sym].dropna() for sym in selected.columns}


def vix_regime_signal_map(
    symbols: list[str],
    *,
    limit: int = 520,
    ratio: pd.Series | None = None,
    inversion_threshold: float = VIX_INVERSION_THRESHOLD,
) -> dict[str, pd.Series]:
    """Market-wide gate: long every symbol when the VIX term structure is calm.

    Calm = VIX/VIX3M < ``inversion_threshold`` (contango); an inverted curve
    (near-term stress) is risk-off and flat.
    """
    close = _panel_close(symbols, limit)
    if close.empty:
        return {}
    if ratio is None:
        from arthaai.data.vix import vix_term_structure

        ratio = vix_term_structure()
    if ratio is None or ratio.empty:
        return {}
    aligned = asof_align(ratio, close.index)
    calm = (aligned < inversion_threshold).astype(float).where(aligned.notna())
    return {str(sym): calm.dropna() for sym in close.columns}
