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
| Sample hash (`sample_sha256_16`) | **`e6468871a625ea35`** |
| Frozen at | 2026-10-12 (extended-history re-freeze) |

Excluded and why: `SILVER`, `XAG` (no bars). The rule is applied uniformly from the
database; no symbol is added or dropped by hand.

The hash covers the symbol list **and each symbol's bar count**, so changing the
history (as below) yields a new hash and voids prior verdicts. The earlier
2-year sample (`f1f17e20c26d6eea`) and all results measured on it are superseded.

## 2. Data

- Source: TimescaleDB `ohlcv` (interval `1d`), providers `lse`/`yfinance`, adjustment
  basis `yfinance_auto_adjust_false`.
- Window: **2016-10-14 → 2026-10-09 (~10 years)**, **1249–3009** bars per symbol
  (avg ≈ 2522). Extended 2026-10-12 via `refresh-universe --lookback-days 3650`.
- Warmup: 60 bars (signals before this are ignored).
- The ~10-year window spans multiple regimes, giving materially more OOS windows
  than the superseded 2-year sample.

## 3. Signals under test

Evaluated through the **unchanged** promotion gate, one at a time. All results
below were measured on the **superseded 2-year** sample (`f1f17e20c26d6eea`) and
are **void** on the extended sample; they are listed only to preserve the audit
trail. Each family is re-run on `e6468871a625ea35` (see `evaluation/e3_results.md`).

1. `trend` — multi-timeframe SMA filter (baseline).
2. `breakout` — Donchian 55/20, ADX-gated (ADX ≥ 25).
3. `composite` — fixed five-factor per-bar mean (diagnostic; ARTHA-219).
4. `ic_composite` — walk-forward IC-weighted factor composite. *(void: 0/73 on old sample)*
5. **Classic momentum family** — pre-registered 2026-10-12:
   - `tsmom` — time-series momentum: long when trailing `lookback`-day return > 0.
   - `xsmom` — cross-sectional momentum: long the top `top_quantile` of trailing
     `lookback`-day return each date.
   Pre-registered variants: `tsmom` L=126; `xsmom` L=63 q=0.30; `xsmom` L=126 q=0.30.
   *(void: all 0/73 on old sample)*
6. **Intermarket risk-regime family** — pre-registered 2026-10-12, a different
   information axis (market state, not own price). Inputs are the SPY trend and the
   HYG/LQD credit ratio, all already in the universe (free, keyless, PIT-safe):
   - `regime` — long every symbol on risk-on days, flat on risk-off days.
   - `regime_tsmom` — the regime gate applied to each symbol's own `tsmom` L=126.
   Risk-on = SPY above its 200-day mean **and** HYG/LQD up over 63 bars. Both are
   reported, with no selection of the best.
7. **Fundamental value/quality axis** — pre-registered 2026-10-12, a genuinely
   exogenous axis from SEC EDGAR (free, keyless). **Scope: the equity subset of the
   frozen universe** (ETFs have no company fundamentals), declared separately as its
   own sample. Availability is the **filing date** (`filed`), so a signal at date *t*
   uses only facts filed on or before *t* (point-in-time; no look-ahead).
   - Metrics: book-to-price (`StockholdersEquity / market cap`), earnings yield
     (`NetIncomeLoss(TTM) / market cap`), ROE (`NetIncomeLoss / StockholdersEquity`).
   - Signal `value`: cross-sectional z-score of the three metrics, long the top
     `top_quantile` each date, flat otherwise.
8. **Macro term-spread axis** — pre-registered 2026-10-12, market-wide macro from the
   US 10y-2y treasury spread (FRED `T10Y2Y`, keyless CSV; market data, non-revised →
   PIT-safe). Applies to all 73 symbols.
   - `macro` — long every symbol when the spread > 0 (expansion), flat when inverted.
   - `macro_tsmom` — the macro gate applied to each symbol's own `tsmom` L=126.
   Both are reported, with no selection of the best.


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
