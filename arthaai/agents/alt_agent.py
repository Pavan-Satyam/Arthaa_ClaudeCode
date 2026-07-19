"""Alt_Agent — alternative / physical intelligence.

STUB. Real deployment connects via MCP to paid vendors (Kpler, Vortexa, Kayrros,
Ursa Space) for cargo flows, storage levels, and satellite geospatial signals —
none of which are accessible without commercial contracts. This returns a clearly
labelled synthetic signal for commodity ETFs so the pipeline demonstrates the
Alt_Agent's role, and abstains for equities.
"""

from __future__ import annotations

from arthaai.db import timescale
from arthaai.security import AgentIdentity, authorize_tool

IDENTITY = AgentIdentity("alt_agent", "spiffe://arthaai/agent/alt_agent")

# Illustrative physical-signal directionality per commodity ETF (STUB DATA).
_SYNTHETIC = {
    "USO": (-0.4, "Elevated floating crude storage and softening vessel demand (Kpler-style signal)."),
    "GLD": (0.2, "Steady vault inflows; no physical stress detected."),
    "SLV": (0.1, "Industrial silver draw stable; mild positive tilt."),
    "DBC": (-0.1, "Mixed broad-commodity physical flows; roughly balanced."),
}


def run(symbol: str) -> dict:
    authorize_tool(IDENTITY, "external_api")
    meta = timescale.asset_meta(symbol) or {}
    if meta.get("asset_class") != "commodity_etf" or symbol.upper() not in _SYNTHETIC:
        return {"available": False, "reason": "no physical-data coverage for this asset (equity)."}
    score, note = _SYNTHETIC[symbol.upper()]
    return {
        "available": True,
        "stub": True,
        "provider": "Kpler/Ursa (stubbed)",
        "physical_score": score,
        "note": note,
    }
