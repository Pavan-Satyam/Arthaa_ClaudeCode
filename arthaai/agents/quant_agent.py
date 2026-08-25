"""Quant Agent — studies mathematical financial models.

Computes annualised return/variance/volatility and the signal-conditioned
discrete-Kelly inputs (win probability W, win/loss ratio R) that the Asset
Manager consumes. W and R are derived from the active signal's historical hit
rate and payoff, not the asset's unconditional daily returns, so they reflect
the signal's actual edge.

Signal selection mirrors db_agent: ADX≥25 uses breakout Kelly stats, else trend.
"""

from __future__ import annotations

from arthaai.agents import indicators
from arthaai.agents.indicators import BREAKOUT_ADX_THRESHOLD
from arthaai.db import timescale
from arthaai.security import AgentIdentity, authorize_tool

IDENTITY = AgentIdentity("quant_agent", "spiffe://arthaai/agent/quant_agent")


def run(symbol: str) -> dict:
    authorize_tool(IDENTITY, "compute_stats")
    df = timescale.load_ohlcv(symbol)
    if df.empty:
        return {"available": False, "reason": "no OHLCV in TimescaleDB — run ingest first."}
    close = df["close"]
    high = df["high"]
    low = df["low"]
    stats = indicators.annualised_stats(close)

    # Match db_agent's signal selector: trending → breakout, else trend.
    adx_val = indicators.adx(high, low, close)
    use_breakout = adx_val is not None and adx_val >= BREAKOUT_ADX_THRESHOLD
    if use_breakout:
        w, r = indicators.signal_kelly_stats(close, high=high, low=low, signal_class="breakout")
        signal_class = "breakout"
    else:
        w, r = indicators.signal_kelly_stats(close, signal_class="trend")
        signal_class = "trend"

    return {
        "available": True,
        "mu": round(stats["mu"], 4),
        "variance": round(stats["variance"], 6),
        "sigma": round(stats["sigma"], 4),
        "win_prob": round(w, 4),
        "win_loss_ratio": round(r, 4),
        "signal_class": signal_class,
    }
