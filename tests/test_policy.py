"""Zero-trust policy seam (least-privilege tool scopes)."""

import pytest

from arthaai.security import AgentIdentity, authorize_tool
from arthaai.security.policy import PolicyViolation


def test_db_agent_allowed_its_tool():
    authorize_tool(AgentIdentity("db_agent", "spiffe://arthaai/agent/db_agent"), "load_ohlcv")


def test_db_agent_denied_execution_path():
    # Least privilege: the data agent has no path to execution tools.
    with pytest.raises(PolicyViolation):
        authorize_tool(AgentIdentity("db_agent", "spiffe://arthaai/agent/db_agent"), "external_api")


def test_unknown_agent_denied():
    with pytest.raises(PolicyViolation):
        authorize_tool(AgentIdentity("rogue", "spiffe://arthaai/agent/rogue"), "kelly")
