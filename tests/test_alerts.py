"""Operational alert ring buffer (ARTHA-5)."""

from arthaai.observability import alerts


def test_alert_records_and_recent_orders_newest_first():
    alerts._RECENT.clear()
    alerts.alert("breaker", "tripped", symbol="GLD")
    alerts.alert("llm", "fallback")
    recent = alerts.recent(5)
    assert [entry["kind"] for entry in recent] == ["llm", "breaker"]
    assert recent[0]["message"] == "fallback"
    assert recent[1]["fields"] == {"symbol": "GLD"}


def test_recent_limit_and_floor():
    alerts._RECENT.clear()
    for index in range(5):
        alerts.alert("k", f"m{index}")
    assert len(alerts.recent(2)) == 2
    assert alerts.recent(0) == []
