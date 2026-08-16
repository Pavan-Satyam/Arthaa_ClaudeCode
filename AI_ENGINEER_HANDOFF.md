# ArthaAI — AI/ML Engineer Handoff

For the end-to-end system flow, see [`README.md`](README.md) and the annotated
[`arthaai-architecture.html`](arthaai-architecture.html).
**This doc covers the model surface only:** prompts, the LLM provider layer, the
RAG pipeline, evaluation, and where the "intelligence" actually lives.

Read §1 before touching anything — it contains four facts that will otherwise
cost you a day.

---

## 1. Four things that will surprise you

### 1.1 The LLM is a *synthesiser*, not a predictor — keep it that way
Every number that influences a trade is computed deterministically in
[`agents/indicators.py`](arthaai/agents/indicators.py) and
[`agents/asset_manager.py`](arthaai/agents/asset_manager.py). The model's job is to
read those numbers plus news context, resolve contradictions, and write an
explained verdict.

> The tempting "improvement" is to let the model forecast prices or emit its own
> probabilities into position sizing. **Don't.** LLM probabilities are
> uncalibrated, and Kelly sizing is extremely sensitive to probability error —
> that path is a fast route to confidently-sized nonsense. If you want better
> predictions, improve the deterministic signal (§6).

### 1.2 The news embeddings are currently **non-semantic** 🔴
[`db/qdrant.py`](arthaai/db/qdrant.py) tries `fastembed`; if it's missing it falls
back to a **hash-based pseudo-embedding**. `fastembed` is an optional extra and is
**not installed**, so the fallback is live. Measured right now:

```
cosine("gold prices rise", "gold prices increase") = 0.216   # ≈ random
```

Hybrid search still hard-filters by ticker, so results belong to the right asset —
but the **ranking within them is meaningless**. Any conclusion you draw about
"sentiment retrieval quality" today is measuring noise. Fix first:

```bash
arch -x86_64 .venv/bin/pip install -e ".[embed]"   # BAAI/bge-small-en-v1.5, local ONNX
```
Then re-seed (`arthaai seed-news`) so vectors are rebuilt with the real model.

### 1.3 There are **no LLM-level evaluations**
`arthaai backtest` evaluates the *deterministic signal*, not the model. There is
no golden set, no regression test on prompt changes, no calibration measurement.
Change the prompt today and nothing tells you if it got worse. Building this is
your highest-leverage early task (§5).

### 1.4 `confidence` is uncalibrated but *does* reach position sizing
`asset_manager.size(quant, confidence=...)` blends the model's confidence into the
win probability:
```python
w = 0.5 * w + 0.5 * confidence     # agents/asset_manager.py
```
It's dampened (50/50 with the empirical win rate) and bounded by quarter-Kelly plus
a hard 5% cap, so blast radius is limited — but it is **not** a calibrated
probability. Treat calibrating or removing this as a real decision (§5.3).

---

## 2. Where the intelligence lives

| Concern | File | Notes |
|---|---|---|
| Prompt, providers, parsing, fallback chain | [`agents/master_llm.py`](arthaai/agents/master_llm.py) | the whole model surface |
| Deterministic indicators (never LLM) | [`agents/indicators.py`](arthaai/agents/indicators.py) | SMA/RSI/μ/σ²/W/R |
| Position sizing (consumes `confidence`) | [`agents/asset_manager.py`](arthaai/agents/asset_manager.py) | Kelly + policy cap |
| RAG: embeddings + hybrid search | [`db/qdrant.py`](arthaai/db/qdrant.py) | ticker filter → vector search |
| News corpus (seed only) | [`data/seed_news.py`](arthaai/data/seed_news.py) | 8 hand-written docs |
| Agent graph / state | [`orchestration/graph.py`](arthaai/orchestration/graph.py) | LangGraph, `GraphState` |
| Per-agent tool permissions | [`security/opa.py`](arthaai/security/opa.py), [`policy/arthaai.rego`](policy/arthaai.rego) | `master_llm` may only call `llm_complete` |

---

## 3. The prompt contract

Single system prompt, `SYSTEM` in `master_llm.py`. It pins three things:
1. **Role:** synthesise sub-agent evidence; do **not** compute numbers.
2. **Output:** JSON only — `direction` (`bullish|bearish|neutral`), `confidence`
   (0–1 float), `rationale` (string ending with a sentence starting
   *"I choose this because"*).
3. **Behaviour:** explicitly flag conflicting signals rather than smoothing them.

The user message is the serialised `GraphState` slice (`db`, `quant`, `news`,
`alt`) built by `_prompt()`.

**Parsing is deliberately lenient** (`_parse_verdict`): strips code fences,
extracts the outermost `{...}`, clamps `confidence` to [0,1], and coerces an
unknown `direction` to `neutral`. This exists because open/local models wrap JSON
in prose. Keep it lenient — but note it means a malformed answer degrades quietly
to `neutral` rather than erroring. If you add strict validation, add a metric too.

**Changing the prompt:** there is no versioning today. Before you iterate, build
the eval harness (§5) or you're flying blind. Suggested: keep `SYSTEM` versioned
(`SYSTEM_V2 = ...`), record the version in `Verdict.source`, and diff eval scores.

---

## 4. Provider layer — how to add or swap a model

Chain resolved from `ARTHAAI_LLM_CHAIN` (e.g. `gemini,local,offline`) via
`Settings.llm_chain_list`. `reason()` walks it; each provider is wrapped in
`guarded(...)` (circuit breaker) and on failure the chain advances. `offline` is
terminal and always succeeds, so **a verdict is always produced**.

Current providers:

