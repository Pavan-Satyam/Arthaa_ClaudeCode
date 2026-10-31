# E3 Results Log

*Protocol: [E3_EVALUATION_PROTOCOL.md](../E3_EVALUATION_PROTOCOL.md)*

> **⚠️ Harness correction (2026-10-21, ARTHA-315) — read before using any result below.**
>
> 1. **Void — never tested their own signal:** `regime`, `regime_tsmom`, `value`, `macro`, `macro_tsmom`.
>    `promote-sweep` only built signal maps for `ic_composite`/`tsmom`/`xsmom`, so these five silently
>    ran the **trend** baseline. Their sweep files are row-for-row identical to `sweep10_trend.txt`
>    (73/73; `value` 33/34). The same applied to `backtest --signal <name>`, so the single-symbol
>    cross-checks quoted for these variants (e.g. `backtest AAPL --signal value`) were trend too.
> 2. **"10-year" sweeps likely evaluated ~2 years.** `promote-sweep` defaults to `--limit 520` and no
>    command below passes `--limit`. The recorded GLD trend row matches a local `--limit 520` run, not a
>    full-history run. The extended-history results are therefore unverified.
> 3. **Persisted/displayed metrics came from the older window.** `oos_windows()` returns most-recent-first,
>    but `promote` and `promote-sweep` reported `rows[-1]`. Pass/fail verdicts are unaffected (every
>    window must pass); the single-window metrics shown in sweep tables are.
>
> Fixed in code on 2026-10-21: every signal now routes to its own series, the engine refuses an unknown
> signal instead of falling back to trend, sweeps print the bars evaluated and the `--limit` used, and
> the most recent window is reported. **The verdicts below stand as historical records only; all
> variants must be re-run with an explicit `--limit 3100` before any E3 conclusion is drawn.**

## 2026-10-12 — IC-weighted cross-sectional composite

| Field | Value |
|---|---|
| Sample | `evaluation/frozen_universe.json`, hash `f1f17e20c26d6eea` (73 symbols) |
| Signal | `ic_composite` — walk-forward IC-weighted cross-sectional composite |
| Construction | 5 alpha101 factors; per-date cross-sectional z-score; weight = expanding mean of rank-IC vs forward return, floored at 0, lagged `horizon+embargo-1` bars |
| Command | `arthaai promote-sweep --symbols <frozen 73> --signal ic_composite --cost-bps 10 --no-save` |
| Gate | unchanged: Sharpe ≥ 1.0 · MaxDD ≤ 20% · long-only > B&H · **every** OOS window |
| **Verdict** | **0 / 73 qualified** |
| Promotion rows written | none (`--no-save`) |

Per-symbol window passes: 2/73 symbols passed a single window (BITO, CRM, EWJ, PPLT, VZ, XLE — each 1/2); **0 passed both**. Representative rows: GLD 0/2 (long-only +19.93% vs B&H +30.65%, Sharpe 2.21); SLV 0/2 (+68.36% vs +79.50%); SPY 0/2 (+1.02% vs +2.40%).

Single-symbol cross-check — `arthaai backtest GLD --signal ic_composite`: edge **−23.91%**, Sharpe **0.72**.

**Conclusion:** the walk-forward IC-weighted composite does **not** beat buy-and-hold on the frozen sample. E3 remains open. No promotion criterion was changed. This is a negative result by the declared protocol, not a tuning opportunity — any further attempt must be a *different, pre-declared* signal family, evaluated on the same frozen hash.

## 2026-10-12 — Classic momentum family (tsmom / xsmom)

Pre-registered in [E3_EVALUATION_PROTOCOL.md](../E3_EVALUATION_PROTOCOL.md) §3 before running.
Same frozen sample (hash `f1f17e20c26d6eea`, 73 symbols), same gate, `--cost-bps 10`, no save.

| Variant | Command | Result | 1-window passes |
|---|---|---|---|
| `tsmom` L=126 | `promote-sweep --signal tsmom --lookback 126` | **0/73** | 6 |
| `xsmom` L=63 q=0.30 | `promote-sweep --signal xsmom --lookback 63 --top-quantile 0.30` | **0/73** | 3 |
| `xsmom` L=126 q=0.30 | `promote-sweep --signal xsmom --lookback 126 --top-quantile 0.30` | **0/73** | 4 |

Raw sweep tables: `evaluation/sweep_tsmom_126.txt`, `sweep_xsmom_63.txt`, `sweep_xsmom_126.txt`.

**Conclusion:** none of the three pre-registered momentum variants beat buy-and-hold on the frozen
sample (no symbol passed both OOS windows). Reported in full, with no selection of the best. E3 remains
open. Five pre-declared signal families (trend, breakout, composite, ic_composite, momentum) have now
been evaluated on this sample and none clears the gate — the strongest honest reading is that this
~2-year, 73-asset sample offers no promotable edge under the current criteria.

