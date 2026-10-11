"""OpenBB Platform adapter for replaceable free/paid data extensions."""

from __future__ import annotations

from typing import Any

import pandas as pd


class OpenBBRouter:
    """Route data requests through OpenBB without leaking its result types."""

    def __init__(self, platform: Any | None = None, provider: str = "yfinance") -> None:
        self._platform = platform
        self.provider = provider

    @property
    def platform(self):
        if self._platform is None:
            try:
                from openbb import obb
            except ImportError as exc:
                raise RuntimeError("OpenBB support requires `pip install -e '.[openbb]'`.") from exc
            self._platform = obb
        return self._platform

    @staticmethod
    def _to_frame(result: Any) -> pd.DataFrame:
        if isinstance(result, pd.DataFrame):
            return result.copy()
        for method_name in ("to_df", "to_dataframe"):
            method = getattr(result, method_name, None)
            if callable(method):
                frame = method()
                if isinstance(frame, pd.DataFrame):
                    return frame
        results = getattr(result, "results", None)
        if results is not None:
            return pd.DataFrame(results)
        return pd.DataFrame(result)

    def _endpoint(self, path: str):
        endpoint = self.platform
        for component in path.split("."):
            endpoint = getattr(endpoint, component)
        if not callable(endpoint):
            raise TypeError(f"OpenBB endpoint '{path}' is not callable")
        return endpoint

    def analyst_price_targets(self, ticker: str) -> pd.DataFrame:
        """Get analyst price targets (example free route: Yahoo Finance)."""
        result = self._endpoint("equity.estimates.price_target")(
            symbol=ticker.upper(), provider=self.provider
        )
        return self._to_frame(result)

    def sector_performance(self) -> pd.DataFrame:
        """Get sector performance data from the configured OpenBB extension."""
        result = self._endpoint("equity.sector.performance")(provider=self.provider)
        return self._to_frame(result)

    def query(self, endpoint: str, **parameters) -> pd.DataFrame:
        """Call another dotted OpenBB endpoint and return a Pandas DataFrame."""
        parameters.setdefault("provider", self.provider)
        return self._to_frame(self._endpoint(endpoint)(**parameters))