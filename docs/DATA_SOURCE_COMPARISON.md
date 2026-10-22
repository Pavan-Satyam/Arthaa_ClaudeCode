# Data Source Comparison — POC (free) vs. Enterprise (paid)

*Prepared 2026-10-21 · supports the open decision in [DATA_PRODUCTION_READINESS.md](../DATA_PRODUCTION_READINESS.md)
("Select initial production coverage and approve source/data-rights requirements").*

**Policy this follows:** free/open sources for POC and research; buy licensed data only when a
component is moving to enterprise use. Every source below is judged on that split.

> **Accuracy note.** Free-tier limits and prices change often. Figures marked † come from
> third-party pricing trackers or community docs found in October 2026 because the vendor's own page
> wasn't reachable; figures marked ‡ were not re-checked this session. Confirm on the vendor's
> pricing page before signing anything. Sources are listed at the end.

---

## 1. How to read this

Each source is scored against what ArthaAI actually needs:

| Criterion | Why it matters here |
|---|---|
| **Point-in-time (PIT)** | The E3 protocol forbids look-ahead. A value must be usable only from the moment it was *published*, not the period it describes. Revised data (most macro, restated fundamentals) is unsafe unless vintages are kept. |
| **History depth** | E3 evaluates on ~10 years; two OOS windows need real history. |
| **Survivorship** | Delisted symbols must be present, or backtests are biased upward (E3 protocol §6 limitation). |
| **Commercial rights** | Most free tiers forbid production/commercial use. Enterprise needs a licence that covers storage, derived signals, and display. |
| **New information for E3** | E3 has only genuinely tested **own-price** signals so far (see §7). A source is valuable for E3 only if it adds an axis not yet tested. |

Legend: ✅ good fit · ⚠️ usable with caveats · ❌ not suitable for that tier.

---

## 2. The structural finding

| Source type | Free? | Enterprise-licensable? | Implication |
|---|---|---|---|
| **Government / regulator** (SEC, CFTC, EIA, FINRA, FRED/ALFRED, US Treasury) | ✅ | ✅ public data | Use for both POC **and** enterprise. These are the cheapest durable foundation. |
| **Commercial vendor free tier** (Alpha Vantage, Finnhub, NewsAPI, FMP, Tiingo, Polygon/Massive free) | ✅ | ❌ mostly personal / dev-only | POC only. Each has a paid tier that *is* licensable — that's the upgrade path. |
| **Unofficial scrapes** (yfinance, Google Trends via pytrends) | ✅ | ❌ | Exploration only. **yfinance is ArthaAI's current primary price source and must be replaced before enterprise** — its own README says the Yahoo data is for personal use. |
| **Institutional vendors** (LSEG, Bloomberg, FactSet, RavenPack, Kpler) | ❌ | ✅ | Enterprise only. Quote-based, typically five to six figures per year‡. |

Bottom line: **price/OHLCV data is the one category you will definitely have to buy** for enterprise.
Fundamentals, positioning, energy, and macro can largely stay on free government sources.

---

## 3. Market prices (OHLCV)

| Source | History | Survivorship | Free-tier limits | Commercial on free tier | Paid / enterprise path | POC | Ent. |
|---|---|---|---|---|---|---|---|
| **yfinance** *(current)* | Decades | ❌ no delisted | Unofficial; undocumented throttling | ❌ personal use | None — replace | ⚠️ | ❌ |
| **London Strategic Edge** *(current)* | ~2y on free plan (per STATUS_REPORT) | ❌ | Free plan: candles only | ‡ check terms | Paid plan (macro/options) | ⚠️ | ‡ |
| **Tiingo** | Decades (EOD) | ❌ | 500 unique symbols/month†; hourly cap unclear (50 or 500)†; no fundamentals/news on free | ❌ | Paid "Power" ~$30/mo† | ✅ fits 73-symbol universe | ⚠️ small-scale |
| **Alpaca** | Since 2016 | ❌ | Free plan: 200 historical calls/min; free bars are **IEX-only** (a subset of market volume) | ⚠️ tied to brokerage account | Algo Trader Plus $99/mo (all US exchanges) | ⚠️ IEX-only bars skew volume | ⚠️ |
| **Polygon.io → Massive** | 2y on free | ❌ | 5 calls/min, EOD only† | ❌ | Starter $29/mo, Developer $79, Advanced $199/mo, priced per asset class† | ⚠️ too little history | ✅ |
| **Twelve Data** | Varies | ❌ | 800 calls/day, 8/min† | ❌ | Paid plans, no daily cap† | ⚠️ | ⚠️ |
| **Financial Modeling Prep** | Limited on free† | ❌ | 250 calls/day, 500 MB / 30 days† | ❌ | Starter (5y) → Premium (30y+)† | ⚠️ | ⚠️ |
| **Alpha Vantage** | Free returns ~100 recent daily points† | ❌ | **25 calls/day**, 5/min† | ❌ | From $49.99/mo† | ❌ too restrictive | ⚠️ |
| **EODHD** | Decades | ❌ | 20 calls/day† | ❌ | Paid plans ~100k calls/day† | ❌ | ⚠️ |
| **Norgate Data** | Decades | ✅ **includes delisted** | Paid only; 21-day trial† | — | ~$35/mo to ~$630/yr depending on tier† | — | ✅ research-grade, cheapest survivorship fix |
| **Sharadar** (Nasdaq Data Link) | Prices since 1998, fundamentals since 1990‡ | ✅ (S&P 500 membership history since 1957‡) | Paid | — | Subscription‡ | — | ✅ |
| **Databento** | Deep, tick-level | ✅ | Pay-as-you-go by GB; **$125 free credit** on signup | ✅ licensed | Usage-based; subscriptions reportedly from ~$199/mo† | ✅ via credit | ✅ institutional-grade |
| **LSEG / Bloomberg / FactSet** | Full | ✅ | — | — | Quote-based‡ | — | ✅ |

