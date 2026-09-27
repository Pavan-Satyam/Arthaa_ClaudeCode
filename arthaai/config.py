"""Central, env-driven configuration (provider-abstracted)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env into the process environment so unprefixed secrets used by third-party
# SDKs and Vault fallbacks (ANTHROPIC_API_KEY, GEMINI_API_KEY, ...) are available.
# pydantic-settings only reads ARTHAAI_-prefixed vars, so this fills the gap.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARTHAAI_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # TimescaleDB
    timescale_host: str = "localhost"
    timescale_port: int = 5432
    timescale_db: str = "arthaai"
    timescale_user: str = "arthaai"
    timescale_password: str = "arthaai_dev_pw"

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    news_collection: str = "news_sentiment"

    # Kafka / Redpanda
    kafka_bootstrap: str = "localhost:9092"
    ingest_topic: str = "arthaai.ingest.ticks"

    # Zero-trust infra
    opa_url: str = "http://localhost:8181"
    vault_addr: str = "http://localhost:8200"
    vault_token: str = "arthaai-root"          # dev-mode root token (see docker-compose)

    # LLM — primary provider + optional fallback chain.
    # Providers: anthropic (Claude) | gemini (Google) | local (OpenAI-compatible
    # endpoint: Ollama / LM Studio / vLLM) | offline (deterministic reasoner).
    llm_provider: Literal["anthropic", "gemini", "local"] = "anthropic"
    # Explicit ordered chain, e.g. "gemini,local,offline". Empty -> [provider, offline].
    llm_chain: str = ""
    llm_model: str = "claude-sonnet-5"       # anthropic model
    gemini_model: str = "gemini-2.5-flash"
    local_base_url: str = "http://localhost:11434/v1"   # Ollama's OpenAI-compatible API
    local_model: str = "llama3.1"

    @property
    def llm_chain_list(self) -> list[str]:
        """Resolved provider order, always ending at the offline fallback."""
        if self.llm_chain.strip():
            chain = [p.strip() for p in self.llm_chain.split(",") if p.strip()]
        else:
            chain = [self.llm_provider]
        if "offline" not in chain:
            chain.append("offline")
        return chain

    # Asset Manager risk policy (deterministic overrides)
    kelly_fraction: float = 0.25          # quarter-Kelly scaling
    max_single_instrument: float = 0.05   # hard cap per instrument
    risk_free_rate: float = 0.04

    # Alpha-Zoo factor gate (E2): lets the deterministic factor signal DAMPEN a
    # long when it disagrees with the signal-conditioned Kelly edge. It can only
    # reduce exposure (never amplify) and never overrides the policy cap. Disable
    # with ARTHAAI_FACTOR_GATE=false.
    factor_gate: bool = True
    factor_dampening: float = 0.5   # multiplier when the factor signal conflicts
    factor_epsilon: float = 0.0     # |signal| <= epsilon is treated as neutral

    # Volatility targeting (C): scale exposure toward an annualised target vol.
    # 0 disables it. Default only de-risks (max leverage 1.0); raise
    # vol_max_leverage to allow leverage when realised vol is below target.
    vol_target: float = 0.0
    vol_max_leverage: float = 1.0

    # Gateway security
    dev_mode: bool = True                # False in production: enforce TLS cookies, reject dev-token fallback

    # OAuth 2.1 / MCP access-token validation (ARTHA-107/108). When oauth_jwks_url
    # is set, bearer tokens are validated as JWTs (signature + exp + iss + aud)
    # against the IdP's JWKS; otherwise a static ARTHAAI_GATEWAY_TOKEN is used.
    oauth_jwks_url: str = ""
    oauth_issuer: str = ""
    oauth_audience: str = ""
    oauth_algorithms: str = "RS256"      # comma-separated, e.g. "RS256,ES256"

    # CORS (ARTHA-509): comma-separated allowed origins. Empty = same-origin only.
    cors_origins: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # London Strategic Edge — free market-data API (https://londonstrategicedge.com)
    # Key is in the unprefixed LSE_API_KEY env var (loaded by load_dotenv above).
    @property
    def lse_api_key(self) -> str | None:
        import os
        return os.environ.get("LSE_API_KEY") or None

    @property
    def lse_base_url(self) -> str:
        return "https://api.londonstrategicedge.com"

    @property
    def timescale_dsn(self) -> str:
        return (
            f"postgresql://{self.timescale_user}:{self.timescale_password}"
            f"@{self.timescale_host}:{self.timescale_port}/{self.timescale_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
