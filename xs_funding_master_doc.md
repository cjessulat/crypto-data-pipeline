# Cross-Sectional Funding Strategy — Master Document

**Status:** Research complete on v2. Not deployed. Three material risks unresolved.
**Last updated:** 2026-07-13

---

## 1. What we set out to do

Explore systematic strategies outside TSMOM. Scored ~7 candidate strategy
families from the literature. Highest-scoring was **perpetual funding carry**
(8.5/10) on grounds of: observable-ex-ante signal, free clean data,
delta-neutral construction, and strong academic grounding (Koijen, Moskowitz,
Pedersen & Vrugt, *"Carry"*, JFE 2018).

**We did not build what we set out to build.** See §4.

---

## 2. Infrastructure (done, working)

Shared data pipeline. Lives on the DigitalOcean droplet, read by both this
project and the TSMOM project.

| | |
|---|---|
| **Repo** | `github.com/cjessulat/crypto-data-pipeline` |
| **Code (VPS)** | `/opt/cdp` |
| **Data (VPS)** | `/opt/marketdata` |
| **Code (Windows)** | `C:\Users\Chris\crypto-data-pipeline` |
| **Cron** | 01:15 UTC daily, verified |

**Datasets**

| dataset | source | cadence | coverage |
|---|---|---|---|
| `spot_klines` | Binance Vision (bulk) | 1h | 2019-09 → present |
| `perp_klines` | Binance Vision (bulk) | 1h | 2020-01 → present |
| `funding` | Binance REST | 8h | 2019-09 → present |
| `metrics` (OI) | Binance Vision (bulk) | 5m | **~31 days only** |

26 crypto perps. ~3.3M rows, ~201 MB.

**The OI limitation is structural.** Binance retains ~31 days and nobody sells
the history cheaply. Cron accumulates it going forward — usable in ~6 months.
No OI-based signal can be backtested today.

### Bugs found and fixed (all would have silently corrupted results)

1. **Microsecond timestamp switchover.** Binance moved spot klines to
   microsecond epochs on 2025-01-01; futures stayed in milliseconds. Naive
   parsing puts 2025+ data in the year 57000, where pandas silently drops it.
   Fixed with magnitude sniffing + a sanity gate that crashes loudly.
2. **Parquet schema drift across 1,384 files.** `ts` was `timestamp[ms]` in
   some partitions and `timestamp[us]` in others; `volume` was `int64` where
   values happened to be whole numbers. Blocked all cross-partition reads.
   Fixed by pinning explicit Arrow schemas on read and write.
3. **Funding history destroyed on every nightly run.** ← *the dangerous one.*
   The daily job rewrote the whole funding partition using a 2-month lookback,
   silently deleting six years of history and reporting success. Caught only
   because we tested the cron script before trusting it.

> **The lesson from #3 is the important one.** It didn't crash. It didn't warn.
> It deleted the data and said "done." That is the failure mode that matters in
> systematic trading — not the error, but the silent corruption that produces a
> beautiful, meaningless backtest.

---

## 3. What the funding data actually says

Six years, 26 assets.

**The naive carry trade is dead.**

| year | mean annualised funding |
|---|---|
| 2021 | **+35.9%** |
| 2022 | −3.7% |
| 2023 | +6.1% |
| 2024 | +11.6% |
| 2025 | +3.1% |
| 2026 | **+0.7%** |

The often-quoted "+10% funding yield" is an artifact of 2021. By 2026 the gross
yield is ~0.7% against a ~2.4% annual cost for monthly taker rebalancing.
**Long-spot/short-perp carry is now a guaranteed loser.** Do not build it.

**But two things survived:**

1. **Persistence.** Funding autocorrelation is 0.68–0.85 at one lag, still
   0.14–0.32 a month out. Funding is *highly* forecastable — unlike price,
   where autocorrelation is ~0. This is the necessary condition for any carry
   strategy to have an edge.
2. **Cross-sectional dispersion.** The *level* has been arbitraged away. The
   *spread across assets* has not. BNB funding is habitually **negative**
   (`pct_pos` = 25%) while LTC is habitually positive (+15%/yr). That
   structural difference is persistent and is what we ended up harvesting.

---

## 4. What we actually built — and what it turned out to be

**Design:** rank assets by trailing 7-day mean funding. Long the low-funding
names, short the high-funding names. Dollar-neutral. Continuous z-scored
weights, daily rebalance, no-trade band, 15% vol target, 5bps taker.

**We set out to build funding carry. We accidentally built short-term reversal.**

Funding is not functioning as a cash flow here. It's functioning as a
**crowding detector**. Deeply negative funding means the market has given up on
an asset. You buy it, and the money is made on the *bounce* — not the coupon.

This is very close to Nagel, *"Evaporating Liquidity"* (RFS 2012): you are
being paid to provide liquidity to forced sellers. That was idea #3 on the
original list, scored 7/10.

### Results (holdout, 2025-01 → 2026-06, never tuned on)

```
                 sharpe   return    vol    maxdd
TRAIN (seen)      1.27    +20.8%   16.3%   -20.9%
HOLDOUT (unseen)  2.45    +39.9%   16.3%    -7.3%
```

**P&L decomposition (holdout):**

```
price leg    +37.30%   <- 94% of P&L. This IS the strategy.
funding leg   +6.01%   <-  6%. Nice, but not the point.
```

**The funding leg in isolation:** +2.55%/yr net of cost, at 0.30% vol —
**Sharpe 8.57.** Extraordinary consistency, and exactly what theory predicts
for a near-deterministic cash flow. But **+2.55%/yr is far too small to run a
business on**, and levering a short-vol trade is how people get liquidated.