**Pick for POC:** keep yfinance for exploration, add **Tiingo free** as the independent price cross-check
that the readiness checklist requires ("sample reconciliation against an independent source").
**Pick for enterprise:** **Norgate or Sharadar** for survivorship-free research history (cheap), plus
**Databento or Massive paid** for the licensed production feed.

---

## 4. Fundamentals & corporate events

| Source | PIT | Free-tier limits | Commercial | Enterprise path | POC | Ent. |
|---|---|---|---|---|---|---|
| **SEC EDGAR XBRL** *(in use: `value` signal)* | ✅ by filing date | Free, keyless, **10 req/s**, User-Agent with contact required; nightly bulk ZIPs | ✅ public data | Stays free | ✅ | ✅ |
| **SEC 8-K filings** (material events) | ✅ by filing timestamp | Same as above | ✅ | Stays free | ✅ | ✅ |
| **Financial Modeling Prep** | ⚠️ restatements | 250/day† | ❌ | Paid tiers† | ⚠️ | ⚠️ |
| **Finnhub** | ⚠️ | ~60 calls/min†; fundamentals on free tier disputed† | ❌ non-commercial† | Paid plans† | ⚠️ | ⚠️ |
| **Sharadar SF1** | ✅ point-in-time | Paid | — | Subscription‡ | — | ✅ |
| **Compustat PIT / FactSet** | ✅ | — | — | Quote-based‡ | — | ✅ |
| **Analyst estimate revisions** (LSEG I/B/E/S, FactSet, Zacks) | ✅ | **No credible free source**‡ | — | Quote-based‡ | — | ✅ |

**Pick:** **SEC EDGAR** for both tiers. Estimate revisions are a historically strong axis but **only
available paid** — a candidate for the first data purchase *if* free axes are exhausted properly.

---

## 5. News & sentiment

| Source | History | PIT | Free-tier limits | Commercial | Enterprise path | POC | Ent. |
|---|---|---|---|---|---|---|---|
| **GDELT 2.0** | Event DB since Feb 2015 (archives to 1979); updates every 15 min | ✅ by publish time | Free, no key | ✅ "unlimited… commercial" with citation and link back (secondhand quote†) | Stays free; GDELT Cloud is a separate paid product | ✅ | ✅ |
| **SEC 8-K** | Decades | ✅ | Free | ✅ | Stays free | ✅ | ✅ |
| **NewsAPI.org** | **1 month** on free | ✅ | 100 req/day, 24h delay | ❌ dev/test only | Business $449/mo, 5y history† | ❌ too short | ⚠️ |
| **Finnhub company news** | Limited‡ | ✅ | ~60/min† | ❌ | Paid† | ⚠️ | ⚠️ |
| **Alpha Vantage News & Sentiment** | ‡ | ✅ | 25/day total† | ❌ | Paid† | ❌ | ⚠️ |
| **RavenPack / LSEG MarketPsych / Dow Jones / Benzinga** | Deep | ✅ | — | — | Quote-based‡ | — | ✅ |

**Pick:** **GDELT** (event tone/volume per entity) + **SEC 8-K** for POC — both free *and*
commercially usable, so the work carries over. Paid sentiment (RavenPack-class) only if GDELT shows
signal under the protocol.

---

