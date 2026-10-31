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

9. **XGBoost over the factor zoo** (`xgb_zoo`) — pre-registered 2026-10-23, the
   architecture doc's own recipe ("alpha factors → tabular model → signal → gate").
   - **Target:** volatility-adjusted forward return (1-day forward return ÷ trailing
     20-day realized vol), *not* raw forward return, so the pooled model is not
     dominated by asset-class beta. An `asset_class` categorical (equity vs
     commodity ETF) separates the two groups.
   - **Features:** strictly **backward-looking** — trailing returns (1/5/20/60d),
     20-day realized vol, 20/60-day MA distance, raw `tsmom`/`xsmom` L=126, and the
     qlib158 beta/corr/cord windows. Composite/meta-signals (`ic_composite`) are
     **excluded** as features because their weights are fit over the whole panel and
     would leak across the walk-forward boundary.
   - **Walk-forward:** expanding-window fit, predict into the next slice. Fixed
     hyperparameters (max_depth 3, n_estimators 300, learning_rate 0.05, subsample
     0.8, colsample 0.8, λ=1.0) chosen in-sample; **no tuning on any OOS window**.
   - **Position mapping:** EMA(5) smoothing + hysteresis — enter long above the 60th
     percentile of the smoothed score's own trailing 252-day window, exit below the
     40th — to control turnover under the 10 bps cost.
10. **Commodity positioning** (`cftc`) — pre-registered 2026-10-23, CFTC Commitments
   of Traders (free since 1995). Net non-commercial positioning z-scored over a
   trailing 156-week window; long a commodity ETF (GLD/SLV/USO) when speculators are
   net-long vs their own history. **PIT:** the Tuesday report is only usable from the
   Friday release (`effective_date = report + 3 business days`).
11. **Energy inventories** (`eia`) — pre-registered 2026-10-23, EIA Weekly Petroleum
   Status Report (free, API key). Long energy names (USO/XOM) when crude stocks are
   drawing (trailing 4-week change < 0). **PIT:** the Friday period is usable from
   the following Wednesday (`effective_date = period + 5 calendar days`).
12. **Insider buying** (`insider`) — pre-registered 2026-10-23, SEC Form 4 (free via
   EDGAR). Cross-sectional: long the top `top_quantile` by trailing 63-day net
   insider-buy flow, over the equity subset. **PIT:** anchored on the filing
   (acceptance) date, never `transaction_date`; a filing accepted after 16:00 ET is
   effective the next business day. FINRA short interest is deliberately **not**
   included — its free history is ~12-24 months and cannot pass a 10-year gate.
13. **Volatility term structure** (`vix_regime`) — pre-registered 2026-10-23, Cboe
   VIX/VIX3M daily CSVs (free). Market-wide gate: long every symbol when the VIX/VIX3M
   ratio < 1.0 (contango/calm), flat when the curve is inverted (near-term stress).


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
.\.venv\Scripts\python.exe -m arthaai.cli promote-sweep --signal composite --cost-bps 10 --limit 3100 --no-save
```

**`--limit` is required.** `promote-sweep` loads at most `--limit` bars per symbol (default 520, ~2 years).
To evaluate the full ~10-year sample, pass `--limit 3100` (≥ the largest per-symbol bar count, 3009). The
sweep table's **Bars** column and footer show what was actually evaluated — check it matches the sample's
`bar_counts` before recording a verdict. *(Added 2026-10-21, ARTHA-315: sweeps recorded before this
date omitted `--limit`, and five variants silently ran `trend`; see `evaluation/e3_results.md`.)*

## 8. Change control

Any change to the selection rule, windowing, costs, or pass criteria requires a
**new freeze** (new hash) recorded here, with the old result explicitly voided.
The manifest hash is the identity of the sample: if it changes, prior verdicts do
not carry over.
