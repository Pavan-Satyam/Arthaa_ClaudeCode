"""Configuration tests for market-data provider selection."""

import pytest

from arthaai.config import Settings


def test_market_data_provider_defaults_to_legacy_auto(monkeypatch):
    monkeypatch.delenv("ARTHAAI_MARKET_DATA_PROVIDER", raising=False)
    settings = Settings(_env_file=None)
    assert settings.market_data_provider == "auto"


def test_market_data_provider_environment_is_normalized(monkeypatch):
    monkeypatch.setenv("ARTHAAI_MARKET_DATA_PROVIDER", "  YFINANCE ")
    settings = Settings(_env_file=None)
    assert settings.market_data_provider == "yfinance"


def test_market_data_provider_rejects_blank_value():
    with pytest.raises(ValueError, match="must not be empty"):
        Settings(_env_file=None, market_data_provider="  ")