## 2026-10-12 — Extended-history sample (re-freeze, all families re-run)

The ~2-year window above was the sample's biggest weakness. Extended history via
`refresh-universe --lookback-days 3650` → **2016-10-14 → 2026-10-09 (~10 years)**, 1249–3009 bars
per symbol. Re-froze: `evaluation/frozen_universe.json`, **sample hash `e6468871a625ea35`**
(the hash now covers bar counts, so the old hash `f1f17e20c26d6eea` and its results are void).

Same gate, same 73 symbols, `--cost-bps 10`, no save. All pre-declared families re-run:

| Family | Command | Result | 2/2 | 1/2 |
|---|---|---|---|---|
| `trend` | `--signal trend` | **0/73** | 0 | 8 |
| `breakout` | `--signal breakout --adx 25` | **0/73** | 0 | 4 |
| `composite` | `--signal composite` | **0/73** | 0 | 0 |
| `ic_composite` | `--signal ic_composite` | **0/73** | 0 | 6 |
| `tsmom` L=126 | `--signal tsmom --lookback 126` | **0/73** | 0 | 9 |
| `xsmom` L=63 | `--signal xsmom --lookback 63 --top-quantile 0.30` | **0/73** | 0 | 3 |
| `xsmom` L=126 | `--signal xsmom --lookback 126 --top-quantile 0.30` | **0/73** | 0 | 5 |

Raw sweeps: `evaluation/sweep10_*.txt`.

**Conclusion:** extending the sample to ~10 years does not change the verdict. **No family passes both
OOS windows on any symbol.** The negative result is now robust to sample length, not an artifact of a
short window. E3 remains open; the gate and promotion criteria are unchanged. Further progress needs a
different data axis (alt/fundamental/news signals), not more price-signal permutations on this sample.

## 2026-10-12 — Intermarket risk-regime family (different information axis)

Pre-registered in the protocol §3 before running. Same frozen sample (`e6468871a625ea35`), same gate,
`--cost-bps 10`, no save. This is a **different axis**: market state (SPY trend + HYG/LQD credit ratio),
not the asset's own price. Inputs are already in the universe — free, keyless, PIT-safe.

| Variant | Command | Result | 2/2 | 1/2 |
|---|---|---|---|---|
| `regime` | `--signal regime` | **0/73** | 0 | 8 |
| `regime_tsmom` | `--signal regime_tsmom --lookback 126` | **0/73** | 0 | 8 |

Raw sweeps: `evaluation/sweep10_regime.txt`, `evaluation/sweep10_regime_tsmom.txt`.

**Conclusion:** the intermarket risk-regime axis does not beat buy-and-hold either. With **eight**
pre-declared variants now failing on the extended sample across two information axes (own-price and
market-state), the honest reading is firm: **no promotable edge is present in price/market data for this
73-asset universe under the current criteria.** The next attempt requires a genuinely exogenous data
axis (fundamentals, macro, news) with point-in-time handling — not more signals from the same data.

## 2026-10-12 — Fundamental value/quality axis (SEC EDGAR, PIT)

Pre-registered in the protocol §3 before running. A genuinely exogenous axis from SEC EDGAR's public
XBRL API (free, keyless). Availability is the **filing date**, so signals are point-in-time. **Scope:
the equity subset** (ETFs have no company fundamentals) — 33 symbols, so this is a *separate* sample
from the 73-asset universe. Command:
`promote-sweep --symbols <equities> --signal value --cost-bps 10 --no-save`.

Signal `value`: cross-sectional z-score of book-to-price, earnings yield, and ROE; long the top 30%
each date, flat otherwise.

| Variant | Result | 2/2 | 1/2 |
|---|---|---|---|
| `value` | **0/34** (33 equities; `XAG` no data) | 0 | 3 |

Raw sweep: `evaluation/sweep10_value.txt`.

**Conclusion:** the fundamental value/quality axis does not beat buy-and-hold on the equity subset
either. Single-symbol cross-check — `arthaai backtest AAPL --signal value`: edge −48.88%, Sharpe −0.77.

**Nine** pre-declared variants now fail across **three** information axes (own-price, market-state,
fundamental). The evidence is consistent and, under the protocol, decisive: the available data does not
contain a promotable edge for this universe under the current gate.

## 2026-10-12 — Macro term-spread axis (FRED T10Y2Y, keyless)

Pre-registered in the protocol §3 before running. Market-wide macro axis from the US 10y-2y treasury
spread (FRED `T10Y2Y`, keyless CSV; market data, non-revised → PIT-safe). Same frozen 73-symbol sample
(`e6468871a625ea35`), same gate, `--cost-bps 10`, no save.

