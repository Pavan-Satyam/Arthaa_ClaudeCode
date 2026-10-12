"""Script exporters — translate a signal definition to platform scripts (ARTHA-412).

Output convenience only: this renders the *same* signal logic (trend SMA filter,
Donchian breakout, time-series momentum) in TradingView Pine, MetaTrader MQL5, or
TDX formula syntax. It is **not** a claim of edge, and it does not contact any
broker — it just writes a file you can paste into a charting platform.
"""

from __future__ import annotations

from dataclasses import dataclass

PLATFORMS = ("pine", "mql5", "tdx")
KINDS = ("trend", "breakout", "tsmom")

_DISCLAIMER = "Output convenience only — not a claim of edge."


@dataclass(frozen=True)
class SignalSpec:
    """Platform-neutral description of a signal, mapped to each exporter."""

    symbol: str
    kind: str = "trend"
    fast: int = 20
    slow: int = 50
    long_filter: int = 200
    entry_window: int = 20
    exit_window: int = 10
    adx_threshold: float = 25.0
    lookback: int = 126


def render(spec: SignalSpec, platform: str) -> str:
    """Render ``spec`` for ``platform`` (``pine`` | ``mql5`` | ``tdx``)."""
    if spec.kind not in KINDS:
        raise ValueError(f"unknown signal kind: {spec.kind!r} (expected one of {KINDS})")
    platform = platform.strip().lower()
    if platform == "pine":
        return _pine(spec)
    if platform == "mql5":
        return _mql5(spec)
    if platform == "tdx":
        return _tdx(spec)
    raise ValueError(f"unknown platform: {platform!r} (expected one of {PLATFORMS})")


def _pine(spec: SignalSpec) -> str:
    header = (
        f'//@version=5\nstrategy("ArthaAI {spec.kind} · {spec.symbol}", overlay=true)\n'
        f"// {_DISCLAIMER}\n"
    )
    if spec.kind == "trend":
        body = (
            f"fast = ta.sma(close, {spec.fast})\n"
            f"slow = ta.sma(close, {spec.slow})\n"
            f"filt = ta.sma(close, {spec.long_filter})\n"
            "longCond = fast > slow and close > filt\n"
            'if longCond\n    strategy.entry("L", strategy.long)\n'
            'else\n    strategy.close("L")\n'
        )
    elif spec.kind == "breakout":
        body = (
            f"entryHigh = ta.highest(high, {spec.entry_window})[1]\n"
            f"exitLow = ta.lowest(low, {spec.exit_window})[1]\n"
            "[_, _, adxVal] = ta.dmi(14, 14)\n"
            f"longCond = close > entryHigh and adxVal >= {spec.adx_threshold:g}\n"
            f"exitCond = close < exitLow\n"
            'if longCond\n    strategy.entry("L", strategy.long)\n'
            'if exitCond\n    strategy.close("L")\n'
        )
    else:  # tsmom
        body = (
            f"mom = close / close[{spec.lookback}] - 1\n"
            "longCond = mom > 0\n"
            'if longCond\n    strategy.entry("L", strategy.long)\n'
            'else\n    strategy.close("L")\n'
        )
    return header + body


def _mql5(spec: SignalSpec) -> str:
    header = (
        "//+------------------------------------------------------------------+\n"
        f"//| ArthaAI exporter · {spec.kind} · {spec.symbol}\n"
        f"//| {_DISCLAIMER}\n"
        "//+------------------------------------------------------------------+\n"
        "#property strict\n"
    )
    if spec.kind == "trend":
        body = (
            f"input int Fast = {spec.fast};\n"
            f"input int Slow = {spec.slow};\n"
            f"input int LongFilter = {spec.long_filter};\n\n"
            "void OnTick()\n{\n"
            "   double fast = iMA(_Symbol, PERIOD_D1, Fast, 0, MODE_SMA, PRICE_CLOSE, 0);\n"
            "   double slow = iMA(_Symbol, PERIOD_D1, Slow, 0, MODE_SMA, PRICE_CLOSE, 0);\n"
            "   double filt = iMA(_Symbol, PERIOD_D1, LongFilter, 0, MODE_SMA, PRICE_CLOSE, 0);\n"
            "   bool longCond = (fast > slow) && (Close[0] > filt);\n"
            "   // TODO: route longCond to your order-management layer.\n"
            "}\n"
        )
    elif spec.kind == "breakout":
        body = (
            f"input int EntryWindow = {spec.entry_window};\n"
            f"input int ExitWindow = {spec.exit_window};\n"
            f"input double AdxThreshold = {spec.adx_threshold:g};\n\n"
            "void OnTick()\n{\n"
            "   int entryHigh = iHighest(_Symbol, PERIOD_D1, MODE_HIGH, EntryWindow, 1);\n"
            "   double entry = High[entryHigh];\n"
            "   double adx = iADX(_Symbol, PERIOD_D1, 14, PRICE_CLOSE, MODE_MAIN, 0);\n"
            "   bool longCond = (Close[0] > entry) && (adx >= AdxThreshold);\n"
            "   // TODO: route longCond to your order-management layer.\n"
            "}\n"
        )
    else:  # tsmom
        body = (
            f"input int Lookback = {spec.lookback};\n\n"
            "void OnTick()\n{\n"
            "   double past = iClose(_Symbol, PERIOD_D1, Lookback);\n"
            "   bool longCond = (past > 0) && (Close[0] > past);\n"
            "   // TODO: route longCond to your order-management layer.\n"
            "}\n"
        )
    return header + body


def _tdx(spec: SignalSpec) -> str:
    header = f"{{ArthaAI exporter · {spec.kind} · {spec.symbol} — {_DISCLAIMER}}}\n"
    if spec.kind == "trend":
        body = (
            f"MAFAST:MA(CLOSE,{spec.fast});\n"
            f"MASLOW:MA(CLOSE,{spec.slow});\n"
            f"MAFILT:MA(CLOSE,{spec.long_filter});\n"
            "LONG:IF(MAFAST>MASLOW AND CLOSE>MAFILT,1,0);\n"
        )
    elif spec.kind == "breakout":
        body = (
            f"ENTRY:REF(HHV(HIGH,{spec.entry_window}),1);\n"
            f"EXIT:REF(LLV(LOW,{spec.exit_window}),1);\n"
            "LONG:IF(CLOSE>ENTRY AND ADX(14)>"
            f"{spec.adx_threshold:g},1,0);\n"
        )
    else:  # tsmom
        body = (
            f"MOM:(CLOSE/REF(CLOSE,{spec.lookback})-1)*100;\n"
            "LONG:IF(MOM>0,1,0);\n"
        )
    return header + body
