"""Human decision gate — proposal, approval, rejection, persistence (ARTHA-308)."""

import pytest

from arthaai.execution import ApprovalGate
from arthaai.execution.approval import Proposal


def _gate(tmp_path):
    return ApprovalGate(tmp_path / "gate.jsonl")


def _propose(gate, symbol="GLD"):
    return gate.propose(
        symbol=symbol, side="buy", notional=5000.0, stop_loss=92.0,
        final_fraction=0.05, rationale="quarter-Kelly on a discrete edge",
    )


class TestApprovalGate:
    def test_proposal_starts_pending(self, tmp_path):
        gate = _gate(tmp_path)
        p = _propose(gate)
        assert isinstance(p, Proposal)
        assert p.status == "pending"
        assert p.symbol == "GLD"
        assert gate.pending() == [p]
        assert gate.is_approved(p.id) is False

    def test_approve_marks_approved(self, tmp_path):
        gate = _gate(tmp_path)
        p = _propose(gate)
        decided = gate.decide(p.id, approved=True, by="alice")
        assert decided.status == "approved"
        assert decided.decided_by == "alice"
        assert gate.is_approved(p.id) is True
        assert gate.pending() == []

    def test_reject_records_reason(self, tmp_path):
        gate = _gate(tmp_path)
        p = _propose(gate)
        decided = gate.decide(p.id, approved=False, by="bob", reason="too concentrated")
        assert decided.status == "rejected"
        assert decided.reason == "too concentrated"
        assert gate.is_approved(p.id) is False

    def test_decision_survives_new_gate_instance(self, tmp_path):
        path = tmp_path / "gate.jsonl"
        p = _propose(ApprovalGate(path))
        ApprovalGate(path).decide(p.id, approved=True, by="alice")
        assert ApprovalGate(path).is_approved(p.id) is True

    def test_cannot_decide_twice(self, tmp_path):
        gate = _gate(tmp_path)
        p = _propose(gate)
        gate.decide(p.id, approved=True, by="alice")
        with pytest.raises(ValueError, match="already approved"):
            gate.decide(p.id, approved=False, by="bob")

    def test_unknown_proposal_raises(self, tmp_path):
        with pytest.raises(KeyError):
            _gate(tmp_path).decide("deadbeef", approved=True, by="alice")

    def test_multiple_proposals_tracked_independently(self, tmp_path):
        gate = _gate(tmp_path)
        a = _propose(gate, "GLD")
        b = _propose(gate, "SLV")
        gate.decide(a.id, approved=True, by="alice")
        assert gate.is_approved(a.id) is True
        assert gate.is_approved(b.id) is False
        assert [p.id for p in gate.pending()] == [b.id]

    def test_executed_is_terminal_and_one_shot(self, tmp_path):
        gate = _gate(tmp_path)
        p = _propose(gate)
        gate.decide(p.id, approved=True, by="alice")
        gate.mark_executed(p.id)
        assert gate.get(p.id).status == "executed"
        assert gate.is_approved(p.id) is False  # cannot be replayed
        with pytest.raises(ValueError, match="not approved"):
            gate.mark_executed(p.id)

    def test_cannot_execute_unapproved(self, tmp_path):
        gate = _gate(tmp_path)
        p = _propose(gate)
        with pytest.raises(ValueError, match="not approved"):
            gate.mark_executed(p.id)

    def test_executed_survives_restart(self, tmp_path):
        path = tmp_path / "gate.jsonl"
        p = _propose(ApprovalGate(path))
        ApprovalGate(path).decide(p.id, approved=True, by="alice")
        ApprovalGate(path).mark_executed(p.id)
        assert ApprovalGate(path).get(p.id).status == "executed"


class TestApprovalCli:
    def test_approve_command(self, tmp_path):
        from typer.testing import CliRunner

        from arthaai.cli import app

        path = tmp_path / "gate.jsonl"
        p = _propose(ApprovalGate(path))
        result = CliRunner().invoke(app, ["approve", str(path), p.id, "--by", "alice"])
        assert result.exit_code == 0
        assert ApprovalGate(path).is_approved(p.id) is True

    def test_reject_command(self, tmp_path):
        from typer.testing import CliRunner

        from arthaai.cli import app

        path = tmp_path / "gate.jsonl"
        p = _propose(ApprovalGate(path))
        result = CliRunner().invoke(
            app, ["reject", str(path), p.id, "--by", "bob", "--reason", "no"]
        )
        assert result.exit_code == 0
        decided = ApprovalGate(path).get(p.id)
        assert decided.status == "rejected"
        assert decided.reason == "no"