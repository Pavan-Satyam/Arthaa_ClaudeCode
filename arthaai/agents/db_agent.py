"""DB_Agent — the quantitative anchor.

Pulls OHLCV from TimescaleDB and derives deterministic technical indicators. No
LLM math. Operates under its SPIFFE identity and least-privilege tool scope.
"""

from __future__ import annotations

from arthaai.agents import indicators
from arthaai.db import timescale
from arthaai.security import AgentIdentity, authorize_tool

IDENTITY = AgentIdentity("db_agent", "spiffe://arthaai/agent/db_agent")


def run(symbol: str) -> dict:
    authorize_tool(IDENTITY, "load_ohlcv")
    df = timescale.load_ohlcv(symbol)
    if df.empty:
        return {"available": False, "reason": "no OHLCV in TimescaleDB — run ingest first."}
    close = df["close"]
    label, score = indicators.trend_signal(close)
    return {
        "available": True,
        "bars": int(len(df)),
        "last_close": round(float(close.iloc[-1]), 4),
        "sma20": indicators.sma(close, 20),
        "sma50": indicators.sma(close, 50),
        "rsi14": indicators.rsi(close),
        "trend": label,
        "trend_score": score,
    }
