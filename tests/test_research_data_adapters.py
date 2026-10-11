"""Offline tests for SEC and macro data adapters."""

from types import SimpleNamespace

import pandas as pd
import pytest

from arthaai.data import news_sentiment
from arthaai.data.alternative import AlternativeAssetFetcher
from arthaai.data.fundamentals import SECDataProcessor
from arthaai.data.macro import MacroEconomicsEngine
from arthaai.data.news_sentiment import NewsSentimentAnalyzer


def test_sec_processor_normalizes_latest_10k_and_form4_rows():
    income = pd.DataFrame({"Revenue": [100.0], "Net Income": [12.0]})
    transaction = SimpleNamespace(
        transaction_date="2025-02-01",
        security_title="Common Stock",
        transaction_code="P",
        transaction_shares=100,
        transaction_price=25.0,
        acquired_disposed="A",
    )
    filing_10k = SimpleNamespace(
        xbrl=lambda: SimpleNamespace(
            statements=SimpleNamespace(income_statement=lambda: income)
        )
    )
    filing_form4 = SimpleNamespace(
        filing_date="2025-02-03",
        obj=lambda: SimpleNamespace(
            reporting_owner="Example Insider",
            transactions=pd.DataFrame([{
                "transaction_date": transaction.transaction_date,
                "security_title": transaction.security_title,
                "transaction_code": transaction.transaction_code,
                "transaction_shares": transaction.transaction_shares,
                "transaction_price": transaction.transaction_price,
                "acquired_disposed": transaction.acquired_disposed,
            }]),
        ),
    )

    class Company:
        def get_filings(self, form):
            return [filing_10k] if form == "10-K" else [filing_form4]

    processor = SECDataProcessor(company_factory=lambda ticker: Company())
    financials = processor.get_10k_financials("aapl")
    trades = processor.get_insider_trades("aapl")

    assert financials.equals(income)
    assert trades.loc[0, "ticker"] == "AAPL"
    assert trades.loc[0, "insider"] == "Example Insider"
    assert trades.loc[0, "transaction_code"] == "P"
    assert trades.loc[0, "shares"] == 100


def test_macro_engine_normalizes_fred_and_computes_cpi_yoy():
    dates = pd.date_range("2024-01-01", periods=13, freq="MS")

    def fred_reader(series_id, start, end):
        values = range(100, 113) if series_id == "CPIAUCSL" else range(13)
        return pd.DataFrame({series_id: values}, index=dates)

    engine = MacroEconomicsEngine(fred_reader=fred_reader)
    series = engine.get_fred_series("DGS10", "2024-01-01", "2025-02-01")
    indicators = engine.get_fred_indicators("2024-01-01", "2025-02-01")

    assert list(series.columns) == ["ts", "value"]
    assert series.loc[0, "ts"] == pd.Timestamp("2024-01-01", tz="UTC")
    assert indicators.loc[12, "cpi_yoy_pct"] == pytest.approx(12.0)
    assert indicators.loc[12, "10y_treasury_yield"] == 12


def test_dbnomics_series_uses_period_and_value_fields():
    engine = MacroEconomicsEngine(
        dbnomics_reader=lambda provider, dataset, series: pd.DataFrame(
            {"period": ["2025-02", "2025-01"], "value": [2.5, 2.0]}
        )
    )
    result = engine.get_global_series("IMF", "IFS", "CPI")

    assert list(result.columns) == ["ts", "value"]
    assert result["value"].tolist() == [2.0, 2.5]
    assert result.iloc[0]["ts"] == pd.Timestamp("2025-01-01", tz="UTC")


def test_news_ingestion_and_finbert_result_are_structured(monkeypatch):
    response = SimpleNamespace(content=b"rss", raise_for_status=lambda: None)
    monkeypatch.setattr(news_sentiment, "is_allowed_feed_url", lambda url: True)
    monkeypatch.setattr(news_sentiment.httpx, "get", lambda *args, **kwargs: response)
    monkeypatch.setitem(
        __import__("sys").modules,
        "feedparser",
        SimpleNamespace(
            parse=lambda content: SimpleNamespace(
                entries=[{
                    "title": "Earnings beat",
                    "link": "https://example.com/story",
                    "published": "2025-01-01",
                    "summary": "Revenue increased",
                }]
            )
        ),
    )
    analyzer = NewsSentimentAnalyzer(
        classifier=lambda text, truncation: [
            {"label": "positive", "score": 0.9},
            {"label": "negative", "score": 0.05},
            {"label": "neutral", "score": 0.05},
        ]
    )

    articles = analyzer.fetch_rss({"wire": "https://feed.example.com/rss"})
    sentiment = analyzer.score_sentiment("Revenue increased and guidance improved.")

    assert articles[0]["source"] == "wire"
    assert articles[0]["url"] == "https://example.com/story"
    assert sentiment["label"] == "Positive"
    assert sentiment["score"] == 0.9
    assert "pr_news_wire" in NewsSentimentAnalyzer.DEFAULT_FEEDS
    assert "yahoo_finance" in NewsSentimentAnalyzer.DEFAULT_FEEDS


def test_alternative_fetcher_normalizes_eia_and_ecb_series():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": {"data": [
                {"period": "2025-02-07", "value": "420.5", "area-name": "U.S."},
                {"period": "2025-01-31", "value": "419.0", "area-name": "U.S."},
            ]}}

    class HttpClient:
        def get(self, url, **kwargs):
            assert url.endswith("/petroleum/stoc/wstk/data/")
            return Response()

    fetcher = AlternativeAssetFetcher(
        eia_api_key="test-key",
        http_client=HttpClient(),
        fx_reader=lambda series, source, start, end: pd.DataFrame(
            {series: [1.02, 1.03]}, index=pd.date_range("2025-01-01", periods=2)
        ),
    )
    inventory = fetcher.get_crude_oil_inventory()
    fx = fetcher.get_ecb_fx_rates("D.USD.EUR.SP00.A", "2025-01-01", "2025-02-01")

    assert inventory["value"].tolist() == [419.0, 420.5]
    assert "area-name" in inventory.columns
    assert list(fx.columns) == ["ts", "rate"]
    assert fx["rate"].tolist() == [1.02, 1.03]


def test_satellite_fetcher_queries_sentinel_metadata_only():
    item = SimpleNamespace(
        id="scene-1",
        datetime=pd.Timestamp("2025-01-01", tz="UTC"),
        properties={"eo:cloud_cover": 4.2},
        bbox=[-1.0, 50.0, 0.0, 51.0],
        collection_id="sentinel-2-l2a",
    )

    class Search:
        def items(self):
            return iter([item])

    class StacClient:
        def search(self, **kwargs):
            assert kwargs["collections"] == ["sentinel-2-l2a"]
            assert kwargs["bbox"] == [-1.0, 50.0, 0.0, 51.0]
            return Search()

    fetcher = AlternativeAssetFetcher(stac_client=StacClient())
    result = fetcher.get_satellite_crop_index(
        (-1.0, 50.0, 0.0, 51.0), start="2025-01-01", end="2025-01-31"
    )

    assert result.loc[0, "id"] == "scene-1"
    assert result.loc[0, "cloud_cover"] == 4.2