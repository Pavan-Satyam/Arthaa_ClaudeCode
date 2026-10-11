"""FRED and DBnomics macroeconomic series adapters."""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, ClassVar

import pandas as pd


class MacroEconomicsEngine:
    """Fetch US FRED indicators and global DBnomics series as DataFrames."""

    FRED_SERIES: ClassVar[dict[str, str]] = {
        "10y_treasury_yield": "DGS10",
        "cpi_index": "CPIAUCSL",
        "unemployment_rate": "UNRATE",
    }

    def __init__(self, fred_reader: Any | None = None, dbnomics_reader: Any | None = None) -> None:
        self._fred_reader = fred_reader
        self._dbnomics_reader = dbnomics_reader

    def _read_fred(self, series_id: str, start, end) -> pd.DataFrame:
        if self._fred_reader is not None:
            return self._fred_reader(series_id, start, end)
        try:
            from pandas_datareader import data as web
        except ImportError as exc:
            raise RuntimeError(
                "FRED support requires `pip install -e '.[macro]'`."
            ) from exc
        kwargs = {}
        api_key = os.environ.get("FRED_API_KEY", "").strip()
        if api_key:
            kwargs["api_key"] = api_key
        return web.DataReader(series_id, "fred", start, end, **kwargs)

    def get_fred_series(
        self, series_id: str, start: str | date | datetime, end: str | date | datetime
    ) -> pd.DataFrame:
        """Fetch one FRED series in a canonical ``ts, value`` frame."""
        raw = self._read_fred(series_id, start, end)
        if raw.empty:
            return pd.DataFrame(columns=["ts", "value"])
        if series_id in raw.columns:
            values = raw[series_id]
        else:
            values = raw.iloc[:, 0]
        result = pd.DataFrame({"ts": pd.to_datetime(values.index, utc=True), "value": values.to_numpy()})
        return result.sort_values("ts").reset_index(drop=True)

    def get_fred_indicators(
        self, start: str | date | datetime, end: str | date | datetime
    ) -> pd.DataFrame:
        """Fetch Treasury, CPI, CPI year-over-year inflation, and unemployment."""
        series_frames = {
            name: self.get_fred_series(series_id, start, end).set_index("ts")["value"]
            for name, series_id in self.FRED_SERIES.items()
        }
        result = pd.concat(series_frames, axis=1).sort_index()
        result["cpi_yoy_pct"] = result["cpi_index"].pct_change(12, fill_method=None) * 100.0
        return result.reset_index(names="ts")

    def _read_dbnomics(self, provider: str, dataset: str, series: str) -> pd.DataFrame:
        if self._dbnomics_reader is not None:
            return self._dbnomics_reader(provider, dataset, series)
        try:
            import rdbnomics
        except ImportError as exc:
            raise RuntimeError("DBnomics support requires `pip install -e '.[macro]'`.") from exc
        return rdbnomics.get_series(provider, dataset, series)

    def get_global_series(
        self, provider: str, dataset: str, series: str
    ) -> pd.DataFrame:
        """Fetch an IMF, World Bank, or other DBnomics series as ``ts, value``."""
        raw = self._read_dbnomics(provider, dataset, series)
        frame = raw.copy() if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if frame.empty:
            return pd.DataFrame(columns=["ts", "value"])
        date_column = next(
            (column for column in ("period", "original_period", "date", "@frequency") if column in frame),
            None,
        )
        value_column = next(
            (column for column in ("value", "original_value") if column in frame), None
        )
        if date_column is None or value_column is None:
            raise ValueError("DBnomics response must contain period/date and value columns")
        result = pd.DataFrame(
            {
                "ts": pd.to_datetime(frame[date_column], utc=True, errors="coerce"),
                "value": pd.to_numeric(frame[value_column], errors="coerce"),
            }
        )
        return result.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)