### Robustness

| test | result | verdict |
|---|---|---|
| Lookahead (340k weights, causal rebuild) | **0 differences** | clean |
| Drop 10 best days | Sharpe 2.54 → 1.56 (61% retained) | concentrated, survives |
| Leave-one-out (26 symbols) | worst case Sharpe 2.00 (81% of base) | **robust** |
| Parameter surface | flat, 0.65–1.05 across 3d–30d | not overfit |
| Every year 2020–2026 | funding leg **positive in all 7** | real mechanism |

**Attribution:** top 3 symbols (SNX, THETA, XLM) = 61% of holdout P&L. All
mid-cap, high-beta, beaten-down alts. In every one, the price leg is 15–40x the
funding leg.

---

## 5. Errors made (documented so they aren't repeated)

**5.1 — I scored carry 8.5/10 and it was wrong.** The arbitrage-compression
criticism I listed as a "primary criticism" turned out to be the whole story.
Should have checked the yield trend before scoring, not after.

**5.2 — Every pre-registered lever made it worse.**

```
config                              sharpe   return   turnover
v1 base (hourly, no band, no vol)    1.79    +48.1%     93.9
+ daily rebalance                    1.72    +45.7%     73.0
+ no-trade band                      1.70    +45.0%     67.1
+ vol target (FULL v2)               1.27    +20.7%     48.5
```

I pre-registered a bundle of cost-reduction levers on the theory that costs
were killing the strategy. On the 10-asset universe they were (−6.7%/yr). On
the 26-asset universe they never were (−3.4%). **I carried an assumption from
the small-universe result into the large-universe world without rechecking it.**
The Sharpe improvement from v1 → v2 came *entirely* from expanding the universe.
The levers I added actively hurt.

**5.3 — Reported v2 as though the levers earned the improvement.** They didn't.
Corrected once the ablation was visible.

**5.4 — Predicted the holdout would degrade. It nearly doubled (1.27 → 2.45).**
Being wrong in this direction is the more dangerous one; it prompts the check
below.

---

## 6. Open risks — none resolved

Ordered by how likely they are to kill the strategy.

### 6.1 Survivorship bias — **the most dangerous**
**MATIC, FTM, EOS and MKR were all major perps. All now delisted.** That is 4 of
a 45-name hand-picked list (~9%), and there are certainly more we never thought
to name.

This matters *disproportionately* here because **the strategy's edge is buying
beaten-down altcoins.** The beaten-down alts that kept falling and died are not
in the dataset. We are testing "buy the dip" on a universe from which the dips
that never recovered have been removed.

**Every number in §4 is an optimistic upper bound.** This could be fatal and it
has not been quantified.

### 6.2 The cost model is not credible
5bps flat, no slippage, no market impact — applied to SNX, THETA, ICP, CRV.
These are thin books. The un-levered config that "wins" the ablation has **94x
annual turnover**, and it wins precisely because the cost model flatters it most.
No conclusion about optimal turnover can be drawn until this is fixed.

### 6.3 Regime dependence — untested
The holdout (2025–26) was choppy and mean-reverting for altcoins — the *exact*
regime a contrarian strategy needs. Sharpe 2.45 may be regime luck. In a
sustained altcoin downtrend, this strategy bleeds. **We have not tested a
hostile regime because the holdout didn't contain one.**

---

## 7. The honest summary

There is a **real, mechanically-grounded, persistent funding edge**: +2.55%/yr
at Sharpe 8.57, positive in every year since 2020. It is too small to trade on
its own.

Wrapped around it is a **contrarian altcoin strategy** that produced Sharpe 2.45
out of sample and survived every robustness test we threw at it — but whose
edge is concentrated in illiquid names, whose costs are not credibly modelled,
and which has only been tested in a regime that suits it.

**It is not ready for capital.** The next honest step is to attack §6.1 — if
survivorship bias accounts for most of the price leg, there is no strategy here,
only a story about the coins that happened to survive.

---

## 8. Next steps (in order)

1. **Quantify survivorship bias.** Rebuild the universe point-in-time, including
   delisted names. Data for dead perps is hard to get — this is the main
   obstacle. Without it, no result here can be trusted.
2. **Build a credible cost model.** Volume- and spread-aware, per-asset. Kill
   the 5bps flat assumption.
3. **Test a hostile regime.** Specifically: sustained altcoin downtrend.
4. **Only then** revisit whether this is a sleeve worth deploying.

---

## Appendix — code

All in `/opt/cdp/src/cdp/`:

| module | purpose |
|---|---|
| `config.py` | universe, paths, dataset definitions |
| `binance_vision.py` | bulk downloader (checksums, timestamp normalisation) |
| `funding.py` | funding REST downloader |
| `store.py` | parquet store — **the only public read interface** |
| `ingest.py` | the CLI you actually run |
| `quality.py` | data-quality checks — **run before every backtest** |
| `repair.py` | one-off schema repair |
| `funding_econ.py` | descriptive funding economics |
| `xs_funding.py` | v1 strategy + backtest engine |
| `xs_v2.py` | v2 (continuous weights, band, vol target) |
| `forensics.py` | attribution, leave-one-out, drop-best-days |
| `holdout.py` | the one-shot holdout test |
| `leak_test.py` | causal-rebuild lookahead check |
| `holdout_forensics.py` | forensics on the holdout |

**Backtest engine was validated against synthetic ground truth**: recovered
+32.64% against a known +32.85%, gross exposure 1.00, net exposure 0.000.
Noise floor on the price leg measured at **±7%** — any price-leg result inside
that band is indistinguishable from luck.
