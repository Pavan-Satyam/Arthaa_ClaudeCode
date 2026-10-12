"""Stub/synthetic alt data must not drive the offline verdict (ARTHA-213a)."""

from arthaai.agents.master_llm import _offline, _weighted_score

_BASE = {"db": {"available": True, "trend_score": 0.0, "trend": "neutral"}}


def test_stub_alt_is_not_weighted():
    with_stub = {**_BASE, "alt": {"available": True, "physical_score": 0.4, "stub": True}}
    assert _weighted_score(with_stub)[0] == _weighted_score(_BASE)[0]


def test_real_alt_is_weighted():
    with_real = {**_BASE, "alt": {"available": True, "physical_score": 0.4}}
    assert _weighted_score(with_real)[0] > _weighted_score(_BASE)[0]


def test_stub_alt_does_not_flip_verdict():
    with_stub = {**_BASE, "alt": {"available": True, "physical_score": 0.4, "stub": True}}
    assert _offline(with_stub, "GLD").direction == _offline(_BASE, "GLD").direction


def test_stub_alt_is_noted_but_unweighted():
    with_stub = {**_BASE, "alt": {"available": True, "physical_score": 0.4, "stub": True}}
    _, notes = _weighted_score(with_stub)
    assert any("stubbed" in note for note in notes)
