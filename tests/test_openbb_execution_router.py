"""Offline tests for OpenBB and research/paper execution boundaries."""

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from arthaai.data.openbb_router import OpenBBRouter
from arthaai.orchestration.execution_router import ArthaExecutionRouter


def test_openbb_router_calls_free_provider_and_returns_dataframe():
    calls = []

    def price_target(**kwargs):
        calls.append(("price_target", kwargs))
        return SimpleNamespace(to_df=lambda: pd.DataFrame({"target": [120.0]}))

    def sector_performance(**kwargs):
        calls.append(("sector_performance", kwargs))
        return pd.DataFrame({"sector": ["Technology"], "change": [0.02]})

    platform = SimpleNamespace(
        equity=SimpleNamespace(
            estimates=SimpleNamespace(price_target=price_target),
            sector=SimpleNamespace(performance=sector_performance),
        )
    )
    router = OpenBBRouter(platform=platform)

    targets = router.analyst_price_targets("aapl")
    sectors = router.sector_performance()

    assert targets.loc[0, "target"] == 120.0
    assert sectors.loc[0, "sector"] == "Technology"
    assert calls[0][1] == {"symbol": "AAPL", "provider": "yfinance"}
    assert calls[1][1] == {"provider": "yfinance"}


def test_local_llm_is_limited_to_text_tasks_and_policy_prompt():
    calls = {}

    def create(**kwargs):
        calls.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=json.dumps({"entities": ["AAPL"], "price": 123.0})
            ))]
        )

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    router = ArthaExecutionRouter(llm_client=client)
    result = router.analyze_text("Apple reported earnings.", task="entity_extraction")

    assert result["content"] == {"entities": ["AAPL"]}
    assert "Do not calculate" in calls["messages"][0]["content"]
    assert calls["temperature"] == 0
    with pytest.raises(ValueError, match="task must"):
        router.analyze_text("text", task="pricing")


def test_nautilus_factory_and_alpaca_paper_only_gate():
    config = object()
    calls = []

    class FakeEngine:
        def add_data(self, data):
            calls.append(("data", data))

        def add_strategy(self, strategy):
            calls.append(("strategy", strategy))

        def run(self):
            calls.append(("run", None))

    fake_engine = FakeEngine()
    router = ArthaExecutionRouter(nautilus_engine_factory=lambda received: fake_engine)
    strategy, historical_data = object(), [object()]
    assert router.create_nautilus_backtest_engine(config) is fake_engine
    assert router.run_nautilus_backtest(config, strategy, historical_data) is fake_engine
    assert calls == [
        ("data", historical_data[0]),
        ("strategy", strategy),
        ("run", None),
    ]

    with pytest.raises(RuntimeError, match="paper trading is disabled"):
        router.create_alpaca_paper_client("key", "secret")

    paper_calls = []
    paper_router = ArthaExecutionRouter(
        paper_trading_enabled=True,
        alpaca_client_factory=lambda key, secret, paper: paper_calls.append((key, secret, paper))
        or SimpleNamespace(submit_order=lambda **kwargs: ("paper-order", kwargs)),
    )
    assert paper_router.create_alpaca_paper_client("key", "secret") is not None
    assert paper_calls == [("key", "secret", True)]


def test_paper_order_submission_requires_explicit_paper_mode(monkeypatch):
    submitted = []
    router = ArthaExecutionRouter(
        paper_trading_enabled=True,
        alpaca_client_factory=lambda key, secret, paper: SimpleNamespace(
            submit_order=lambda **kwargs: submitted.append(kwargs) or "submitted"
        ),
    )
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    request = object()

    assert router.submit_paper_order(request) == "submitted"
    assert submitted == [{"order_data": request}]