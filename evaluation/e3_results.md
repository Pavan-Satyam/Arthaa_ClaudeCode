# E3 Results Log

*Protocol: [E3_EVALUATION_PROTOCOL.md](../E3_EVALUATION_PROTOCOL.md)*

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

