"""Research-first integrations for local LLMs, Nautilus, and Alpaca paper mode."""

from __future__ import annotations

import json
import os
from typing import Any, Literal, TypedDict


class LocalAnalysisResult(TypedDict):
    task: str
    content: dict[str, Any]


class ArthaExecutionRouter:
    """Keep LLM use narrow and execution integrations explicitly non-live."""

    SYSTEM_PROMPT = (
        "You are ArthaAI's text-analysis component. You may only perform the "
        "requested entity extraction or sentiment scoring. Do not calculate, "
        "estimate, or invent prices, returns, probabilities, financial ratios, "
        "position sizes, or trade decisions. All numeric financial analysis is "
        "computed by deterministic code. Return only valid JSON matching the "
        "requested output schema."
    )

    def __init__(
        self,
        *,
        llm_client: Any | None = None,
        paper_trading_enabled: bool = False,
        alpaca_client_factory: Any | None = None,
        nautilus_engine_factory: Any | None = None,
    ) -> None:
        self._llm_client = llm_client
        self.paper_trading_enabled = paper_trading_enabled
        self._alpaca_client_factory = alpaca_client_factory
        self._nautilus_engine_factory = nautilus_engine_factory

    def _local_llm_client(self, base_url: str | None = None):
        if self._llm_client is not None:
            return self._llm_client
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Local LLM support requires `pip install -e '.[execution]'`.") from exc
        url = base_url or os.environ.get("ARTHAAI_LOCAL_LLM_URL", "http://localhost:11434/v1")
        self._llm_client = OpenAI(base_url=url, api_key=os.environ.get("ARTHAAI_LOCAL_LLM_API_KEY", "ollama"))
        return self._llm_client

    def analyze_text(
        self,
        text: str,
        *,
        task: Literal["entity_extraction", "sentiment_scoring"],
        model: str | None = None,
        base_url: str | None = None,
    ) -> LocalAnalysisResult:
        """Use a local OpenAI-compatible LLM only for extraction/sentiment JSON."""
        if not text.strip():
            raise ValueError("text must not be empty")
        if task not in ("entity_extraction", "sentiment_scoring"):
            raise ValueError("task must be entity_extraction or sentiment_scoring")
        client = self._local_llm_client(base_url)
        response = client.chat.completions.create(
            model=model or os.environ.get("ARTHAAI_LOCAL_LLM_MODEL", "qwen2.5:7b"),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Task: {task}. Analyze the following text only:\n{text[:20_000]}",
                },
            ],
        )
        content = response.choices[0].message.content or "{}"
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("local LLM response was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise TypeError("local LLM must return a JSON object")
        if task == "entity_extraction":
            entities = parsed.get("entities")
            if not isinstance(entities, list) or not all(isinstance(item, str) for item in entities):
                raise ValueError("entity extraction response must contain an entities string list")
            parsed = {"entities": entities}
        else:
            label = parsed.get("label")
            score = parsed.get("score")
            if label not in ("positive", "negative", "neutral"):
                raise ValueError("sentiment response label must be positive, negative, or neutral")
            if not isinstance(score, (int, float)) or not 0.0 <= float(score) <= 1.0:
                raise ValueError("sentiment response score must be between 0 and 1")
            parsed = {"label": label, "score": float(score)}
        return LocalAnalysisResult(task=task, content=parsed)

    def create_nautilus_backtest_engine(self, config: Any):
        """Create a Nautilus BacktestEngine; strategy/data remain caller-owned.

        The project-specific strategy is passed unchanged to the engine by the
        caller so research and paper integrations can share the same strategy
        class rather than translating notebook logic.
        """
        if self._nautilus_engine_factory is not None:
            return self._nautilus_engine_factory(config)
        try:
            from nautilus_trader.backtest.engine import BacktestEngine
        except ImportError as exc:
            raise RuntimeError("Nautilus support requires `pip install -e '.[execution]'`.") from exc
        return BacktestEngine(config=config)

    def run_nautilus_backtest(self, config: Any, strategy: Any, data: list[Any] | None = None):
        """Run a supplied Nautilus strategy class/instance on historical data.

        ``strategy`` must be a Nautilus Strategy instance. The exact same
        strategy instance can be supplied by the project's paper adapter after
        data and venue configuration are explicitly set up.
        """
        engine = self.create_nautilus_backtest_engine(config)
        for item in data or []:
            engine.add_data(item)
        engine.add_strategy(strategy)
        engine.run()
        return engine

    def create_alpaca_paper_client(self, api_key: str | None = None, secret_key: str | None = None):
        """Construct an Alpaca client forced to paper mode; never enables live routing."""
        if not self.paper_trading_enabled:
            raise RuntimeError("paper trading is disabled until the research phase is approved")
        key = api_key or os.environ.get("ALPACA_API_KEY", "").strip()
        secret = secret_key or os.environ.get("ALPACA_SECRET_KEY", "").strip()
        if not key or not secret:
            raise RuntimeError("Set ALPACA_API_KEY and ALPACA_SECRET_KEY for paper trading")
        if self._alpaca_client_factory is not None:
            return self._alpaca_client_factory(key, secret, paper=True)
        try:
            from alpaca.trading.client import TradingClient
        except ImportError as exc:
            raise RuntimeError("Alpaca paper support requires `pip install -e '.[execution]'`.") from exc
        return TradingClient(key, secret, paper=True)

    def submit_paper_order(self, order_request: Any):
        """Submit an order request to Alpaca paper trading only."""
        client = self.create_alpaca_paper_client()
        return client.submit_order(order_data=order_request)