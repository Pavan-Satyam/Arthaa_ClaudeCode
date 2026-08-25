"""DB_Agent — the quantitative anchor.

Pulls OHLCV from TimescaleDB and derives deterministic technical indicators. No
LLM math. Operates under its SPIFFE identity and least-privilege tool scope.

Signal selection: ADX regime decides which signal class is active. In trending
markets (ADX≥25) the Donchian breakout system is used — it has real risk-
adjusted edge on trending assets (GLD Sharpe 1.28, SLV 1.29). In choppy or
weak-trend markets the multi-timeframe trend filter is used, as breakout bleeds
in sideways conditions.
"""

from __future__ import annotations

from arthaai.agents import indicators
from arthaai.agents.indicators import BREAKOUT_ADX_THRESHOLD, BREAKOUT_ENTRY_WINDOW, BREAKOUT_EXIT_WINDOW
from arthaai.db import timescale
from arthaai.security import AgentIdentity, authorize_tool

IDENTITY = AgentIdentity("db_agent", "spiffe://arthaai/agent/db_agent")


def run(symbol: str) -> dict:
    authorize_tool(IDENTITY, "load_ohlcv")
    df = timescale.load_ohlcv(symbol)
    if df.empty:
        return {"available": False, "reason": "no OHLCV in TimescaleDB — run ingest first."}
    close = df["close"]
    high = df["high"]
    low = df["low"]
    adx_val = indicators.adx(high, low, close)
    regime = _regime_label(adx_val)

    # Signal selector: trending markets use breakout, everything else uses trend.
    use_breakout = adx_val is not None and adx_val >= BREAKOUT_ADX_THRESHOLD
    if use_breakout:
        label, score = indicators.breakout_signal(
            high, low, close, entry_window=BREAKOUT_ENTRY_WINDOW, exit_window=BREAKOUT_EXIT_WINDOW,
        )
        signal_class = "breakout"
    else:
        label, score = indicators.trend_signal(close)
        signal_class = "trend"

    return {
        "available": True,
        "bars": int(len(df)),
        "last_close": round(float(close.iloc[-1]), 4),
        "sma20": indicators.sma(close, 20),
        "sma50": indicators.sma(close, 50),
        "rsi14": indicators.rsi(close),
        "adx14": round(adx_val, 1) if adx_val is not None else None,
        "regime": regime,
        "signal_class": signal_class,
        "trend": label,
        "trend_score": score,
    }


def _regime_label(adx_val: float | None) -> str:
    """Translate ADX into a human-readable trend-strength regime."""
    if adx_val is None:
        return "unknown"
    if adx_val >= 25:
        return "trending"
    if adx_val >= 20:
        return "weak-trend"
    return "choppy"
