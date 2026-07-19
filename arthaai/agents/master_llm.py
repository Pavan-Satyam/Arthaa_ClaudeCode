"""Master Reasoning LLM (the "Brain") — Tier 2 apex aggregator.

Ingests the unified GraphState (quant + sentiment + physical) and synthesises a
probabilistically weighted forecast with an explicit, auditable rationale ending
in "I choose this because…".

Provider-agnostic with a fallback chain (blueprint's resilience pattern). Each
provider is wrapped in a circuit breaker; on failure the chain advances to the
next, terminating at a deterministic offline reasoner so a verdict is ALWAYS
produced. Configure via ARTHAAI_LLM_CHAIN, e.g. "gemini,local,offline" or
"local,anthropic,offline".

Providers:
  anthropic  Claude API
  gemini     Google Generative Language API (REST)
  local      any OpenAI-compatible endpoint (Ollama / LM Studio / vLLM)
  offline    deterministic weighted-evidence reasoner (no network)
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from arthaai.config import get_settings
from arthaai.resiliency import guarded
from arthaai.security import AgentIdentity, authorize_tool, vault

IDENTITY = AgentIdentity("master_llm", "spiffe://arthaai/agent/master_llm")

SYSTEM = (
    "You are the Master Reasoning LLM of a financial multi-agent system. You do "
    "NOT compute numbers; you synthesise the deterministic evidence provided by "
    "sub-agents and explain conflicts. Return ONLY compact JSON with keys "
    "direction (bullish|bearish|neutral), confidence (0..1 float), rationale "
    "(string ending with a sentence starting 'I choose this because'). Warn of "
    "conflicting signals in the rationale."
)


@dataclass
class Verdict:
    direction: str        # bullish | bearish | neutral
    confidence: float     # 0..1
    rationale: str
    source: str           # which provider produced it


def _prompt(state: dict, symbol: str) -> str:
    payload = {k: state.get(k) for k in ("db", "quant", "news", "alt") if state.get(k)}
    return f"Asset: {symbol}\nAgent evidence (GraphState):\n{json.dumps(payload, indent=2)}"


def _parse_verdict(text: str, source: str) -> Verdict:
    """Lenient JSON extraction — local/open models don't always return clean JSON."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j != -1:
        t = t[i : j + 1]
    data = json.loads(t)
    direction = str(data.get("direction", "neutral")).lower()
    if direction not in {"bullish", "bearish", "neutral"}:
        direction = "neutral"
    conf = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    rationale = str(data.get("rationale", "")).strip() or "(model returned no rationale)"
    return Verdict(direction, round(conf, 3), rationale, source)


