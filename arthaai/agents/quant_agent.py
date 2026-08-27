"""Quant Agent — studies mathematical financial models.

Computes annualised return/variance/volatility and the signal-conditioned
discrete-Kelly inputs (win probability W, win/loss ratio R) that the Asset
Manager consumes. W and R are derived from the active signal's historical hit
rate and payoff, not the asset's unconditional daily returns, so they reflect
the signal's actual edge.

Signal selection mirrors db_agent: ADX≥25 uses breakout Kelly stats, else trend.

Alpha Zoo factor engine: evaluates the top-ranking alpha factors from the
445-factor zoo (Alpha101, GTJA191, Qlib158) against the asset and reports
the strongest factors and their directional signal. This is the ★ "Alpha-Zoo
factor engine" the blueprint calls for — "the edge lives here."
"""

from __future__ import annotations

from arthaai.agents import indicators
from arthaai.agents.indicators import BREAKOUT_ADX_THRESHOLD
from arthaai.db import timescale
from arthaai.security import AgentIdentity, authorize_tool

IDENTITY = AgentIdentity("quant_agent", "spiffe://arthaai/agent/quant_agent")

# Default factor universes to evaluate (subset for speed; full set available via CLI)
DEFAULT_FACTOR_ZOOS = ["alpha101"]
DEFAULT_TOP_K = 5


def run(symbol: str, factor_zoos: list[str] | None = None, top_k: int = 0) -> dict:
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

    result = {
        "available": True,
        "mu": round(stats["mu"], 4),
        "variance": round(stats["variance"], 6),
        "sigma": round(stats["sigma"], 4),
        "win_prob": round(w, 4),
        "win_loss_ratio": round(r, 4),
        "signal_class": signal_class,
    }

    # Alpha Zoo factor evaluation — the ★ star component.
    # Loads the factor registry, builds a single-asset panel, evaluates factors,
    # and reports the top-K by absolute factor value (directional signal strength).
    try:
        factor_scores = _evaluate_factors(symbol, df, factor_zoos, top_k or DEFAULT_TOP_K)
        if factor_scores:
            result["factors"] = factor_scores
            # Aggregate factor direction: bullish if mean > 0, bearish if < 0
            factor_signal = sum(f["score"] for f in factor_scores) / len(factor_scores)
            result["factor_signal"] = round(factor_signal, 4)
    except Exception:
        pass  # Factor engine is non-blocking — degrade gracefully if unavailable

    return result


def _evaluate_factors(
    symbol: str,
    df: "pd.DataFrame",
    zoos: list[str] | None,
    top_k: int,
) -> list[dict]:
    """Evaluate Alpha Zoo factors and return the top-K by absolute score.

    For a single asset, factors return a 1-column DataFrame. We take the last
    bar's value as the current factor score. This is a time-series evaluation
    (not cross-sectional) — for cross-sectional ranking across a universe, use
    the full panel + IC evaluation pipeline.
    """
    from arthaai.factors.panel import build_panel
    from arthaai.factors.registry import get_default_registry

    zoos = zoos or DEFAULT_FACTOR_ZOOS
    panel = build_panel({symbol: df})
    if not panel or "close" not in panel:
        return []

    reg = get_default_registry()
    scores: list[dict] = []

    for zoo in zoos:
        alpha_ids = reg.list(zoo=zoo)
        for alpha_id in alpha_ids:
            try:
                factor_df = reg.compute(alpha_id, panel)
                if factor_df.empty:
                    continue
                # Single asset: take last row's value (current signal)
                last_val = factor_df.iloc[-1]
                if last_val.isna().all():
                    continue
                score = float(last_val.dropna().iloc[0]) if not last_val.dropna().empty else 0.0
                if score == 0.0 or pd.isna(score):
                    continue
                scores.append({
                    "id": alpha_id,
                    "zoo": zoo,
                    "score": round(score, 6),
                })
            except Exception:
                continue  # Skip factors that fail on this data

    # Sort by absolute score descending, return top-K
    scores.sort(key=lambda x: abs(x["score"]), reverse=True)
    return scores[:top_k]


# Type hint for pd (imported lazily to avoid circular imports)
import pandas as pd  # noqa: E402
