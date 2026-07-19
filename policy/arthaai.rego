# ArthaAI zero-trust tool authorization (blueprint §6, Policy-as-Code).
# OPA evaluates this on every agent tool call. The platform — not the LLM —
# retains ultimate authority over what actions are permitted. Least privilege:
# the data agents have no path to execution tools.
package arthaai

# Immutable per-agent tool scope.
scopes := {
	"db_agent": {"sql_query", "load_ohlcv"},
	"quant_agent": {"load_ohlcv", "compute_stats"},
	"news_agent": {"hybrid_search"},
	"alt_agent": {"external_api"},
	"asset_manager": {"compute_stats", "kelly"},
	"master_llm": {"llm_complete"},
}

default allow := false

# allow when the requested tool is within the agent's declared scope.
allow {
	scopes[input.agent][input.tool]
}
