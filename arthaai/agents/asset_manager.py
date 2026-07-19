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


def discrete_kelly(win_prob: float, win_loss_ratio: float) -> float:
    if win_loss_ratio <= 0:
        return 0.0
    return win_prob - (1 - win_prob) / win_loss_ratio


def continuous_kelly(mu: float, variance: float, risk_free: float) -> float:
    if variance <= 0:
        return 0.0
    return (mu - risk_free) / variance


def size(quant: dict, *, confidence: float | None = None) -> Allocation:
    """Compute a bounded position fraction from the quant agent's statistics.

    `confidence` (0..1), when supplied by the Master LLM, tempers the win
    probability — the LLM informs but never overrides the deterministic caps.
    """
    authorize_tool(IDENTITY, "kelly")
    s = get_settings()

    w = quant.get("win_prob", 0.5)
    if confidence is not None:
        w = max(0.0, min(1.0, 0.5 * w + 0.5 * confidence))
    r = quant.get("win_loss_ratio", 1.0)

    d_kelly = discrete_kelly(w, r)
    c_kelly = continuous_kelly(quant.get("mu", 0.0), quant.get("variance", 0.0), s.risk_free_rate)

    # Prefer the continuous form for continuous assets; clamp negatives to 0 (no shorting here).
    raw = max(0.0, c_kelly if quant.get("variance", 0) > 0 else d_kelly)
    fractional = raw * s.kelly_fraction

    final = min(fractional, s.max_single_instrument)
    capped = final < fractional
    rationale = (
        f"quarter-Kelly ({s.kelly_fraction:g}x) applied to smooth drawdowns; "
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
    )
