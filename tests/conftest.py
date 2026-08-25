"""Shared test fixtures — skip OPA network calls to eliminate 2s timeouts.

Every authorize_tool() call queries the OPA server (2s timeout when down).
In tests we always want the in-process ALLOWED map (the fail-safe fallback),
never the network round-trip. This conftest monkeypatches opa.is_allowed to
bypass the network entirely, making tests ~15s faster.
"""

from __future__ import annotations

import pytest

from arthaai.security import opa


@pytest.fixture(autouse=True)
def _skip_opa_network(monkeypatch):
    """Bypass OPA network calls — use the in-process ALLOWED map directly."""
    monkeypatch.setattr(
        "arthaai.security.opa.is_allowed",
        lambda agent, tool: tool in opa.ALLOWED.get(agent, set()),
    )
