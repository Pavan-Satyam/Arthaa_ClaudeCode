"""Deterministic technical indicators & return statistics.

This is the quant layer the blueprint insists on: all numbers are computed here,
never by the LLM. Pure functions over an OHLCV frame.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(close: pd.Series, window: int) -> float | None:
    if len(close) < window:
        return None
    return float(close.tail(window).mean())


def rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    delta = close.diff().dropna()
    gain = delta.clip(lower=0).rolling(period).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).rolling(period).mean().iloc[-1]
    if pd.isna(gain) or pd.isna(loss):
        return None
    if loss == 0:  # no downside in the window -> maximally overbought (or flat)
        return 100.0 if gain > 0 else 50.0
    rs = gain / loss
    return float(100 - 100 / (1 + rs))


def annualised_stats(close: pd.Series) -> dict[str, float]:
    """Annualised mean return (mu), variance (sigma^2), and volatility (sigma)."""
    rets = np.log(close / close.shift(1)).dropna()
    if len(rets) < 2:
        return {"mu": 0.0, "variance": 0.0, "sigma": 0.0}
    mu = float(rets.mean() * 252)
    var = float(rets.var(ddof=1) * 252)
    return {"mu": mu, "variance": var, "sigma": var**0.5}


def win_loss_ratio(close: pd.Series) -> tuple[float, float]:
    """Return (win_prob W, win/loss ratio R) from daily returns — feeds discrete Kelly."""
    rets = close.pct_change().dropna()
    wins, losses = rets[rets > 0], rets[rets < 0]
    if len(rets) == 0 or len(losses) == 0 or len(wins) == 0:
        return 0.5, 1.0
    w = float(len(wins) / len(rets))
    r = float(wins.mean() / abs(losses.mean()))
    return w, r


def trend_signal(close: pd.Series) -> tuple[str, float]:
    """Coarse directional read from SMA cross + RSI. Returns (label, score -1..1)."""
    s20, s50 = sma(close, 20), sma(close, 50)
    r = rsi(close)
    score = 0.0
    if s20 and s50:
        score += 0.5 if s20 > s50 else -0.5
    if r is not None:
        if r > 70:
            score -= 0.25
        elif r < 30:
            score += 0.25
        else:
            score += (r - 50) / 100
    score = max(-1.0, min(1.0, score))
    label = "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral"
    return label, round(score, 3)
