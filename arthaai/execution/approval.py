"""Human decision gate for Tier 3 (ARTHA-308).

Law 3 and the blueprint require a human in the loop before capital moves: the
system proposes, a person approves or rejects, and the decision is recorded.
Previously the only "gate" was that nothing auto-connected to a broker — there
was no explicit approval step, no pending state, and no audit trail.

This module makes the gate explicit and persistent. A proposal is written to an
append-only JSONL log; the gate state is reconstructed by replaying those events,
so a decision survives a process restart. Approval is a *separate* act from
proposal: ``propose()`` never trades, and ``decide()`` can only be applied once
per proposal.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from arthaai.execution.audit import AuditLog, read_audit


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Proposal:
    id: str
    symbol: str
    side: str
    notional: float
    stop_loss: float
    final_fraction: float
    rationale: str = ""
    created_at: str = ""
    status: str = "pending"          # pending | approved | rejected
    decided_by: str | None = None
    decided_at: str | None = None
    reason: str = ""


class ApprovalGate:
    """Append-only human approval workflow backed by a JSONL log."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._log = AuditLog(self.path)
        self._cache: dict[str, Proposal] | None = None

    def propose(
        self,
        *,
        symbol: str,
        side: str,
        notional: float,
        stop_loss: float,
        final_fraction: float,
        rationale: str = "",
    ) -> Proposal:
        """Record a pending proposal. Does not trade."""
        proposal = Proposal(
            id=uuid.uuid4().hex[:12],
            symbol=symbol.upper(),
            side=side,
            notional=float(notional),
            stop_loss=float(stop_loss),
            final_fraction=float(final_fraction),
            rationale=rationale,
            created_at=_now(),
        )
        self._log.write("proposal", **asdict(proposal))
        self._cache = None
        return proposal

    def load(self) -> dict[str, Proposal]:
        """Replay the log into the current proposal set (cached per instance)."""
        if self._cache is not None:
            return self._cache
        proposals: dict[str, Proposal] = {}
        for rec in read_audit(self.path):
            event = rec.get("event")
            if event == "proposal":
                p = Proposal(
                    id=str(rec.get("id", "")),
                    symbol=str(rec.get("symbol", "")),
                    side=str(rec.get("side", "")),
                    notional=float(rec.get("notional", 0.0)),
                    stop_loss=float(rec.get("stop_loss", 0.0)),
                    final_fraction=float(rec.get("final_fraction", 0.0)),
                    rationale=str(rec.get("rationale", "")),
                    created_at=str(rec.get("created_at", "")),
                )
                proposals[p.id] = p
            elif event == "decision":
                p = proposals.get(str(rec.get("proposal_id", "")))
                if p is not None:
                    p.status = str(rec.get("status", p.status))
                    p.decided_by = rec.get("by")
                    p.decided_at = rec.get("decided_at")
                    p.reason = str(rec.get("reason", ""))
        self._cache = proposals
        return proposals

    def get(self, proposal_id: str) -> Proposal | None:
        return self.load().get(proposal_id)

    def pending(self) -> list[Proposal]:
        return [p for p in self.load().values() if p.status == "pending"]

    def is_approved(self, proposal_id: str) -> bool:
        p = self.get(proposal_id)
        return p is not None and p.status == "approved"

    def decide(
        self, proposal_id: str, *, approved: bool, by: str, reason: str = ""
    ) -> Proposal:
        """Approve or reject a pending proposal exactly once."""
        proposals = self.load()
        p = proposals.get(proposal_id)
        if p is None:
            raise KeyError(proposal_id)
        if p.status != "pending":
            raise ValueError(f"proposal {proposal_id} already {p.status}")
        p.status = "approved" if approved else "rejected"
        p.decided_by = by
        p.decided_at = _now()
        p.reason = reason
        self._log.write(
            "decision",
            proposal_id=proposal_id,
            status=p.status,
            by=by,
            reason=reason,
            decided_at=p.decided_at,
        )
        self._cache = None
        return p

    def mark_executed(self, proposal_id: str, *, by: str = "") -> Proposal:
        """Mark an approved proposal as executed (terminal, one-shot).

        Prevents a single approval from authorizing more than one order.
        """
        proposals = self.load()
        p = proposals.get(proposal_id)
        if p is None:
            raise KeyError(proposal_id)
        if p.status != "approved":
            raise ValueError(f"proposal {proposal_id} is {p.status}, not approved")
        p.status = "executed"
        if by:
            p.decided_by = by
        p.decided_at = _now()
        self._log.write(
            "decision", proposal_id=proposal_id, status="executed", by=by,
            decided_at=p.decided_at,
        )
        self._cache = None
        return p