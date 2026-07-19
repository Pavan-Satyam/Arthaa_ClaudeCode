"""ArthaAI — zero-trust multi-agent LLM framework for financial-market analysis.

Blueprint implementation. Tiers:
  1. Client & Interface  (gateway/)
  2. Orchestration        (orchestration/) + worker agents (agents/) + persistence (db/)
  3. Oversight & Asset Mgmt (agents/asset_manager.py)
  4. Execution            (stubbed — guarded trade execution)

The deterministic quant layer (db/, agents/db_agent, quant_agent, asset_manager)
produces the numbers; the Master Reasoning LLM only synthesises and explains them.
"""

__version__ = "0.1.0"
