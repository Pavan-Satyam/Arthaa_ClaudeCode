# AGENTS.md

## Project overview

ArthaAI is a zero-trust multi-agent LLM framework for equities & commodities analysis. The deterministic quant layer computes all numbers; the LLM only synthesises and explains. Kelly sizing runs on statistics, never on LLM-invented probabilities.

## Environment setup

- Python 3.12+, venv at `.venv`
- Windows: must set `$env:PYTHONUTF8=1` before running anything (Rich console crashes on cp1252)
- Install: `pip install -e ".[dev,embed]"`
- Docker stack: `docker compose up -d` (TimescaleDB, Qdrant, Redpanda, OPA, Vault)
- No ANTHROPIC_API_KEY required — Master LLM falls back to offline deterministic reasoner

## Build / test / lint commands

```powershell
# Run DB-independent tests (fast, ~18s):
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m pytest tests/ -q -k "not health"

# Run a specific test file:
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m pytest tests/test_kelly.py -v

# Lint:
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m ruff check arthaai/ tests/

# Run the full pipeline (needs Docker stack running):
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m arthaai.cli analyze GLD --skip-ingest

# Backtest:
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m arthaai.cli backtest GLD --signal breakout --adx 25

# Signal comparison across assets:
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m arthaai.cli compare --symbols GLD,SLV,USO,XOM,AAPL

# LLM eval harness:
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe -m arthaai.cli eval --provider offline
```

## Architecture

```
ingest (yfinance → TimescaleDB)
    │  fan-out (LangGraph)
    ├── DB_Agent      → technical indicators + signal selector (trend|breakout via ADX)
    ├── Quant Agent   → μ / σ² / signal-conditioned Kelly inputs (W, R)
    ├── News_Agent    → hybrid-search sentiment (Qdrant, fastembed BAAI/bge-small-en-v1.5)
    └── Alt_Agent     → physical signal (stub)
    │  converge → State Store (GraphState)
    ▼
Master Reasoning LLM  → direction + confidence + explicit rationale (provider chain → offline fallback)
    ▼
Asset Manager Agent   → discrete Kelly (primary) + continuous Kelly (informational) + 5% policy cap → allocation
```

## Key design rules

1. **Quant layer is deterministic** — all numbers computed in `indicators.py`, never by the LLM
2. **LLM only synthesises** — the Master LLM explains conflicts and produces a verdict, but does not compute
3. **Discrete Kelly is the sizing driver** — continuous Kelly is informational only; the 5% policy cap is a guardrail for strong edges, not the default sizer
4. **Signal selection is ADX-driven** — trending (ADX≥25) uses Donchian breakout; choppy/weak-trend uses multi-timeframe trend filter
5. **Look-ahead-safe backtest** — signal at bar t only sees bars ≤ t; return at t+1 grades the signal
6. **No shorting in sizing** — negative discrete Kelly → flat (0%), not leverage

## Key files

- `arthaai/agents/indicators.py` — core signal logic: `_trend_signal_series` (vectorized O(n)), `trend_signal`, `breakout_positions`, `breakout_signal`, `signal_kelly_stats`, `adx`, `rsi`, `wr_from_tallies`
- `arthaai/agents/asset_manager.py` — Kelly sizing: discrete Kelly primary, continuous Kelly informational, 5% policy cap
- `arthaai/agents/db_agent.py` — live agent: ADX regime → signal selector (trend vs breakout)
- `arthaai/agents/quant_agent.py` — signal-conditioned Kelly stats (matches db_agent's signal class)
- `arthaai/agents/master_llm.py` — provider chain (anthropic → gemini → local → offline) with circuit breaker
- `arthaai/backtest/engine.py` — walk-forward backtest with incremental Kelly accumulation
- `arthaai/eval/harness.py` — golden-fixture eval harness with direction accuracy, rationale rate, confidence calibration
- `arthaai/gateway/app.py` — FastAPI gateway: httpOnly cookie auth, authenticated /ohlcv
- `arthaai/gateway/auth.py` — bearer header + cookie auth
- `arthaai/config.py` — env-driven settings including `dev_mode` (controls cookie secure flag)
- `tests/conftest.py` — autouse fixture bypasses OPA network calls in tests

## Test notes

- `tests/conftest.py` monkeypatches `opa.is_allowed` to skip the 2s OPA network timeout — all tests use the in-process ALLOWED map
- `test_health` is excluded from normal runs (`-k "not health"`) because it pings TimescaleDB (hangs if Docker is down)
- Tests that need the DB are not in the fast set — they hang without Docker
- 49 DB-independent tests pass in ~18s

## Known issues

- Push to `origin/feat/arthaai-core` fails (403 permission denied) — GitHub account lacks write access to `Pavan-Satyam/Arthaa_ClaudeCode`
- Qdrant client 1.19.0 vs server 1.12.4 version mismatch warning is cosmetic
- Vault 404 warnings expected (run `arthaai seed-secrets` to populate; env fallback works)
- `breakout_signal()` has no runtime caller yet — backtest uses `breakout_positions` directly; live `analyze` uses the signal selector in `db_agent`