| Name | Transport | Notes |
|---|---|---|
| `gemini` | REST | **Key must go in the `x-goog-api-key` header**, never `?key=` (it leaked into logs/tracebacks before). Default `gemini-2.5-flash`; `gemini-2.0-flash` is **deprecated → 404**. |
| `local` | OpenAI-compatible `/chat/completions` | Ollama / LM Studio / vLLM. `temperature=0.2`. |
| `anthropic` | Anthropic SDK | Claude. |
| `offline` | none | Deterministic weighted blend of the evidence (`_weighted_score`): technical 0.45, sentiment 0.30, physical 0.25. |

⚠️ **Gemini 2.5+ are thinking models.** Without `thinkingConfig.thinkingBudget: 0`
they spend the output budget reasoning and return **truncated JSON** (this bit us).
If you raise `maxOutputTokens` or enable thinking, re-check parsing.

**Adding a provider** — write a function returning a `Verdict` (or raising), then
register it:
```python
def _my_provider(state: dict, symbol: str) -> Verdict:
    key = vault.get_secret("arthaai", "my_api_key", env="MY_API_KEY")
    if not key: raise RuntimeError("no MY_API_KEY")
    text = ...  # call the model with SYSTEM + _prompt(state, symbol)
    return _parse_verdict(text, "my-provider")

_PROVIDERS["myprovider"] = _my_provider
```
Then `ARTHAAI_LLM_CHAIN=myprovider,offline`. Secrets resolve via Vault with env
fallback — never read `os.environ` directly. Check reachability with
`make llm-status`.

---

## 5. Evaluation — what to build (priority order)

### 5.1 Golden-fixture regression (build this first)
Freeze ~20–30 `GraphState` fixtures spanning: clear bull, clear bear, flat, and —
most importantly — **conflicting** cases (bullish technicals vs bearish sentiment).
Assert the model's `direction` lands in an accepted set and the rationale mentions
the conflict. Run it on every prompt/model change. Fixtures are cheap: capture real
states from `orchestration.analyze()` and commit them as JSON.

### 5.2 Consistency / variance
Same fixture × N runs → measure direction flip rate and confidence spread. High
variance means the prompt is under-constrained (or temperature too high). This is
the cheapest signal that a prompt edit made things worse.

### 5.3 Calibration (before trusting `confidence`)
Log `(confidence, direction, realised forward return)` per analysis, then score
with **Brier score** / a reliability curve. If confidence isn't calibrated, either
recalibrate (isotonic/Platt on historical outcomes) or **cut the confidence→Kelly
link** in `asset_manager.size()`. Right now it's an unvalidated input to money.

### 5.4 LLM-as-judge (optional, later)
A second model grading rationale quality — does it cite the evidence, does it
acknowledge conflicts, is it non-generic. Useful for prompt iteration; do not use
it as a trading signal.

> Note what evaluation **cannot** fix: if the underlying signal has no edge, a
> perfectly-evaluated LLM just explains a coin flip more eloquently.

---

## 6. The actual bottleneck (please read)

`arthaai backtest GLD` currently shows the naive SMA/RSI signal **underperforming
buy-and-hold** (~+2% vs ~+50% on the sample window). Prompt engineering will not
fix that — it isn't a model problem.

The highest-value AI work here is **signal research**: better features (multi-
timeframe, volatility regimes, cross-asset), proper walk-forward validation, and
honest out-of-sample discipline. The harness already exists
([`backtest/engine.py`](arthaai/backtest/engine.py)) and is look-ahead guarded —
the signal at day *t* only sees bars ≤ *t*, and it sizes with the real Kelly+cap
logic, so improvements measured there are real.

---

## 7. Blueprint ambitions vs. my recommendation

The original architecture doc calls for SEAL self-adapting fine-tuning, replay
buffers for catastrophic forgetting, and NeMo Guardrails.

**Recommendation: don't, yet.** Fine-tuning a reasoning model is not the
constraint — no evals exist to prove a tuned model is better, and the signal has no
edge to amplify. Sequence it: real embeddings → eval harness → calibration →
signal edge. Revisit fine-tuning only if evals show the *synthesis step* is the
limiter, which is unlikely. (NeMo-style guardrails are more defensible sooner if
this ever ingests untrusted external text — prompt injection via scraped news is a
real threat, and today's only defence is that the LLM has no tool access beyond
`llm_complete`.)

---

## 8. Gotchas

- **Rosetta/x86_64:** this Mac's shell is x86_64; the venv matches. Use `make …`
  or `arch -x86_64 .venv/bin/python …`, else you get "incompatible architecture".
- **`.env` loading:** `pydantic-settings` only reads `ARTHAAI_`-prefixed vars;
  unprefixed secrets (`GEMINI_API_KEY`) work only because `config.py` calls
  `load_dotenv()`. Keep that call.
- **Symbols** are normalised (`.RDW` → `RDW`); no-data tickers surface a clear
  message rather than an empty verdict.
- **A verdict always exists.** Absence of the LLM is invisible unless you check
  `verdict.source` — always log/inspect it when evaluating.
- **Rotate the Gemini key** if it was ever printed to logs during setup.

---

## 9. Suggested first two weeks

1. `pip install -e ".[embed]"`, re-seed, and re-check retrieval quality — you're
   currently evaluating noise.
2. Replace seed news with a real feed (RSS/NewsAPI) + sensible chunking/metadata.
3. Build the golden-fixture eval harness (§5.1) and wire it into `pytest`.
4. Instrument calibration logging (§5.3); decide whether `confidence` keeps
   touching Kelly.
5. Then — and this is the real work — **signal research against the backtest** (§6).
