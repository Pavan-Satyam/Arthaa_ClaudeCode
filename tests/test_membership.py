"""Point-in-time universe membership (survivorship control)."""

from arthaai.data.membership import derive_membership, members_as_of


def test_derive_membership_from_coverage_skips_symbols_without_bars():
    coverage = [
        {"symbol": "gld", "first": "2016-10-14 00:00:00+00", "last": "2026-10-09 00:00:00+00", "bars": 3009},
        {"symbol": "IPO", "first": "2024-01-02 00:00:00+00", "last": "2026-10-09 00:00:00+00", "bars": 700},
        {"symbol": "SILVER", "bars": 0, "first": None, "last": None},
    ]
    windows = derive_membership(coverage)
    assert {w.symbol for w in windows} == {"GLD", "IPO"}
    assert all(w.source == "ohlcv_coverage" for w in windows)
    assert windows[0].valid_from == "2016-10-14"  # date-only normalization


def test_members_as_of_excludes_not_yet_listed_and_delisted():
    rows = [
        {"symbol": "GLD", "valid_from": "2016-10-14", "valid_to": "2026-10-09"},
        {"symbol": "IPO", "valid_from": "2024-01-02", "valid_to": "2026-10-09"},
        {"symbol": "DEAD", "valid_from": "2016-01-01", "valid_to": "2020-06-30"},
    ]
    assert members_as_of(rows, "2018-01-01") == ["DEAD", "GLD"]
    assert members_as_of(rows, "2022-01-01") == ["GLD"]
    assert members_as_of(rows, "2025-01-01") == ["GLD", "IPO"]
    assert members_as_of(rows, "2026-10-09") == ["GLD", "IPO"]


def test_members_as_of_asset_class_filter():
    rows = [
        {"symbol": "GLD", "asset_class": "commodity_etf", "valid_from": "2016-01-01", "valid_to": None},
        {"symbol": "AAPL", "asset_class": "equity", "valid_from": "2016-01-01", "valid_to": None},
    ]
    assert members_as_of(rows, "2020-01-01", asset_class="equity") == ["AAPL"]


def test_open_window_covers_all_future_dates():
    rows = [{"symbol": "NEW", "valid_from": "2020-01-01", "valid_to": None}]
    assert members_as_of(rows, "2099-01-01") == ["NEW"]