# --- providers (each returns a Verdict or raises) ------------------------
def _anthropic(state: dict, symbol: str) -> Verdict:
    key = vault.get_secret("arthaai", "anthropic_api_key", env="ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("no ANTHROPIC_API_KEY")
    from anthropic import Anthropic

    msg = Anthropic(api_key=key).messages.create(
        model=get_settings().llm_model,
        max_tokens=700,
        system=SYSTEM,
        messages=[{"role": "user", "content": _prompt(state, symbol)}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text")
    return _parse_verdict(text, "claude")


def _gemini(state: dict, symbol: str) -> Verdict:
    key = vault.get_secret("arthaai", "gemini_api_key", env="GEMINI_API_KEY")
    if not key:
        raise RuntimeError("no GEMINI_API_KEY")
    model = get_settings().gemini_model
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"parts": [{"text": _prompt(state, symbol)}]}],
        "generationConfig": {
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
            # 2.5+ are "thinking" models; without this they spend the token budget on
            # reasoning and truncate the JSON answer. 0 = answer directly.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    # Key goes in a header, never the URL — so it can't leak into logs/tracebacks.
    resp = httpx.post(url, headers={"x-goog-api-key": key}, json=body, timeout=30.0)
    resp.raise_for_status()
    text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    return _parse_verdict(text, "gemini")


def _local(state: dict, symbol: str) -> Verdict:
    """Any OpenAI-compatible chat endpoint — Ollama, LM Studio, vLLM, etc.

    This is the blueprint's 'internally-hosted open-weight model' — a local model
    keeps analysis running with zero external dependency or data egress.
    """
    s = get_settings()
    key = vault.get_secret("arthaai", "local_api_key", env="ARTHAAI_LOCAL_API_KEY") or "not-needed"
    resp = httpx.post(
        f"{s.local_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": s.local_model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": _prompt(state, symbol)},
            ],
            "temperature": 0.2,
            "max_tokens": 700,
        },
        timeout=90.0,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    return _parse_verdict(text, f"local:{s.local_model}")


def _weighted_score(state: dict) -> tuple[float, list[str]]:
    """Deterministic evidence blend — also the offline fallback reasoner."""
    signals, notes = [], []
    db = state.get("db", {})
    if db.get("available"):
        signals.append((db["trend_score"], 0.45))
        notes.append(f"technical trend {db['trend']} ({db['trend_score']:+.2f})")
    news = state.get("news", {})
    if news.get("available"):
        signals.append((news["avg_sentiment"], 0.30))
        notes.append(f"news sentiment {news['label']} ({news['avg_sentiment']:+.2f})")
    alt = state.get("alt", {})
    if alt.get("available"):
        signals.append((alt["physical_score"], 0.25))
        notes.append(f"physical/alt signal {alt['physical_score']:+.2f}")
    if not signals:
        return 0.0, ["no evidence available"]
    wsum = sum(w for _, w in signals)
    return sum(v * w for v, w in signals) / wsum, notes


def _offline(state: dict, symbol: str) -> Verdict:
    score, notes = _weighted_score(state)
    direction = "bullish" if score > 0.12 else "bearish" if score < -0.12 else "neutral"
    conf = min(1.0, 0.5 + abs(score) / 2)
    rationale = (
        f"Weighing the evidence for {symbol}: {'; '.join(notes)}. The signals net to "
        f"{score:+.2f}. I choose a {direction} stance because the weighted balance of "
        f"technical, sentiment, and physical evidence points that way."
    )
    return Verdict(direction, round(conf, 3), rationale, "offline-fallback")


_PROVIDERS = {"anthropic": _anthropic, "gemini": _gemini, "local": _local, "offline": _offline}


def provider_status() -> list[dict]:
    """Probe each provider in the configured chain; report reachability."""
    s = get_settings()
    out: list[dict] = []
    for name in s.llm_chain_list:
        if name == "offline":
            out.append({"provider": "offline", "ok": True, "detail": "deterministic reasoner (always available)"})
        elif name == "anthropic":
            key = vault.get_secret("arthaai", "anthropic_api_key", env="ANTHROPIC_API_KEY")
            out.append({"provider": "anthropic", "ok": bool(key),
                        "detail": f"key present · model {s.llm_model}" if key else "no ANTHROPIC_API_KEY"})
        elif name == "gemini":
            key = vault.get_secret("arthaai", "gemini_api_key", env="GEMINI_API_KEY")
            if not key:
                out.append({"provider": "gemini", "ok": False, "detail": "no GEMINI_API_KEY"})
            else:
                try:
                    r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models",
                                  headers={"x-goog-api-key": key}, timeout=8.0)
                    r.raise_for_status()
                    out.append({"provider": "gemini", "ok": True, "detail": f"reachable · model {s.gemini_model}"})
                except Exception as exc:  # noqa: BLE001
                    out.append({"provider": "gemini", "ok": False, "detail": f"key set but call failed: {exc}"})
        elif name == "local":
            try:
                r = httpx.get(f"{s.local_base_url.rstrip('/')}/models", timeout=5.0)
                r.raise_for_status()
                models = [m.get("id") for m in r.json().get("data", [])]
                have = s.local_model in models
                detail = f"server up · model '{s.local_model}' " + (
                    "loaded" if have else f"NOT pulled (run: ollama pull {s.local_model})")
                out.append({"provider": "local", "ok": have, "detail": detail})
            except Exception as exc:  # noqa: BLE001
                out.append({"provider": "local", "ok": False,
                            "detail": f"no server at {s.local_base_url} ({type(exc).__name__})"})
    return out


def reason(state: dict, symbol: str) -> Verdict:
    authorize_tool(IDENTITY, "llm_complete")
    for name in get_settings().llm_chain_list:
        fn = _PROVIDERS.get(name)
        if fn is None:
            continue
        if name == "offline":
            return _offline(state, symbol)
        result = guarded(f"llm:{name}", lambda fn=fn: fn(state, symbol), fallback=lambda: None)
        if result is not None:
            return result
    return _offline(state, symbol)