## 6. Macro, positioning, energy & market-structure (the untested exogenous axes)

These are the most interesting rows for E3: **free, official, point-in-time, and never tested.**

| Source | What it adds | Cadence / PIT lag | Free access | Commercial | Best for (universe) | E3 tested? |
|---|---|---|---|---|---|---|
| **CFTC Commitments of Traders** | Speculator vs. commercial positioning in futures | Weekly; Tuesday data released **Friday 3:30pm ET** | Free since 1995; Socrata API (Public Reporting Environment) | ✅ public | **GLD, SLV, USO, DBC** (commodity ETFs) | ❌ never |
| **EIA weekly petroleum (WPSR)** | Crude/gasoline inventories, Cushing stocks | Weekly; reported release Wednesday 10:30am ET† | Free API key; coverage from 1990† | ✅ public | **USO, XOM**, energy names | ❌ never |
| **FINRA equity short interest** | Short positioning per stock | Twice monthly; published **7 business days** after settlement | Free web grid, 5 rolling years; **no documented official API** (file download/scrape) | ✅ public‡ | Equities subset | ❌ never |
| **SEC Form 4** (insider transactions) | Insider buying/selling | Filed within 2 business days‡ | Free via EDGAR | ✅ public | Equities subset | ❌ never |
| **SEC 13F** | Institutional holdings | Quarterly, 45-day lag‡ | Free via EDGAR | ✅ public | Equities subset | ❌ never |
| **FRED + ALFRED** *(FRED in use)* | Rates, spreads, activity; **ALFRED keeps vintages** so revised series become PIT-safe | Daily → monthly | Free API key | ✅ mostly (some series carry third-party copyright — check per series‡) | All | ⚠️ term spread only — **and that run was voided, see §7** |
| **Cboe VIX / VIX3M indices** | Implied-vol level and term structure | Daily | Free historical CSVs‡ | ⚠️ check Cboe terms‡ | All (market regime) | ❌ never |
| **Kpler / Vortexa / Ursa** (cargo, satellite) | Physical commodity flows | Near-real-time | — | Paid: $5k–40k/mo (per the architecture doc's Stage 4) | Commodity ETFs | — |

**Pick:** these are the **highest-value free sources for E3**. CFTC COT and EIA map directly onto the
commodity ETFs that the Alt_Agent stub was meant to cover — they are the free, legal precursor to the
$5k–40k/mo Kpler/Ursa feeds.

---

## 7. Important: what E3 has actually tested so far (corrected 2026-10-21)

Before buying any data, note that the E3 verdict ("11 variants, 4 axes, all fail → it's a data problem")
is **not supported by the recorded runs**. Two harness problems were found while preparing this
comparison:

1. **5 of the 11 variants never ran their own signal.** `promote-sweep` only builds a signal map for
   `ic_composite`, `tsmom`, and `xsmom` (`arthaai/cli.py`, the `if signal in (...)` check before the
   sweep). `regime`, `regime_tsmom`, `value`, `macro`, and `macro_tsmom` silently fell back to the
   **trend** baseline. Evidence: their recorded sweep files are row-for-row identical to
   `sweep10_trend.txt` (73/73 rows; 33/34 for `value`), and a live re-run today reproduces
   identical output for `--signal trend|regime|macro|value`.
2. **The "10-year" sweeps most likely used only ~2 years.** `promote-sweep` defaults to `--limit 520`
   bars and none of the recorded commands pass `--limit`. The recorded "10-year" GLD trend row
   (B&H +30.65%, Sharpe 1.50) matches a local `--limit 520` run (+30.66%, 1.52), not a full-history
   run (+41.08%).

So the honest state is: **~6 own-price variants on ~2 years of data have failed.** The market-regime,
fundamental (SEC EDGAR), and macro axes are **untested**, and the 10-year robustness claim is unverified.
None of the free sources in §6 has been tried.

---

## 8. Recommended sequence (for your decision)

| Step | What | Cost | Why this order |
|---|---|---|---|
| 1 | Fix the two harness issues; re-run the 5 voided variants and the original 6 with an explicit 10-year `--limit` | $0 | The current verdict is unreliable; nothing should be bought on it |
| 2 | XGBoost over the factor zoo, pre-registered (the architecture doc's own recipe) | $0 | Settles the blueprint's open question on existing data |
| 3 | New free exogenous axes: **CFTC COT** (commodities), **EIA** (energy), **Form 4 + FINRA short interest** (equities), **GDELT** tone, **VIX term structure** | $0 | Free, PIT-safe, enterprise-licensable, never tested |
| 4 | **Norgate** (~$35/mo†) for survivorship-free history, to stress-test any step 1–3 survivor | Low | Removes the protocol's biggest declared bias cheaply |
| 5 | Only if something survives 1–4: licensed price feed (Databento/Massive), then estimate revisions or paid sentiment | Medium → high | Spend follows evidence, per the architecture doc's staged plan |

**POC stack (free):** yfinance (exploration) + Tiingo free (cross-check) + SEC EDGAR + GDELT + CFTC COT +
EIA + FINRA short interest + FRED/ALFRED.

**Enterprise stack (paid, when promoted):** Databento or Massive paid (licensed prices) + Norgate or
Sharadar (survivorship-free research) + the same government sources (still free) + paid estimates/sentiment
only if their axis proves out.

---

## Sources

- Alpha Vantage limits: [macroption](https://www.macroption.com/alpha-vantage-api-limits/), [qveris pricing guide](https://qveris.ai/guides/alpha-vantage-pricing-alternative/?lang=zh), [improvado](https://improvado.io/docs/alpha-vantage-troubleshooting)
- Polygon/Massive: [apicostcalc rebrand](https://apicostcalc.com/blog/polygon-massive-rebrand-api-pricing.html), [qveris Polygon pricing](https://qveris.ai/guides/polygon-pricing-optimized/), [apis.io plans](https://apis.io/plans/polygon/polygon-plans-pricing/)
- Tiingo: [QuantStart](https://www.quantstart.com/articles/evaluating-data-coverage-with-tiingo/), [Wealth-Lab forum](https://wl6.wealth-lab.com/Forum/Posts/Why-Tiingo-works-on-some-but-fails-on-other-symbols-40475)
- Financial Modeling Prep: [FMP plan guide](https://site.financialmodelingprep.com/insights/platform/how-to-choose-the-right-financial-modeling-prep-plan-for-your-workflow), [fitgap](https://us.fitgap.com/products/financial-modeling-prep)
- Norgate: [Norgate overview](https://norgatedata.com/), [NexusFi](https://nexusfi.com/d/data-providers/norgate-data/), [QuantConnect forum](https://www.quantconnect.com/forum/discussion/21226/would-you-pay-for-cheap-point-in-time-s-amp-p-500-data-survivorship-bias-free/), [MarketParquet](https://marketparquet.com/vs/norgate)
- Databento: [usage-based pricing & credits](https://databento.com/docs/knowledge-base/new-users/usage-based-pricing-and-data-credits), [pricing](https://databento.com/pricing)
- Sharadar: [QuantRocket Sharadar](https://www.quantrocket.com/sharadar/)
- EODHD / Twelve Data: [EODHD forum](https://forum.eodhd.com/t/pay-as-your-need/970), [CodeWords Twelve Data guide](https://www.codewords.ai/blog/twelve-data-api)
- Alpaca: [Alpaca Market Data docs](https://docs.alpaca.markets/docs/about-market-data-api), [Alpaca forum](https://forum.alpaca.markets/t/market-historical-data-discrepancies/14059)
- yfinance: [yfinance README](https://github.com/ranaroussi/yfinance)
- GDELT: [jwatte.com on GDELT terms](https://jwatte.com/blog/gdelt-open-data-kalev-leetaru/), [Aalto datahub](https://datahub.aalto.fi/en/data-sources/the-gdelt-database)
- NewsAPI: [newsapi.org pricing](https://newsapi.org/pricing)
- Finnhub: [apicostcalc Finnhub](https://apicostcalc.com/finnhub.html), [qveris free stock API comparison](https://qveris.ai/guides/stock-api-free-comparison/)
- SEC EDGAR: [SEC — Accessing EDGAR Data](https://www.sec.gov/os/accessing-edgar-data), [EDGAR API guide](https://arkolith.com/blog/sec-edgar-api-guide)
- CFTC COT: [CFTC press release 8612-22](https://www.cftc.gov/PressRoom/PressReleases/8612-22), [About the COT reports](https://www.cftc.gov/MarketReports/CommitmentsofTraders/AbouttheCOTReports/index.htm)
- EIA: [OilPriceAPI EIA v2 guide](https://www.oilpriceapi.com/eia-api)
- FINRA: [FINRA Equity Short Interest](https://www.finra.org:443/finra-data/browse-catalog/equity-short-interest), [Regulatory Notice 21-19](https://www.finra.org/sites/default/files/2021-06/Regulatory-Notice-21-19.pdf)
- ALFRED: [fredapi](https://github.com/mortada/fredapi), [alfred R package](https://onnokleen.r-universe.dev/alfred/doc/manual.html)
