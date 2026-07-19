"""Central, env-driven configuration (provider-abstracted)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # LLM
    llm_provider: Literal["anthropic", "bedrock"] = "anthropic"
    llm_model: str = "claude-sonnet-5"
    aws_region: str = "us-east-1"

    # Asset Manager risk policy (deterministic overrides)
    kelly_fraction: float = 0.25          # quarter-Kelly scaling
    max_single_instrument: float = 0.05   # hard cap per instrument
    risk_free_rate: float = 0.04

    @property
    def timescale_dsn(self) -> str:
        return (
            f"postgresql://{self.timescale_user}:{self.timescale_password}"
            f"@{self.timescale_host}:{self.timescale_port}/{self.timescale_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
