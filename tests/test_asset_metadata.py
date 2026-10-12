"""Asset metadata enrichment (exchange/asset-class normalization)."""

from arthaai.data.metadata import fetch_asset_metadata, normalize_exchange


def test_normalize_exchange_prefers_full_name():
    assert normalize_exchange("NMS", "NasdaqGS") == "NASDAQ"
    assert normalize_exchange("PCX", "NYSEArca") == "NYSEARCA"
    assert normalize_exchange("NYQ", "NYSE") == "NYSE"
    assert normalize_exchange("ASE", "NYSE American") == "NYSEAMERICAN"
    assert normalize_exchange("BTS", "Cboe BZX") == "BATS"


def test_normalize_exchange_falls_back_to_code():
    assert normalize_exchange("NMS") == "NASDAQ"
    assert normalize_exchange("PCX") == "NYSEARCA"
    assert normalize_exchange("NYQ") == "NYSE"
    assert normalize_exchange(None) is None
    assert normalize_exchange("") is None


def test_fetch_asset_metadata_maps_etf():
    info = {
        "shortName": "SPDR Gold Shares",
        "quoteType": "ETF",
        "exchange": "PCX",
        "fullExchangeName": "NYSEArca",
        "currency": "USD",
    }
    meta = fetch_asset_metadata("gld", info_factory=lambda s: info)
    assert meta["symbol"] == "GLD"
    assert meta["asset_class"] == "etf"
    assert meta["exchange"] == "NYSEARCA"
    assert meta["name"] == "SPDR Gold Shares"


def test_fetch_asset_metadata_equity_defaults():
    info = {"longName": "Apple Inc.", "quoteType": "EQUITY", "exchange": "NMS"}
    meta = fetch_asset_metadata("AAPL", info_factory=lambda s: info)
    assert meta["asset_class"] == "equity"
    assert meta["exchange"] == "NASDAQ"
    assert meta["currency"] == "USD"


def test_fetch_asset_metadata_empty_info_is_safe():
    meta = fetch_asset_metadata("ZZZZ", info_factory=lambda s: {})
    assert meta["name"] == "ZZZZ"
    assert meta["asset_class"] == "equity"
    assert meta["exchange"] is None
