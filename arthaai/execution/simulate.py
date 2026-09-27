"""Bar-by-bar paper simulation driven by the shared execution state machine.

The algebraic backtest (``arthaai.backtest.engine``) measures signal edge with
frictionless Kelly sizing and never touches the Position state machine, so the
mandatory stop-loss / target triggers in ``Position.step()`` are unreachable
there. This module walks the *same* state machine over historical bars so stops
and targets actually fire, producing an execution-level P&L and equity curve.

Look-ahead safety matches the backtest: the signal at bar *t* is computed from
bars ``<= t`` only, and a position opened at bar *t* is only marked or exited
from bar *t+1* onward (the engine steps existing positions before considering a
new entry on each bar).

Long-only: entries happen on a bullish signal; a position is also closed when
the signal stops being bullish (a "signal" exit). Bearish/neutral bars otherwise
stay flat — no synthetic shorting, matching the sizing policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from arthaai.agents import indicators
from arthaai.execution.engine import ExecutionEngine
from arthaai.execution.state import Fill, PositionState


@dataclass
class SimulationResult:
    symbol: str
    bars: int
    entries: int
    exits: int
    stops_hit: int
    targets_hit: int
    realised_pnl: float
    final_equity: float
    max_drawdown: float
    equity_curve: list[float] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)


def simulate_symbol(
    symbol: str,
    df: pd.DataFrame,
    *,
    warmup: int = 60,
    signal: str = "trend",
    adx_threshold: float = 0.0,
    entry_window: int = 55,
    exit_window: int = 20,
    allocation_fraction: float = 0.05,
    equity: float = 100_000.0,
    stop_loss_pct: float = 0.08,
    engine: ExecutionEngine | None = None,
) -> SimulationResult:
    """Run the execution state machine bar-by-bar over ``df``.

    Args:
        symbol: Ticker (position key and labels).
        df: OHLCV bars with ts/open/high/low/close columns, ascending.
        warmup: Bars to skip before the first signal.
        signal: 'trend' (multi-timeframe SMA filter) or 'breakout' (Donchian).
        adx_threshold: ADX regime gate for the breakout signal.
        entry_window / exit_window: Donchian windows for the breakout signal.
        allocation_fraction: Fraction of equity per entry (policy cap is the caller's).
        equity: Starting paper equity (ignored when ``engine`` is supplied).
        stop_loss_pct: Mandatory stop distance for every entry.
        engine: Optional pre-built engine (e.g. with an AuditLog attached).

    Returns:
        SimulationResult with fills, stop/target counts and the equity curve.
    """
    symbol = symbol.upper()
    if df.empty:
        raise ValueError(f"no bars for {symbol}")

    df = df.reset_index(drop=True)
    close = df["close"]
    high = df["high"]
    low = df["low"]

    breakout_dirs = (
        indicators.breakout_positions(
            high, low, close,
            entry_window=entry_window, exit_window=exit_window, adx_threshold=adx_threshold,
        )
        if signal == "breakout"
        else None
    )

    def direction_at(t: int) -> int:
        """Signal direction using bars <= t only (look-ahead safe)."""
        if signal == "breakout":
            d = breakout_dirs[t] if breakout_dirs is not None else 0
            return 1 if d == 1 else (-1 if d == -1 else 0)
        label, _ = indicators.trend_signal(close.iloc[: t + 1])
        return 1 if label == "bullish" else (-1 if label == "bearish" else 0)

    eng = engine or ExecutionEngine(initial_equity=equity, stop_loss_pct=stop_loss_pct)
    entries = exits = stops = targets = 0
    fills: list[Fill] = []
    curve: list[float] = []

    for t in range(warmup, len(df)):
        bar = df.iloc[t]

        # 1) mark-to-market and fire stops/targets from any prior entry.
        levels: tuple[float | None, float | None] = (None, None)
        pos = eng.portfolio.positions.get(symbol)
        if pos is not None and pos.state == PositionState.OPEN:
            levels = (pos.stop_price, pos.target_price)
        step_fills = eng.step(bar)
        fill = step_fills.get(symbol)
        if fill is not None:
            fills.append(fill)
            stop, target = levels
            if stop is not None and fill.price == stop:
                stops += 1
            elif target is not None and fill.price == target:
                targets += 1
            else:
                exits += 1

        det = direction_at(t)

        # 2) signal exit: long-only, so close when the signal is no longer bullish.
        pos = eng.portfolio.positions.get(symbol)
        if fill is None and pos is not None and pos.state == PositionState.OPEN and det != 1:
            sig_fill = eng.exit_position(
                symbol, float(bar["close"]), ts=bar["ts"], reason="signal"
            )
            if sig_fill is not None:
                fills.append(sig_fill)
                exits += 1

        # 3) entry using only bars <= t. Skip the bar that just exited a position.
        pos = eng.portfolio.positions.get(symbol)
        flat = pos is None or pos.state != PositionState.OPEN
        if fill is None and flat and det == 1 and eng.portfolio.is_buyable():
            eng.submit(
                symbol,
                {"final_fraction": allocation_fraction},
                float(bar["close"]),
                "bullish",
                ts=bar["ts"],
            )
            entries += 1

        # 4) equity at this bar's close (mark open position at close, not entry).
        curve.append(eng.portfolio.mark_to_market({symbol: float(bar["close"])}))

    pos = eng.portfolio.positions.get(symbol)
    realised = float(pos.realised_pnl) if pos is not None else 0.0

    peak = curve[0] if curve else equity
    max_dd = 0.0
    for eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = min(max_dd, (eq - peak) / peak)

    return SimulationResult(
        symbol=symbol,
        bars=len(df),
        entries=entries,
        exits=exits,
        stops_hit=stops,
        targets_hit=targets,
        realised_pnl=realised,
        final_equity=curve[-1] if curve else equity,
        max_drawdown=max_dd,
        equity_curve=curve,
        fills=fills,
    )
