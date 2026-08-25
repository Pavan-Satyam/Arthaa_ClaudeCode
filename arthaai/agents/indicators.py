"""Deterministic technical indicators & return statistics.

This is the quant layer the blueprint insists on: all numbers are computed here,
never by the LLM. Pure functions over an OHLCV frame.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd


def sma(close: pd.Series, window: int) -> float | None:
    if len(close) < window:
        return None
    return float(close.tail(window).mean())


def _wilder_rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (RMA / running moving average): alpha = 1/period.

    Equivalent to the exponential moving average with alpha=1/period; this is
    the standard RSI smoothing (the original Wilder definition), not a plain
    rolling mean.
    """
    alpha = 1.0 / period
    return series.ewm(alpha=alpha, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    delta = close.diff().dropna()
    gain = delta.clip(lower=0)
    loss = (-delta.clip(upper=0))
    avg_gain = _wilder_rma(gain, period).iloc[-1]
    avg_loss = _wilder_rma(loss, period).iloc[-1]
    if pd.isna(avg_gain) or pd.isna(avg_loss):
        return None
    if avg_loss == 0:  # no downside in the window -> maximally overbought (or flat)
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return float(100 - 100 / (1 + rs))


def roc(close: pd.Series, window: int = 20) -> float | None:
    """Rate of change over `window` bars (fractional). Momentum confirmation."""
    if len(close) < window + 1:
        return None
    prev = close.iloc[-window - 1]
    if prev == 0:
        return None
    return float((close.iloc[-1] - prev) / prev)


def _adx_series(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> np.ndarray:
    """Full per-bar ADX series (Wilder). Internal helper for the regime gate."""
    h = high.to_numpy(dtype=float)
    l = low.to_numpy(dtype=float)
    c = close.to_numpy(dtype=float)
    n = len(c)
    if n < period * 2:
        return np.zeros(n)

    up = np.diff(h)
    down = -np.diff(l)
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    tr = np.maximum.reduce([
        h[1:] - l[1:],
        np.abs(h[1:] - c[:-1]),
        np.abs(l[1:] - c[:-1]),
    ])

    atr = _wilder_rma(pd.Series(tr), period).to_numpy()
    safe_atr = np.where(atr == 0, 1, atr)
    plus_di = 100 * _wilder_rma(pd.Series(plus_dm), period).to_numpy() / safe_atr
    minus_di = 100 * _wilder_rma(pd.Series(minus_dm), period).to_numpy() / safe_atr

    di_sum = plus_di + minus_di
    dx = 100 * np.abs(plus_di - minus_di) / np.where(di_sum == 0, 1, di_sum)
    adx_arr = _wilder_rma(pd.Series(dx), period).to_numpy()

    # The DX series is shorter by (period-1) warmup bars vs the price series.
    out = np.zeros(n)
    offset = n - len(adx_arr)
    out[offset:] = np.where(np.isnan(adx_arr), 0, adx_arr)
    return out


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float | None:
    """Wilder's Average Directional Index — trend *strength* (not direction).

    ADX > 25 is the canonical "trending" boundary; below 20 is chop/noise.
    Unlike a fixed ER threshold, this boundary is asset-agnostic because ADX
    normalises directional movement by true range, so it reads comparably
    across a low-vol bond ETF and a high-vol commodity.
    """
    if len(close) < period * 2:
        return None
    series = _adx_series(high, low, close, period)
    val = series[-1]
    return float(val) if val > 0 else None


def annualised_stats(close: pd.Series) -> dict[str, float]:
    """Annualised mean return (mu), variance (sigma^2), and volatility (sigma)."""
    rets = np.log(close / close.shift(1)).dropna()
    if len(rets) < 2:
        return {"mu": 0.0, "variance": 0.0, "sigma": 0.0}
    mu = float(rets.mean() * 252)
    var = float(rets.var(ddof=1) * 252)
    return {"mu": mu, "variance": var, "sigma": var**0.5}


def wr_from_tallies(wins: int, losses: int, win_sum: float, loss_sum: float) -> tuple[float, float]:
    """Signal-conditioned (win_prob W, win/loss ratio R) from accumulated tallies.

    ``win_sum`` and ``loss_sum`` must be sums of *magnitudes* (abs returns), not
    signed returns. Returns the neutral prior (0.5, 1.0) — which yields discrete
    Kelly = 0 (flat) — when R is unestimable (no wins or no losses). Callers may
    add a minimum-sample guard on top; this helper is the single source of truth
    for the W/R formula shared by the live and backtest paths.
    """
    if wins == 0 or losses == 0:
        return 0.5, 1.0
    w = wins / (wins + losses)
    r = (win_sum / wins) / (loss_sum / losses)
    return w, r


def signal_kelly_stats(
    close: pd.Series, signal_fn: "Callable[..., tuple[str, float]] | None" = None,
    warmup: int = 60,
) -> tuple[float, float]:
    """Signal-conditioned (win_prob W, win/loss ratio R) for discrete Kelly.

    Walks the series: at each bar t the signal direction is decided from
    close[:t+1] alone (no look-ahead), then graded against the *next* bar's
    return. ``W`` is the hit rate — the fraction of active bars where the
    signal's direction matched the next-day return — and ``R`` is the average
    win magnitude divided by the average loss magnitude, both computed only
    over bars where the signal was active.

    These are the correct inputs for discrete Kelly on a directional signal:
    unlike the asset's unconditional daily win rate, they reflect the signal's
    actual edge (or lack of it). Defaults to ``trend_signal``, evaluated via the
    vectorized ``_trend_signal_series`` (O(n)). A custom ``signal_fn`` must
    accept a single ``pd.Series`` positional argument and return ``(label, score)``;
    note that ``breakout_signal`` does NOT fit this signature (it requires
    ``high, low, close``) and would need a ``functools.partial`` wrapper.
    """
    c = close.reset_index(drop=True)
    n = len(c)
    if n < warmup + 2:
        return 0.5, 1.0
    rets = c.pct_change()

    # Fast path: for the default trend signal, use the vectorized series to
    # avoid O(n²) per-bar recomputation. Other signal_fns fall back to per-bar.
    if signal_fn is None or signal_fn is trend_signal:
        labels = _trend_signal_series(c)[0]
    else:
        labels = [""] * n
        for t in range(warmup, n - 1):
            labels[t], _ = signal_fn(c.iloc[: t + 1])

    wins = losses = 0
    win_sum = loss_sum = 0.0
    for t in range(warmup, n - 1):
        label = labels[t]
        d = 1 if label == "bullish" else -1 if label == "bearish" else 0
        if d == 0:
            continue
        rt = rets.iloc[t + 1]
        if pd.isna(rt) or rt == 0:
            continue
        if np.sign(rt) == d:
            wins += 1
            win_sum += abs(rt)
        else:
            losses += 1
            loss_sum += abs(rt)
    return wr_from_tallies(wins, losses, win_sum, loss_sum)


def breakout_positions(
    high: pd.Series, low: pd.Series, close: pd.Series,
    entry_window: int = 20, exit_window: int = 10,
    adx_period: int = 14, adx_threshold: float = 0.0,
) -> list[int]:
    """Full per-bar position series for the Donchian breakout system.

    Returns a list of directions (1 long, -1 short, 0 flat) for each bar, where
    position[t] depends only on bars ≤ t (look-ahead-safe by construction: the
    entry/exit tests use prior N-day extremes only). Computing the whole series
    in one O(n) pass is far cheaper than re-simulating per bar.

    Regime gate: when `adx_threshold > 0`, entries are only taken when ADX
    (Wilder's trend-strength index) exceeds the threshold at that bar. ADX > 25
    is the canonical "trending" boundary; this normalises across assets so a
    single threshold works where a fixed ER cut did not.

    See `breakout_signal` for the system rules.
    """
    h = high.to_numpy()
    l = low.to_numpy()
    c = close.to_numpy()
    n = len(c)
    dirs = [0] * n
    if n < entry_window + 1:
        return dirs

    # Precompute the full ADX series once if the regime gate is active.
    adx_series = None
    if adx_threshold > 0.0 and n >= adx_period * 2:
        adx_series = _adx_series(high, low, close, adx_period)

    pos = 0
    for i in range(entry_window, n):
        eh = h[i - entry_window:i].max()
        el = l[i - entry_window:i].min()
        j = min(i, exit_window)
        xl = l[i - j:i].min()
        xh = h[i - j:i].max()
        px = c[i]

        if pos == 1 and px < xl:
            pos = 0
        elif pos == -1 and px > xh:
            pos = 0

        if pos == 0:
            # Regime gate: only enter when the market is trending (ADX above
            # threshold). In chop (low ADX) breakouts are false and bleed.
            enter = True
            if adx_series is not None:
                enter = adx_series[i] >= adx_threshold
            if enter:
                if px > eh:
                    pos = 1
                elif px < el:
                    pos = -1

        dirs[i] = pos
    return dirs


def breakout_signal(
    high: pd.Series, low: pd.Series, close: pd.Series,
    entry_window: int = 20, exit_window: int = 10,
    adx_threshold: float = 0.0,
) -> tuple[str, float]:
    """Donchian-style breakout entry (Turtle system 1), stateful.

    A fundamentally different signal class from SMA-cross: it enters on a
    *new* N-day extreme rather than a moving-average crossover, and *holds*
    until an opposite M-day extreme (shorter window) is hit. This gives
    inherent multi-day holding and cuts the whipsaw that kills SMA-cross in
    choppy markets.

    Because position state matters (you hold until an exit signal), this
    simulates the system forward through the window and returns the position
    held at the most recent bar. `breakout_positions` computes the full series
    efficiently; this wraps it for the per-bar call pattern of a future live
    signal-selector. Not yet wired into the live pipeline — the backtest uses
    `breakout_positions` directly and live `analyze` uses `trend_signal`.

    Returns (label, score in {-1, 0, 1}).
    """
    dirs = breakout_positions(high, low, close, entry_window, exit_window, adx_threshold=adx_threshold)
    pos = dirs[-1] if dirs else 0
    if pos == 1:
        return "bullish", 1.0
    if pos == -1:
        return "bearish", -1.0
    return "neutral", 0.0


def _trend_signal_series(close: pd.Series) -> tuple[list[str], np.ndarray]:
    """Full per-bar (labels, scores) series — vectorized trend_signal.

    Computes the multi-timeframe trend filter for every bar in one O(n) pass.
    `trend_signal` returns the last bar's values; `signal_kelly_stats` indexes
    the full series to avoid O(n²) per-bar recomputation. This is the single
    source of truth — `trend_signal` delegates here.
    """
    c = close.reset_index(drop=True)
    n = len(c)
    s20 = c.rolling(20).mean()
    s50 = c.rolling(50).mean()
    s200 = c.rolling(200).mean()

    # RSI series (Wilder) — replicate rsi() exactly: dropna before ewm so the
    # leading NaN from diff() doesn't seed the recursion, then reindex back.
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = _wilder_rma(gain.dropna(), 14).reindex(c.index)
    avg_loss = _wilder_rma(loss.dropna(), 14).reindex(c.index)
    # rsi = 100 - 100/(1+rs); avg_loss==0 -> 100 (if gain>0) else 50
    rs = avg_gain / avg_loss
    rsi_s = 100 - 100 / (1 + rs)
    zero_loss = avg_loss.eq(0) & avg_loss.notna()
    rsi_s = rsi_s.where(~zero_loss, np.where(avg_gain > 0, 100.0, 50.0))

    # ROC
    mom = c.pct_change(20)

    s20_np = s20.to_numpy()
    s50_np = s50.to_numpy()
    s200_np = s200.to_numpy()
    c_np = c.to_numpy()
    mom_np = mom.to_numpy()
    rsi_np = rsi_s.to_numpy()

    score = np.zeros(n)

    # Primary: medium-term trend (SMA cross).
    has_medium = ~np.isnan(s20_np) & ~np.isnan(s50_np)
    medium = np.where(s20_np > s50_np, 1.0, -1.0)
    score += np.where(has_medium, 0.5 * medium, 0.0)

    # Long-term trend filter: close vs SMA-200.
    has_long = ~np.isnan(s200_np)
    long_term = np.where(c_np > s200_np, 1.0, -1.0)
    score += np.where(has_long, 0.25 * long_term, 0.0)

    # flat: both defined and disagree -> force neutral, gate confirmations.
    flat = has_medium & has_long & (medium != long_term)
    score = np.where(flat, 0.0, score)

    # Momentum confirmation (not flat, mom not NaN).
    mom_valid = ~np.isnan(mom_np)
    mom_contrib = np.clip(mom_np * 2.0, -0.2, 0.2)
    score = np.where(flat | ~mom_valid, score, score + mom_contrib)

    # RSI exhaustion filter (not flat, rsi not NaN).
    rsi_valid = ~np.isnan(rsi_np)
    rsi_contrib = np.where(rsi_np > 80, -0.15, np.where(rsi_np < 20, 0.15, 0.0))
    score = np.where(flat | ~rsi_valid, score, score + rsi_contrib)

    score = np.clip(score, -1.0, 1.0)
    labels = [
        "bullish" if s > 0.15 else "bearish" if s < -0.45 else "neutral"
        for s in score
    ]
    return labels, score


def trend_signal(close: pd.Series) -> tuple[str, float]:
    """Coarse directional read from a multi-timeframe trend filter.
    Combines:
      - medium-term SMA-20/50 cross (primary, trend-following)
      - long-term SMA-200 filter (suppresses counter-trend whipsaws)
      - 20-day ROC momentum confirmation (bounded contribution)
      - Wilder RSI as an exhaustion filter (extremes damp, not mean-revert)

    The medium and long-term trends must agree; when they disagree the signal
    collapses toward neutral, which cuts the overtrading that a bare SMA-20/50
    cross produces in sideways markets.
    """
    labels, scores = _trend_signal_series(close)
    if not labels:
        return "neutral", 0.0
    return labels[-1], round(float(scores[-1]), 3)
