# E3 Evaluation Protocol — Frozen Sample

*Declared 2026-10-12 · branch `feat/arthaai-core`*

E3 (ARTHA-202) is the release gate: **a signal must beat buy-and-hold out-of-sample**
(Sharpe ≥ 1.0, MaxDD ≤ 20%, exposure-matched long-only return > B&H, on every OOS
window). Prior attempts failed, and the board showed why the *evidence* was
unreliable: a 5-asset positive reversed on 73 assets. This document freezes the
sample and the protocol **before** any further signal result is produced, so the
next verdict is reproducible rather than cherry-picked.

## 1. Frozen universe

| Field | Value |
|---|---|
| Manifest | `evaluation/frozen_universe.json` |
| Selection rule | registered symbol with ≥ **480** daily bars **and** a known exchange |
| Count | **73** symbols |
| Composition | 36 ETF · 33 equity · 4 commodity_etf |
| Exchanges | 36 NYSEARCA · 18 NASDAQ · 18 NYSE · 1 BATS |
| Content hash (`symbols_sha256_16`) | **`f1f17e20c26d6eea`** |
| Frozen at | 2026-10-12T01:24:33Z |

Excluded and why: `SILVER`, `XAG` (no bars). The rule is applied uniformly from the
database; no symbol is added or dropped by hand.

## 2. Data

- Source: TimescaleDB `ohlcv` (interval `1d`), provider `yfinance`, adjustment basis
  `yfinance_auto_adjust_false`.
- Window: 2024-08-02 → 2026-10-09 (~505–1048 bars per symbol).
- Warmup: 60 bars (signals before this are ignored).
- **This is a short (~2-year) sample.** Any conclusion is conditional on it.

## 3. Signals under test

Evaluated through the **unchanged** promotion gate, one at a time:

1. `trend` — multi-timeframe SMA filter (baseline).
2. `breakout` — Donchian 55/20, ADX-gated (ADX ≥ 25).
3. `composite` — fixed five-factor per-bar mean (diagnostic; ARTHA-219).
4. *(next)* a **walk-forward IC-weighted factor composite** — weights fitted only on
   data strictly before each OOS window.

## 4. Out-of-sample protocol

- Sequential, non-overlapping OOS windows (`oos_windows`, 30% tail, count = 2),
  each with the standard warmup.
- **No tuning on the OOS window.** Signal parameters, factor sets, and weights are
  chosen from in-sample data only. If a parameter is changed after seeing an OOS
  result, that result is void and the run must be redone on fresh windows.
- Cost model: **10 bps round-trip** on turnover (charged on |Δexposure|).
- Long-only is flat when the signal is not bullish; **no shorting**.

## 5. Pass criteria (unchanged)

A signal qualifies **only if every OOS window** passes:
Sharpe ≥ 1.0 · MaxDD ≤ 20% · exposure-matched long-only return > buy-and-hold.
`combine_windows()` requires all windows to pass; a single failure is a rejection.

## 6. Known limitations (declared, not hidden)

- **Survivorship / selection bias**: the 73 symbols are a curated, currently-listed
  set. There is no point-in-time constituent history, so index/sector ETFs and large
  caps are over-represented relative to a true historical universe.
- **Single provider**: all bars come from yfinance; no independent price cross-check.
- **Short history**: ~2 years; results may not generalize across regimes.
- **No corporate-action re-adjustment audit** for this sample.

These bound what any E3 pass/fail can claim. A pass here is necessary, not
sufficient, for a global edge claim.

## 7. Reproduce

```powershell
$env:PYTHONUTF8=1
.\.venv\Scripts\python.exe -m arthaai.cli backfill-metadata          # populate exchange/class
.\.venv\Scripts\python.exe -m arthaai.cli freeze-universe            # re-emit manifest + hash
.\.venv\Scripts\python.exe -m arthaai.cli promote-sweep --signal composite --cost-bps 10
```

## 8. Change control

Any change to the selection rule, windowing, costs, or pass criteria requires a
**new freeze** (new hash) recorded here, with the old result explicitly voided.
The manifest hash is the identity of the sample: if it changes, prior verdicts do
not carry over.
