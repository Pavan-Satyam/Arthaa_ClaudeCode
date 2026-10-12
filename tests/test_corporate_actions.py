"""Corporate-action capture and gap-audit consistency scan."""

import pandas as pd

from arthaai.data.corporate_actions import (
    CorporateAction,
    fetch_corporate_actions,
    scan_unexplained_gaps,
    unexplained_gaps,
)


class _FakeTicker:
    def __init__(self, splits, dividends):
        self.splits = splits
        self.dividends = dividends


def _bars(closes, start="2024-01-01"):
    ts = pd.date_range(start, periods=len(closes), freq="B", tz="UTC")
    return pd.DataFrame({"ts": ts, "close": closes})


def test_fetch_corporate_actions_maps_splits_and_dividends():
    splits = pd.Series([2.0], index=pd.to_datetime(["2020-08-31"]))
    dividends = pd.Series([0.25], index=pd.to_datetime(["2020-02-07"]))
    actions = fetch_corporate_actions(
        "aapl", ticker_factory=lambda sym: _FakeTicker(splits, dividends)
    )
    assert [(a.action_type, a.ex_date) for a in actions] == [
        ("dividend", "2020-02-07"),
        ("split", "2020-08-31"),
    ]
    assert actions[1].ratio == 2.0
    assert actions[0].amount == 0.25
    assert all(a.symbol == "AAPL" for a in actions)


def test_fetch_corporate_actions_handles_no_actions():
    empty = pd.Series(dtype=float)
    actions = fetch_corporate_actions("gld", ticker_factory=lambda sym: _FakeTicker(empty, empty))
    assert actions == []


def test_scan_flags_large_gap_as_unexplained():
    bars = _bars([100, 101, 102, 60, 61])  # ~-41% overnight gap at index 3
    findings = scan_unexplained_gaps(bars, [], threshold=0.15)
    assert len(findings) == 1
    assert findings[0]["explained"] is False
    assert unexplained_gaps(findings) == findings


def test_scan_explains_gap_near_action():
    bars = _bars([100, 101, 102, 60, 61])
    action_date = bars["ts"].iloc[3].strftime("%Y-%m-%d")
    actions = [CorporateAction("X", action_date, "split", 0.5, None, None, "test")]
    findings = scan_unexplained_gaps(bars, actions, threshold=0.15, window_days=2)
    assert findings and findings[0]["explained"] is True
    assert unexplained_gaps(findings) == []


def test_scan_ignores_small_moves():
    assert scan_unexplained_gaps(_bars([100, 101, 102, 103]), [], threshold=0.15) == []


def test_scan_empty_or_short_is_safe():
    assert scan_unexplained_gaps(pd.DataFrame({"ts": [], "close": []}), []) == []
    assert scan_unexplained_gaps(_bars([100]), []) == []
