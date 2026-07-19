"""Master LLM — verdict parsing and provider fallback chain."""

from arthaai.agents import master_llm as m
from arthaai.config import get_settings


def test_parse_fenced_json_and_clamp_confidence():
    txt = '```json\n{"direction":"bullish","confidence":1.7,"rationale":"x. I choose this because y"}\n```'
    v = m._parse_verdict(txt, "gemini")
    assert v.direction == "bullish"
    assert v.confidence == 1.0          # clamped to [0,1]
    assert v.source == "gemini"


def test_parse_bad_direction_defaults_neutral():
    v = m._parse_verdict('{"direction":"to-the-moon","confidence":0.3,"rationale":"z"}', "local")
    assert v.direction == "neutral"


def test_parse_extracts_json_from_surrounding_text():
    # open models often add prose around the JSON
    txt = 'Sure! Here is the analysis:\n{"direction":"bearish","confidence":0.6,"rationale":"r"} Hope this helps.'
    v = m._parse_verdict(txt, "local:llama3.1")
    assert v.direction == "bearish" and v.confidence == 0.6


def test_chain_falls_through_to_offline(monkeypatch):
    # gemini + local both unreachable/unkeyed -> deterministic offline verdict.
    monkeypatch.setenv("ARTHAAI_LLM_CHAIN", "gemini,local,offline")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ARTHAAI_LOCAL_BASE_URL", "http://127.0.0.1:9")  # nothing listening
    get_settings.cache_clear()
    try:
        state = {"symbol": "GLD", "db": {"available": True, "trend": "bullish", "trend_score": 0.4}}
        v = m.reason(state, "GLD")
        assert v.source == "offline-fallback"
        assert v.direction in {"bullish", "bearish", "neutral"}
    finally:
        get_settings.cache_clear()


def test_chain_list_always_ends_offline(monkeypatch):
    monkeypatch.setenv("ARTHAAI_LLM_CHAIN", "local")
    get_settings.cache_clear()
    try:
        assert get_settings().llm_chain_list == ["local", "offline"]
    finally:
        get_settings.cache_clear()
