"""Alternative asset, FX, options, and satellite metadata adapters."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Any, TypedDict

import httpx
import pandas as pd


class OptionGreeks(TypedDict):
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    option_type: str


class AlternativeAssetFetcher:
    """Fetch selected public alternative data and calculate option Greeks."""

    EIA_BASE_URL = "https://api.eia.gov/v2"
    STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

    def __init__(
        self,
        *,
        eia_api_key: str | None = None,
        http_client: Any | None = None,
        fx_reader: Any | None = None,
        stac_client: Any | None = None,
    ) -> None:
        self._eia_api_key = eia_api_key or os.environ.get("EIA_API_KEY", "").strip()
        self._http = http_client or httpx
        self._fx_reader = fx_reader
        self._stac_client = stac_client

    def get_eia_series(
        self,
        route: str,
        *,
        start: str | None = None,
        end: str | None = None,
        facets: dict[str, list[str]] | None = None,
        length: int = 5000,
    ) -> pd.DataFrame:
        """Fetch one EIA v2 data route and normalize its period/value columns."""
        if not self._eia_api_key:
            raise RuntimeError("Set EIA_API_KEY to query the EIA Open Data API.")
        params: dict[str, Any] = {
            "api_key": self._eia_api_key,
            "frequency": "weekly",
            "data[0]": "value",
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "length": length,
        }
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        for name, values in (facets or {}).items():
            params[f"facets[{name}][]"] = values
        response = self._http.get(f"{self.EIA_BASE_URL}/{route.strip('/')}/data/", params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        records = payload.get("response", {}).get("data", [])
        if not records:
            return pd.DataFrame(columns=["ts", "value"])
        frame = pd.DataFrame(records)
        if "period" not in frame or "value" not in frame:
            raise ValueError("EIA response does not contain period and value fields")
        frame["ts"] = pd.to_datetime(frame.pop("period"), utc=True, errors="coerce")
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        return frame.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)

    def get_crude_oil_inventory(self, **kwargs) -> pd.DataFrame:
        """Fetch weekly US crude oil stocks from the EIA petroleum endpoint."""
        return self.get_eia_series(
            "petroleum/stoc/wstk",
            facets={"duoarea": ["NUS"], "product": ["EPC0"], "process": ["SAE"]},
            **kwargs,
        )

    def get_natural_gas_inventory(self, **kwargs) -> pd.DataFrame:
        """Fetch weekly US working natural-gas storage from the EIA endpoint."""
        return self.get_eia_series(
            "natural-gas/stor/wkly",
            facets={"duoarea": ["NUS"], "process": ["R48"]},
            **kwargs,
        )

    def get_ecb_fx_rates(
        self,
        series: str,
        start: str | date | datetime,
        end: str | date | datetime,
    ) -> pd.DataFrame:
        """Fetch an ECB SDMX series via pandas-datareader as ``ts, rate``."""
        if self._fx_reader is None:
            try:
                from pandas_datareader import data as web
            except ImportError as exc:
                raise RuntimeError("ECB FX support requires `pip install -e '.[macro]'`.") from exc
            reader = web.DataReader
        else:
            reader = self._fx_reader
        raw = reader(series, "ecb", start, end)
        if raw.empty:
            return pd.DataFrame(columns=["ts", "rate"])
        result = pd.DataFrame(
            {"ts": pd.to_datetime(raw.index, utc=True), "rate": raw.iloc[:, 0].to_numpy()}
        )
        return result.sort_values("ts").reset_index(drop=True)

    @staticmethod
    def black_scholes_greeks(
        spot: float,
        strike: float,
        expiry: date,
        volatility: float,
        risk_free_rate: float,
        *,
        dividend_yield: float = 0.0,
        option_type: str = "call",
    ) -> OptionGreeks:
        """Price a European option and calculate Greeks using QuantLib."""
        if spot <= 0 or strike <= 0 or volatility <= 0:
            raise ValueError("spot, strike, and volatility must be positive")
        if expiry <= datetime.now(tz=UTC).date():
            raise ValueError("expiry must be a future date")
        normalized_type = option_type.lower()
        if normalized_type not in ("call", "put"):
            raise ValueError("option_type must be 'call' or 'put'")
        try:
            import QuantLib as ql
        except ImportError as exc:
            raise RuntimeError("Options pricing requires `pip install -e '.[alternatives]'`.") from exc

        evaluation_date = ql.Date.todaysDate()
        prior_evaluation_date = ql.Settings.instance().evaluationDate
        maturity = ql.Date(expiry.day, expiry.month, expiry.year)
        day_count = ql.Actual365Fixed()
        calendar = ql.NullCalendar()
        ql.Settings.instance().evaluationDate = evaluation_date
        try:
            spot_handle = ql.QuoteHandle(ql.SimpleQuote(float(spot)))
            rate_curve = ql.YieldTermStructureHandle(
                ql.FlatForward(evaluation_date, float(risk_free_rate), day_count)
            )
            dividend_curve = ql.YieldTermStructureHandle(
                ql.FlatForward(evaluation_date, float(dividend_yield), day_count)
            )
            volatility_curve = ql.BlackVolTermStructureHandle(
                ql.BlackConstantVol(evaluation_date, calendar, float(volatility), day_count)
            )
            process = ql.BlackScholesMertonProcess(
                spot_handle, dividend_curve, rate_curve, volatility_curve
            )
            ql_option = ql.Option.Call if normalized_type == "call" else ql.Option.Put
            option = ql.EuropeanOption(
                ql.PlainVanillaPayoff(ql_option, float(strike)), ql.EuropeanExercise(maturity)
            )
            option.setPricingEngine(ql.AnalyticEuropeanEngine(process))
            return OptionGreeks(
                price=float(option.NPV()),
                delta=float(option.delta()),
                gamma=float(option.gamma()),
                theta=float(option.theta()),
                vega=float(option.vega()),
                option_type=normalized_type,
            )
        finally:
            ql.Settings.instance().evaluationDate = prior_evaluation_date

    def get_satellite_crop_index(
        self,
        region_box: tuple[float, float, float, float],
        *,
        start: str,
        end: str,
        limit: int = 100,
    ) -> pd.DataFrame:
        """Return Sentinel-2 scene metadata for a bbox; imagery is not downloaded."""
        if len(region_box) != 4 or region_box[0] >= region_box[2] or region_box[1] >= region_box[3]:
            raise ValueError("region_box must be (min_lon, min_lat, max_lon, max_lat)")
        client = self._stac_client
        if client is None:
            try:
                import planetary_computer
                from pystac_client import Client
            except ImportError as exc:
                raise RuntimeError(
                    "Satellite metadata requires `pip install -e '.[alternatives]'`."
                ) from exc
            client = Client.open(self.STAC_URL, modifier=planetary_computer.sign_inplace)
        search = client.search(
            collections=["sentinel-2-l2a"],
            bbox=list(region_box),
            datetime=f"{start}/{end}",
            max_items=limit,
        )
        rows = []
        for item in search.items():
            rows.append(
                {
                    "id": item.id,
                    "datetime": item.datetime,
                    "cloud_cover": item.properties.get("eo:cloud_cover"),
                    "bbox": item.bbox,
                    "collection": item.collection_id,
                }
            )
        return pd.DataFrame(rows, columns=["id", "datetime", "cloud_cover", "bbox", "collection"])