"""Walk-forward backtest (blueprint offline evaluation).

Strictly guards against look-ahead bias: at each step the signal is computed only
from bars *up to and including* day t, and the return it earns is day t+1's — the
signal never sees the return it is graded on. Position size uses the same
fractional-Kelly + policy cap as live trading, so the backtest evaluates the real
sizing logic, not a simplified proxy.

This measures whether the deterministic signal has edge before any capital (or the
LLM) is involved — the gate the blueprint's look-ahead audit is meant to enforce.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from arthaai.agents import asset_manager, indicators
from arthaai.config import get_settings
from arthaai.db import timescale


@dataclass
class BacktestResult:
    symbol: str
    bars: int
    trades: int
    total_return: float      # strategy cumulative return
    buy_hold_return: float
    sharpe: float            # annualised
    max_drawdown: float
    hit_rate: float          # fraction of days the sign was correct

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol, "bars": self.bars, "trades": self.trades,
            "total_return": round(self.total_return, 4),
            "buy_hold_return": round(self.buy_hold_return, 4),
            "sharpe": round(self.sharpe, 3),
            "max_drawdown": round(self.max_drawdown, 4),
            "hit_rate": round(self.hit_rate, 4),
        }


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float(((equity - peak) / peak).min())


def run_backtest(symbol: str, *, warmup: int = 60, limit: int = 500) -> BacktestResult:
    symbol = symbol.upper()
    df = timescale.load_ohlcv(symbol, limit=limit)
    if len(df) < warmup + 5:
        raise ValueError(f"not enough history for {symbol} (need > {warmup + 5} bars).")

    close = df["close"].reset_index(drop=True)
    fwd_ret = close.pct_change().shift(-1)  # day t earns day t+1's return
    s = get_settings()

    strat_rets, signs_correct, trades = [], 0, 0
    for t in range(warmup, len(close) - 1):
        window = close.iloc[: t + 1]                       # only past data (no leakage)
        _, score = indicators.trend_signal(window)
        stats = indicators.annualised_stats(window)
        w, r = indicators.win_loss_ratio(window)
        alloc = asset_manager.size(
            {"mu": stats["mu"], "variance": stats["variance"], "win_prob": w, "win_loss_ratio": r}
        )
        direction = 1 if score > 0.15 else -1 if score < -0.15 else 0
        frac = alloc.final_fraction * direction            # signed exposure, policy-capped
        rt = fwd_ret.iloc[t]
        if pd.isna(rt):
            continue
        strat_rets.append(frac * rt)
        if direction != 0:
            trades += 1
            if np.sign(rt) == np.sign(direction):
                signs_correct += 1

    sr = pd.Series(strat_rets)
    equity = (1 + sr).cumprod()
    ann = np.sqrt(252)
    sharpe = float(sr.mean() / sr.std() * ann) if sr.std() > 0 else 0.0
    total = float(equity.iloc[-1] - 1) if len(equity) else 0.0
    bh = float(close.iloc[-1] / close.iloc[warmup] - 1)
    hit = signs_correct / trades if trades else 0.0

    return BacktestResult(
        symbol=symbol, bars=len(df), trades=trades, total_return=total,
        buy_hold_return=bh, sharpe=sharpe, max_drawdown=_max_drawdown(equity) if len(equity) else 0.0,
        hit_rate=hit,
    )
