"""Asset Manager Agent (Tier 3) — Kelly-optimised position sizing.

Implements both Kelly formulations from the blueprint, the fractional (quarter-
Kelly) scaling of Busseti et al. (2016), and the deterministic policy override
that caps single-instrument exposure regardless of the probabilistic model.

    Discrete (binary):    f = W - (1 - W) / R
    Continuous (returns): f* = (mu - r) / sigma^2
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from arthaai.agents import risk
from arthaai.config import get_settings
from arthaai.security import AgentIdentity, authorize_tool

IDENTITY = AgentIdentity("asset_manager", "spiffe://arthaai/agent/asset_manager")


@dataclass
class Allocation:
    discrete_kelly: float
    continuous_kelly: float
    raw_fraction: float        # chosen Kelly before scaling
    fractional: float          # after quarter-Kelly scaling
    final_fraction: float      # after policy cap
    capped_by_policy: bool
    rationale: str
    factor_multiplier: float = 1.0      # factor-gate multiplier applied (1.0 = none)
    factor_signal: float | None = None  # factor signal that informed the gate
    vol_multiplier: float = 1.0         # volatility-target multiplier applied
    var_95: float | None = None         # annualised parametric VaR (positive loss)
    expected_shortfall_95: float | None = None  # annualised parametric ES (CVaR)
    kelly_fraction_used: float | None = None    # dynamic Kelly fraction (ARTHA-311)


@dataclass
class PortfolioAllocation:
    """Covariance-aware allocation across several assets (ARTHA-309)."""

    fractions: dict[str, float]              # final per-asset exposure
    standalone_fractions: dict[str, float]   # before correlation de-risking
    correlation_multiplier: float            # de-risk factor in (0, 1]
    portfolio_sigma: float                   # annualised portfolio volatility
    total_exposure: float
    capped_by_policy: bool
    rationale: str


def discrete_kelly(win_prob: float, win_loss_ratio: float) -> float:
    if win_loss_ratio <= 0:
        return 0.0
    return win_prob - (1 - win_prob) / win_loss_ratio


def continuous_kelly(mu: float, variance: float, risk_free: float) -> float:
    if variance <= 0:
        return 0.0
    return (mu - risk_free) / variance


def dynamic_kelly_fraction(
    sigma: float | None,
    *,
    base: float,
    target_vol: float,
    floor: float,
    ceil: float,
) -> float:
    """Scale the Kelly fraction by the volatility regime (ARTHA-311).

    Inverse-vol scaling: a high realised vol shrinks the fraction (more
    conservative), a low vol grows it — always bounded to ``[floor, ceil]``.
    Falls back to ``base`` when vol is unavailable or the target is non-positive.
    """
    if sigma is None or sigma <= 0 or target_vol <= 0:
        return base
    return max(floor, min(ceil, base * (target_vol / sigma)))


def _as_float(value) -> float | None:
    """Return ``value`` as a finite float, or None for None/NaN/non-numeric."""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # NaN != NaN


def size(
    quant: dict,
    *,
    confidence: float | None = None,
    factor_gate: bool | None = None,
    vol_target: float | None = None,
    vol_max_leverage: float | None = None,
) -> Allocation:
    """Compute a bounded position fraction from the quant agent's statistics.

    `confidence` (0..1), when supplied by the Master LLM, tempers the win
    probability — the LLM informs but never overrides the deterministic caps.

    Factor gate (E2): when the pipeline supplies ``quant["factor_signal"]`` and
    the gate is enabled (``Settings.factor_gate``, override via ``factor_gate``),
    a factor signal that *conflicts* with a long edge dampens the size by
    ``Settings.factor_dampening``. It can only reduce exposure — never amplify —
    and is still subject to the hard policy cap, so a noisy factor cannot
    inflate risk. When no factor signal is present the sizing is unchanged.
    """
    authorize_tool(IDENTITY, "kelly")
    s = get_settings()

    w = quant.get("win_prob", 0.5)
    if confidence is not None:
        w = max(0.0, min(1.0, 0.5 * w + 0.5 * confidence))
    r = quant.get("win_loss_ratio", 1.0)

    d_kelly = discrete_kelly(w, r)
    c_kelly = continuous_kelly(quant.get("mu", 0.0), quant.get("variance", 0.0), s.risk_free_rate)

    # Directional signals (trend / breakout) are discrete win/loss bets, so the
    # discrete Kelly fraction is the sound sizing driver. Continuous Kelly is
    # retained only as a reported cross-check: with annualised mu/variance it
    # routinely exceeds 100% and would let the policy cap do all the sizing,
    # hiding the signal's (lack of) edge. A negative or zero discrete edge sizes
    # to flat (no shorting here) rather than pumping leverage via continuous Kelly.
    raw = max(0.0, float(d_kelly))

    # --- Dynamic Kelly fraction (ARTHA-311) ---------------------------------
    # Scale the Kelly aggressiveness by the volatility regime instead of using a
    # static fraction. Opt-in; bounded so it can never exceed the configured cap.
    sigma = _as_float(quant.get("sigma"))
    kelly_fraction = s.kelly_fraction
    dynamic_note = ""
    if s.dynamic_kelly and sigma and sigma > 0 and s.dynamic_kelly_target_vol > 0:
        kelly_fraction = dynamic_kelly_fraction(
            sigma, base=s.kelly_fraction, target_vol=s.dynamic_kelly_target_vol,
            floor=s.kelly_fraction_min, ceil=s.kelly_fraction_max,
        )
        dynamic_note = (
            f"dynamic Kelly fraction {kelly_fraction:.2f} "
            f"(σ={sigma:.1%} vs target {s.dynamic_kelly_target_vol:.0%}). "
        )
    fractional = raw * kelly_fraction

    # --- Volatility targeting (C): scale exposure toward a target annual vol --
    # Directly raises risk-adjusted return (the binding promotion criterion).
    # Only de-risks by default (max leverage 1.0). Disabled when vol_target <= 0
    # or sigma is unavailable.
    vt = s.vol_target if vol_target is None else vol_target
    vmax = s.vol_max_leverage if vol_max_leverage is None else vol_max_leverage
    vol_mult = 1.0
    vol_note = ""
    if vt and vt > 0 and sigma and sigma > 0:
        vol_mult = min(vmax, vt / sigma)
        vol_note = f"vol target {vt:.0%}: σ={sigma:.1%} → ×{vol_mult:.2f}. "
    scaled = fractional * vol_mult

    # --- Factor gate (E2): deterministic, dampen-only ------------------------
    gate_on = s.factor_gate if factor_gate is None else factor_gate
    signal = _as_float(quant.get("factor_signal"))
    factor_mult = 1.0
    factor_note = ""
    if gate_on and signal is not None:
        if d_kelly > 0 and signal < -s.factor_epsilon:
            factor_mult = s.factor_dampening
            factor_note = f"factor gate: signal {signal:.3f} conflicts with long → ×{factor_mult:g}. "
        elif d_kelly > 0 and signal > s.factor_epsilon:
            factor_note = f"factor gate: signal {signal:.3f} confirms long. "
        elif abs(signal) <= s.factor_epsilon:
            factor_note = "factor gate: signal neutral. "
    gated = scaled * factor_mult

    final = float(min(gated, s.max_single_instrument))
    capped = bool(final < gated)

    # --- Tail risk (ARTHA-310): annualised parametric VaR / ES, informational --
    # Reported on the *sized* exposure so the allocation carries its own tail-risk
    # view; it never feeds back into sizing (no hidden leverage).
    mu = _as_float(quant.get("mu")) or 0.0
    var95 = es95 = None
    risk_note = ""
    if sigma and sigma > 0:
        var95 = risk.parametric_var(mu, sigma, 0.95)
        es95 = risk.parametric_expected_shortfall(mu, sigma, 0.95)
        risk_note = (
            f"annualised 95% VaR={var95 * final:.2%} "
            f"ES={es95 * final:.2%} on {final:.2%} exposure. "
        )

    rationale = (
        f"Kelly ({kelly_fraction:g}x) on discrete f={d_kelly:.3f} "
        f"(W={w:.2f}, R={r:.2f}); continuous f*={c_kelly:.2f} (informational); "
        + dynamic_note
        + vol_note
        + factor_note
        + risk_note
        + (
            f"policy cap of {s.max_single_instrument:.0%} single-instrument exposure enforced."
            if capped
            else "within single-instrument policy limit."
        )
    )
    return Allocation(
        discrete_kelly=round(d_kelly, 4),
        continuous_kelly=round(c_kelly, 4),
        raw_fraction=round(raw, 4),
        fractional=round(fractional, 4),
        final_fraction=round(final, 4),
        capped_by_policy=capped,
        rationale=rationale,
        factor_multiplier=round(factor_mult, 4),
        factor_signal=None if signal is None else round(signal, 4),
        vol_multiplier=round(vol_mult, 4),
        var_95=None if var95 is None else round(var95, 4),
        expected_shortfall_95=None if es95 is None else round(es95, 4),
kelly_fraction_used=round(kelly_fraction, 4),
    )


def portfolio_size(
    quant_map: dict[str, dict],
    returns,
    *,
    confidence_map: dict[str, float] | None = None,
    vol_target: float | None = None,
    vol_max_leverage: float | None = None,
) -> PortfolioAllocation:
    """Covariance-aware allocation across a universe (ARTHA-309).

    Per-asset discrete Kelly fractions remain the sizing driver; the covariance
    matrix is used only to *de-risk* correlated books, never to add leverage.
    When assets are independent the correlation multiplier is 1.0; as they co-move
    the multiplier shrinks so portfolio variance matches the sum of standalone
    variances. A hard cap bounds total exposure.
    """
    authorize_tool(IDENTITY, "kelly")
    s = get_settings()
    conf_map = confidence_map or {}
    vt = s.vol_target if vol_target is None else vol_target
    vmax = s.vol_max_leverage if vol_max_leverage is None else vol_max_leverage

    syms = [sym for sym in quant_map if sym in getattr(returns, "columns", [])]
    if not syms:
        return PortfolioAllocation(
            fractions={}, standalone_fractions={}, correlation_multiplier=1.0,
            portfolio_sigma=0.0, total_exposure=0.0, capped_by_policy=False,
            rationale="no assets with return history — nothing to size.",
        )

    standalone: dict[str, float] = {}
    for sym in syms:
        # Delegate to the canonical single-asset sizer so the factor gate (E2),
        # dynamic Kelly (ARTHA-311), policy cap and vol targeting are identical
        # to the live path; only the covariance de-risk is added below.
        alloc = size(
            quant_map[sym],
            confidence=conf_map.get(sym),
            vol_target=vt,
            vol_max_leverage=vmax,
        )
        standalone[sym] = alloc.final_fraction

    f_vec = np.array([standalone[sym] for sym in syms], dtype=float)
    cov = returns[syms].cov().to_numpy(dtype=float)

    correlation_multiplier = 1.0
    if f_vec.size and np.all(np.isfinite(cov)):
        port_var = float(f_vec @ cov @ f_vec)
        standalone_var = float(np.sum((f_vec ** 2) * np.diag(cov)))
        if port_var > 0 and standalone_var > 0:
            correlation_multiplier = min(1.0, float(np.sqrt(standalone_var / port_var)))

    fractions = {sym: standalone[sym] * correlation_multiplier for sym in syms}

    total = sum(fractions.values())
    capped = False
    if total > s.max_portfolio_exposure > 0:
        scale = s.max_portfolio_exposure / total
        fractions = {sym: v * scale for sym, v in fractions.items()}
        capped = True

    f_final = np.array([fractions[sym] for sym in syms], dtype=float)
    portfolio_sigma = 0.0
    if f_final.size and np.all(np.isfinite(cov)):
        portfolio_sigma = float(np.sqrt(max(0.0, f_final @ cov @ f_final)) * np.sqrt(252))

    rationale = (
        f"portfolio Kelly across {len(syms)} assets; discrete Kelly drives each "
        f"fraction, correlation multiplier ×{correlation_multiplier:.2f}, "
        f"annualised portfolio σ={portfolio_sigma:.1%}, "
        f"total exposure {sum(fractions.values()):.1%}"
        + (" (capped by policy)." if capped else ".")
    )
    return PortfolioAllocation(
        fractions={k: round(v, 4) for k, v in fractions.items()},
        standalone_fractions={k: round(v, 4) for k, v in standalone.items()},
        correlation_multiplier=round(correlation_multiplier, 4),
        portfolio_sigma=round(portfolio_sigma, 4),
        total_exposure=round(sum(fractions.values()), 4),
        capped_by_policy=capped,
        rationale=rationale,
    )
