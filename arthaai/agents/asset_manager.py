"""Asset Manager Agent (Tier 3) — Kelly-optimised position sizing.

Implements both Kelly formulations from the blueprint, the fractional (quarter-
Kelly) scaling of Busseti et al. (2016), and the deterministic policy override
that caps single-instrument exposure regardless of the probabilistic model.

    Discrete (binary):    f = W - (1 - W) / R
    Continuous (returns): f* = (mu - r) / sigma^2
"""

from __future__ import annotations

from dataclasses import dataclass

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


def discrete_kelly(win_prob: float, win_loss_ratio: float) -> float:
    if win_loss_ratio <= 0:
        return 0.0
    return win_prob - (1 - win_prob) / win_loss_ratio


def continuous_kelly(mu: float, variance: float, risk_free: float) -> float:
    if variance <= 0:
        return 0.0
    return (mu - risk_free) / variance


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
    fractional = raw * s.kelly_fraction

    # --- Volatility targeting (C): scale exposure toward a target annual vol --
    # Directly raises risk-adjusted return (the binding promotion criterion).
    # Only de-risks by default (max leverage 1.0). Disabled when vol_target <= 0
    # or sigma is unavailable.
    sigma = _as_float(quant.get("sigma"))
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
    rationale = (
        f"quarter-Kelly ({s.kelly_fraction:g}x) on discrete f={d_kelly:.3f} "
        f"(W={w:.2f}, R={r:.2f}); continuous f*={c_kelly:.2f} (informational); "
        + vol_note
        + factor_note
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
    )