| Variant | Command | Result | 2/2 | 1/2 |
|---|---|---|---|---|
| `macro` | `--signal macro` | **0/73** | 0 | 8 |
| `macro_tsmom` | `--signal macro_tsmom --lookback 126` | **0/73** | 0 | 8 |

Raw sweeps: `evaluation/sweep10_macro.txt`, `evaluation/sweep10_macro_tsmom.txt`.

**Conclusion:** the macro term-spread axis does not beat buy-and-hold either. **Eleven** pre-declared
variants have now failed across **four** information axes (own-price, market-state, fundamental, macro).
Every tractable, free, point-in-time-safe axis available without new data procurement has been tested and
none clears the gate. The conclusion recorded above stands and is now exhaustive for the data at hand.

## 2026-10-24 — Verified re-run on a genuine 10-year sample (harness fixed + history densified)

**Why this section exists.** The 2026-10-12 "extended-history" runs above are void under the §7 correction:
they never passed `--limit`, so `promote-sweep` used its default (520 ≈ 2 years). This section is the
re-run those runs required, and it also **densified the stored history**, which was the deeper problem.

**Sample repair (step 1a.5).** The frozen universe's stored daily bars were sparse — several symbols had
huge gaps inside a 10-year span (ABBV 544 bars, GLD 1459, XLC 2099, MSFT 1647). Audited with the new
`arthaai history-depth`, then rebuilt cleanly: delete the universe's `1d` rows →
`refresh-universe --symbols <frozen 73> --lookback-days 3650 --provider yfinance` → `repair_daily_duplicates`.
Result: **2016-10-26 → 2026-10-23 (~10 years)**, bars per symbol **min 1258 · median 2512 · max 2512**
(only BITO, a 2021 listing, and XLC, a 2018 fund, are legitimately short). `history-depth` now passes the
E3 gate. Frozen sample hash unchanged: **`e6468871a625ea35`** (73 symbols).

**Guard active.** `promote-sweep` now prints bars evaluated and the `--limit` used; every run below
evaluated **median 2512 bars** (≈10y) with no shallow-table warning. This is the first E3 run whose window
is *verifiably* ~10 years.

Command pattern (all variants, `--cost-bps 10`, `--warmup 60`, `--windows 2`, `--no-save`):
`arthaai promote-sweep --symbols <frozen 73> --signal <name> --limit 3100 ...`

| Variant | Command | Result | 2/2 | 1/2 |
|---|---|---|---|---|
| `trend` | `--signal trend` | **0/73** | 0 | 0 |
| `breakout` | `--signal breakout --adx 25` | **0/73** | 0 | 0 |
| `composite` | `--signal composite` | **0/73** | 0 | 0 |
| `ic_composite` | `--signal ic_composite` | **0/73** | 0 | 1 |
| `tsmom` L=126 | `--signal tsmom --lookback 126` | **0/73** | 0 | 1 |
| `xsmom` L=63 | `--signal xsmom --lookback 63 --top-quantile 0.30` | **0/73** | 0 | 1 |
| `xsmom` L=126 | `--signal xsmom --lookback 126 --top-quantile 0.30` | **0/73** | 0 | 2 |
| `regime` | `--signal regime` | **0/73** | 0 | 0 |
| `regime_tsmom` | `--signal regime_tsmom --lookback 126` | **0/73** | 0 | 0 |
| `value` | `--signal value` (equity subset: 45 with fundamentals, 28 no-data) | **0/45** | 0 | 0 |
| `macro` | `--signal macro` | **0/73** | 0 | 1 |
| `macro_tsmom` | `--signal macro_tsmom --lookback 126` | **0/73** | 0 | 0 |
| `xgb_zoo` | `--signal xgb_zoo` (new family 9) | **0/73** | 0 | 3 |

- `trend` as a single 73-symbol process crashed natively (Windows rc `0xC0000409`); re-run in 4 chunks
  (no crash) → 0/73, 8 symbols passed one window in the earlier (void) run.
- `xgb_zoo` is the architecture doc's own recipe (pre-registered family 9): volatility-adjusted target,
  strictly backward-looking features, EMA(5)+hysteresis position mapping. It does **not** clear the gate.

Raw sweep tables: `evaluation/e3_rerun_<variant>.txt` (trend split as `e3_rerun_trend_chunk{0..3}.txt`).

**Conclusion:** on a genuine, gap-free ~10-year sample and with the harness fixed, **no pre-registered
family clears the promotion gate** — **thirteen** variants across five information axes (own-price,
market-state, fundamental, macro, and now a pre-registered ML model) all fail. The negative verdict is
therefore robust and now trustworthy: it is **not** an artifact of a short or gappy window, and **not** an
artifact of the earlier signal-routing bug. E3 remains open; the gate and criteria are unchanged. Further
progress requires a genuinely new exogenous data axis or new data procurement (estimate revisions,
licensing, survivorship-free history) — **not** more permutations of the same price/market data.





