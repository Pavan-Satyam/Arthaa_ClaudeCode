"""Corporate-action capture (splits/dividends) for adjustment auditability.

Records splits and dividends from yfinance so a backtest's price basis is
reproducible and auditable, and provides a pure consistency scan that flags
overnight price gaps not explained by a corporate action.

``reference_price`` (the prior close the adjustment applies against) is left
``None`` here and filled from stored OHLCV by ``timescale.set_action_reference_prices``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    ex_date: str  # ISO date (YYYY-MM-DD)
    action_type: str  # 'split' | 'dividend'
    ratio: float | None
    amount: float | None
    reference_price: float | None
    source: str


def _as_date(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _default_ticker_factory(symbol: str) -> Any:
    import yfinance as yf

    return yf.Ticker(symbol)


def fetch_corporate_actions(
    symbol: str, *, ticker_factory: Callable[[str], Any] | None = None
) -> list[CorporateAction]:
    """Fetch splits and dividends for ``symbol`` via yfinance (injectable for tests)."""
    factory = ticker_factory or _default_ticker_factory
    ticker = factory(symbol)
    upper = symbol.upper()
    actions: list[CorporateAction] = []

    splits = getattr(ticker, "splits", None)
    if splits is not None and len(splits):
        for ts, ratio in splits.items():
            actions.append(
                CorporateAction(upper, _as_date(ts), "split", float(ratio), None, None, "yfinance")
            )

    dividends = getattr(ticker, "dividends", None)
    if dividends is not None and len(dividends):
        for ts, amount in dividends.items():
            actions.append(
                CorporateAction(upper, _as_date(ts), "dividend", None, float(amount), None, "yfinance")
            )

    actions.sort(key=lambda action: (action.ex_date, action.action_type))
    return actions


def _action_date(action: Any) -> pd.Timestamp:
    raw = action["ex_date"] if isinstance(action, dict) else action.ex_date
    stamp = pd.Timestamp(raw)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def scan_unexplained_gaps(
    bars: pd.DataFrame,
    actions: list[Any],
    *,
    threshold: float = 0.15,
    window_days: int = 5,
) -> list[dict]:
    """Flag overnight gaps larger than ``threshold`` not explained by a corporate action.

    ``bars`` is an OHLCV frame with ``ts`` and ``close``. A gap on date *t* is
    "explained" when a corporate action ex-date falls within ``window_days`` of it.
    Pure function: no I/O, no clock.
    """
    if bars is None or len(bars) < 2 or "close" not in getattr(bars, "columns", []):
        return []
    frame = bars.sort_values("ts") if "ts" in bars.columns else bars
    close = pd.to_numeric(frame["close"], errors="coerce").reset_index(drop=True)
    ts = (
        pd.to_datetime(frame["ts"], utc=True, errors="coerce").reset_index(drop=True)
        if "ts" in frame.columns
        else None
    )
    action_dates = [_action_date(action) for action in actions] if actions else []

    findings: list[dict] = []
    for index in range(1, len(close)):
        previous, current = close.iloc[index - 1], close.iloc[index]
        if pd.isna(previous) or pd.isna(current) or not previous:
            continue
        change = current / previous - 1.0
        if abs(change) < threshold:
            continue
        date = ts.iloc[index] if ts is not None else pd.NaT
        explained = False
        if not pd.isna(date):
            explained = any(abs((action_date - date).days) <= window_days for action_date in action_dates)
        findings.append(
            {
                "date": "" if pd.isna(date) else date.strftime("%Y-%m-%d"),
                "change": float(change),
                "explained": explained,
            }
        )
    return findings


def unexplained_gaps(findings: list[dict]) -> list[dict]:
    """Filter a ``scan_unexplained_gaps`` result to the unexplained anomalies."""
    return [finding for finding in findings if not finding["explained"]]
