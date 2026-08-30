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
from arthaai.db import timescale


def oos_slice(n_total: int, oos_pct: float = 0.30) -> tuple[int, int]:
    """Return (in_start, in_end) indices for an out-of-sample split.

    The in-sample period is bars [0, in_end), and the out-of-sample period is
    bars [in_end, n_total). Minimum OOS is one bar if n_total is tiny.

    Args:
        n_total: total number of bars available.
        oos_pct: fraction of total bars to reserve for OOS (default 0.30).

    Returns:
        (in_end, n_total) where in_end is the first OOS bar index.
    """
    if n_total <= 0:
        return 0, 0
    n_oos = max(1, int(round(n_total * oos_pct)))
    in_end = max(0, n_total - n_oos)
    return in_end, n_total


@dataclass
class BacktestResult:
    symbol: str
    bars: int
    trades: int
    total_return: float      # strategy cumulative return (Kelly-sized, policy-capped)
    buy_hold_return: float
    sharpe: float            # annualised
    max_drawdown: float
    hit_rate: float          # fraction of days the sign was correct
    long_short_return: float  # 100% exposure × direction — raw directional edge
    long_only_return: float   # 100% long when bullish, flat otherwise (long-only filter)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol, "bars": self.bars, "trades": self.trades,
            "total_return": round(self.total_return, 4),
            "buy_hold_return": round(self.buy_hold_return, 4),
            "sharpe": round(self.sharpe, 3),
            "max_drawdown": round(self.max_drawdown, 4),
            "hit_rate": round(self.hit_rate, 4),
            "long_short_return": round(self.long_short_return, 4),
            "long_only_return": round(self.long_only_return, 4),
        }


def _max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float(((equity - peak) / peak).min())


def run_backtest(
    symbol: str, *, warmup: int = 60, limit: int = 500,
    signal: str = "trend", adx_threshold: float = 0.0,
    data_slice: slice | None = None,
) -> BacktestResult:
    """Walk-forward backtest with look-ahead-bias guards.

    Args:
        symbol: Ticker symbol.
        warmup: minimum bars before first signal.
        limit: max bars to load.
        signal: 'trend' or 'breakout'.
        adx_threshold: ADX regime threshold for breakout signal.
        data_slice: optional slice into the loaded OHLCV (e.g. for OOS runs).

    Returns:
        BacktestResult with all metrics.
    """
    symbol = symbol.upper()
    df = timescale.load_ohlcv(symbol, limit=limit)
    if data_slice is not None:
        df = df[data_slice]
    if len(df) < warmup + 5:
        raise ValueError(f"not enough history for {symbol} (need > {warmup + 5} bars).")

    close = df["close"].reset_index(drop=True)
    high = df["high"].reset_index(drop=True)
    low = df["low"].reset_index(drop=True)
    fwd_ret = close.pct_change().shift(-1)  # day t earns day t+1's return

    # For the breakout signal, precompute the full position series once (O(n),
    # look-ahead-safe by construction); per-bar re-simulation would be O(n²).
    # 55/20 = slow Turtle system: catches bigger trends, the configuration where
    # Donchian shows real edge on trending assets (vs the fast 20/10 which bleeds).
    breakout_dirs = (
        indicators.breakout_positions(
            high, low, close, entry_window=55, exit_window=20, adx_threshold=adx_threshold
        )
        if signal == "breakout" else None
    )

    strat_rets, dir_rets, lo_rets, signs_correct, trades = [], [], [], 0, 0
    # Incremental signal-conditioned Kelly stats: at bar t we resolve the prior
    # bar's (direction, realized return) pair — fully known by bar t — and
    # accumulate the hit rate / payoff the Asset Manager sizes on. This is
    # look-ahead-safe (never uses a return before it is realized) and costs no
    # extra signal evaluations, since the per-bar direction is already computed.
    sig_wins = sig_losses = 0
    sig_win_sum = sig_loss_sum = 0.0
    prev_dir = 0
    for t in range(warmup, len(close) - 1):
        # Resolve the previous bar's signal against its realized return (known now).
        if t > warmup and prev_dir != 0:
            prev_ret = fwd_ret.iloc[t - 1]
            if not pd.isna(prev_ret) and prev_ret != 0:
                if np.sign(prev_ret) == prev_dir:
                    sig_wins += 1
                    sig_win_sum += abs(prev_ret)
                else:
                    sig_losses += 1
                    sig_loss_sum += abs(prev_ret)

        c_win = close.iloc[: t + 1]                       # only past data (no leakage)
        if signal == "breakout":
            direction = breakout_dirs[t]                   # held position at t
            label = "bullish" if direction == 1 else "bearish" if direction == -1 else "neutral"
        else:
            label, _ = indicators.trend_signal(c_win)
            direction = 1 if label == "bullish" else -1 if label == "bearish" else 0
        prev_dir = direction
        stats = indicators.annualised_stats(c_win)
        # Neutral prior until enough signal-conditioned samples exist; discrete
        # Kelly of (0.5, 1.0) is 0 -> flat, so early bars take no position.
        if sig_wins + sig_losses >= 10:
            w, r = indicators.wr_from_tallies(sig_wins, sig_losses, sig_win_sum, sig_loss_sum)
        else:
            w, r = 0.5, 1.0
        alloc = asset_manager.size(
            {"mu": stats["mu"], "variance": stats["variance"], "win_prob": w, "win_loss_ratio": r}
        )
        frac = alloc.final_fraction * direction            # signed exposure, policy-capped
        rt = fwd_ret.iloc[t]
        if pd.isna(rt):
            continue
        strat_rets.append(frac * rt)
        dir_rets.append(direction * rt)                    # 100% exposure long/short
        lo_rets.append(max(0, direction) * rt)             # long-only, flat when not bullish
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
    ls = float((1 + pd.Series(dir_rets)).prod() - 1) if dir_rets else 0.0
    lo = float((1 + pd.Series(lo_rets)).prod() - 1) if lo_rets else 0.0

    return BacktestResult(
        symbol=symbol, bars=len(df), trades=trades, total_return=total,
        buy_hold_return=bh, sharpe=sharpe, max_drawdown=_max_drawdown(equity) if len(equity) else 0.0,
        hit_rate=hit, long_short_return=ls, long_only_return=lo,
    )
