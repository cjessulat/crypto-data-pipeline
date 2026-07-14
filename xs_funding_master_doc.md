# Cross-Sectional Funding Strategy — Master Document

**Status:** Research complete on Binance. Hyperliquid discovery in progress.
**Not deployed. Not ready for capital.**
**Last updated:** 2026-07-14 (session 2)

---

## THE HEADLINE

**1. The strategy resists all improvement — nine attempts, nine rejections.**
Not bad luck. Each failed for a *different, mechanistically coherent* reason.
The simple config is not a local optimum we settled for. **It is the strategy.**

**2. Funding is dying on Binance but ALIVE on Hyperliquid.**
Binance funding leg: +33%/yr (2020) → +5%/yr (2025). Arbitraged away.
Hyperliquid, same assets, 3-year window: **+13% to +21%/yr**, with a **30-point
cross-sectional spread**. And HL is the venue we intend to trade on.

---

## 1. THE STRATEGY (current best config)

```
signal      : trailing 7d mean funding, cross-sectionally z-scored, LAGGED
weights     : continuous, proportional to z, dollar-neutral, gross = 1.0
liq tilt    : 0.25  (mild tilt toward liquid names)
rebalance   : daily, with a 0.005 no-trade band
vol target  : NONE  (rejected — see §3)
exits       : NONE  (rejected — see §3)
costs       : Corwin-Schultz spread + square-root impact, per-asset
universe    : 26 Binance perps
```

**Performance ($5k capital, honest costs):**

| | Sortino | Calmar | Return | MaxDD |
|---|---|---|---|---|
| **TRAIN 2020–24** (hostile regimes) | 1.62 | 1.32 | +32.0% | −24.3% |
| **HOLDOUT 2025–26** (benign) | 1.36 | 1.11 | +16.3% | −14.7% |

**Plan around the holdout number (+16%), not the train number (+32%).** The
train figure assumes a funding yield that no longer exists on Binance.

**One losing year in seven.** Worst was 2022 at −0.7% — the year crypto
collapsed, the funding leg (+22.8%) almost exactly offset a −11.7% price leg.
The diversification working as designed.

---

## 2. WHAT THE STRATEGY ACTUALLY IS

**Not funding carry.** We set out to build carry and accidentally built
**short-term reversal / liquidity provision**.

- **84% of P&L comes from the LONG leg** — buying hated assets
- Profits when **cross-sectional dispersion** rises, NOT when the market crashes
  (market return was ~0% on every one of its 10 best days)
- Funding is a **crowding detector**, not a cash flow
- Payoff is **episodic**: top 10 days = 130% of holdout P&L (without them it
  loses money). Those days span 5 months and 22 assets — *lumpy*, not one event.

Closest literature: **Nagel, "Evaporating Liquidity" (RFS 2012)** — you are paid
to provide liquidity to forced sellers.

**The funding leg alone:** +2.55%/yr at 0.30% vol — **Sortino 8.57.**
Extraordinary consistency, exactly as theory predicts for a near-deterministic
cash flow. **Far too small to trade on its own.**

---

## 3. NINE REJECTIONS — and why each failed

| # | Intervention | Result | Why |
|---|---|---|---|
| 1 | Vol targeting (Moreira-Muir) | Calmar 1.97 → 0.99 | scaled the bet; Sortino sees through it |
| 2 | Liquidity weighting (full) | Sortino 1.68 → 0.26 | removed the edge's source |
| 3 | Dispersion sizing | Sortino +0.02 (noise) | scaled the bet |
| 4 | Asymmetric long/short | holdout → NEGATIVE | added market beta (β 0.00 → 0.96) |
| 5 | Profit targets / stops / time stops | Sortino halved | truncated the fat tail |
| 6 | Funding-normalisation exits | **worst of all** | funding normalises WHEN THE RECOVERY STARTS — it sells the bounce |
| 7 | Trailing stops | maxDD −24% → −37..−52% | sold after peak, missed continuation |
| 8 | Vol-normalised stops | all worse | sold the bottom |
| 9 | Blended crowding signals | **catastrophic** | see below |

### The two deepest findings

**Exits make drawdowns WORSE.** Every exit variant *increased* max drawdown
(−24% → −37..−52%). I hypothesised this was because exits break
dollar-neutrality, so I built a re-hedging version to test it. **Re-hedging did
not help. My explanation was wrong.** The truth:

> **In a liquidity-provision strategy, the drawdown IS the edge.** You are paid
> precisely because most participants cannot hold through it. Any rule that
> reduces exposure to drawdown reduces exposure to the payoff. Stops don't
> reduce risk here — they convert temporary drawdowns into permanent losses.

**Funding is irreplaceable.** Every alternative crowding signal was not merely
useless but *catastrophically negative*:

```
funding only        Sortino +1.62   ret +32.0%
taker imbalance     Sortino -2.71   ret -49.2%   maxDD -92.7%
vol spike           Sortino -1.80   ret -48.8%   maxDD -93.5%
price extension     Sortino -2.15   ret -71.0%   maxDD -98.1%
```

Blends degrade **monotonically** with every drop of non-funding signal added.

> **Funding is a PAYMENT, not a pattern.** It is what one side is willing to
> *pay* the other to hold a position — revealed preference with money attached.
> Taker imbalance, volume, volatility, price extension are *activity* measures:
> they say what happened, not what anyone will pay.
>
> The edge is not "find crowded assets." It is **"find assets where people are
> paying you to take the other side."** The payment IS the edge.

---

## 4. THE HYPERLIQUID DISCOVERY (session 2's main result)

Binance funding is being competed away. Since no substitute *signal* exists
(§3), the only option is to find the same signal **elsewhere**.

**Same assets, same 3-year window:**

| venue | BTC funding, annualised |
|---|---|
| **Hyperliquid** | **+14.51%** |
| Bybit | +7.08% |
| OKX | (90 days of history only — unusable) |

**HL pays 2x Bybit.** Across the universe:

```
NEAR  +21.4%      ATOM   -2.2%
DOGE  +17.5%      BCH    -1.7%
AAVE  +17.0%      XLM    -0.5%
LINK  +16.0%      TRX    +2.1%
FIL   +15.9%      CRV    +2.5%
BTC   +14.6%      ICP    -8.9%
```

**A 30-point cross-sectional spread, with genuinely negative-funding names to
buy.** Binance in 2026: everything compressed to within basis points of zero.
**The cross-section we need is alive on HL and dead on Binance.**

Mechanism: HL is newer, retail-heavier, fewer institutional arbitrageurs. The
premium survives because the competition has not arrived.

### THE BLOCKER

| | Hyperliquid | Binance |
|---|---|---|
| Funding | 2023-05 → now ✓ | 2019-09 → now ✓ |
| **Prices** | **2025-12 → now** ✗ | 2019-09 → now ✓ |

**HL's API retains only ~5,000 candles (~7 months).** Verified directly:
requests for 2024-01, 2024-07, 2025-01, 2025-07 all return **zero bars**.
A native HL backtest is impossible today.

### THE URGENT ACTION — taken

**HL price data is PERISHABLE and cannot be backfilled.** `cdp.hl_daily` is now
in cron. Every day it does not run is a day of data permanently lost. In ~12
months this yields a native HL dataset.

---

## 5. WHAT I GOT WRONG (so it is not repeated)

**5.1** Scored carry 8.5/10 without checking the yield trend. The
arbitrage-compression criticism I listed as a footnote *was the whole story*.

**5.2** Pre-registered cost-reduction levers on the theory costs were killing
the strategy. On the 26-asset universe **they never were**. Carried an
assumption from the 10-asset world without rechecking. The v1→v2 improvement
came *entirely* from expanding the universe; my levers actively hurt.

**5.3** Predicted the holdout would degrade. It nearly *doubled* — an artifact
of the fake 5bps cost model. Under honest costs it degrades properly
(+32% → +16%), which is the healthy result.

**5.4** Let a 5bps flat cost model stand for three sessions. Wrong by **4–8x**,
and wrong in the worst way: it most understated the cost of exactly the thin
names (SNX 39bps, THETA 35bps, CRV 33bps) where the strategy makes its money.

**5.5** Predicted "size DOWN in dead periods" beats "size UP into episodes."
Backwards. Quiet periods are not dead weight.

**5.6** Explained the exit failures as "exits break the hedge." **Built a
re-hedging test that disproved my own explanation.** The truth is deeper: the
drawdown *is* the edge.

---

## 6. OPEN RISKS

### 6.1 Survivorship bias — RESOLVED (was the top risk)
Distressed positions contribute **−2% of P&L**, not +40%. Excluding them makes
the strategy *better* (Sortino 3.54 → 3.77). **Mildly deflating, not inflating.**
The lottery-winner hypothesis is dead.

### 6.2 Capacity ceiling — QUANTIFIED, and LOW

| capital | Sortino | return |
|---|---|---|
| $5k | 1.68 | +31.8% |
| $10k | 1.61 | +30.5% |
| $100k | 1.12 | +21.4% |
| $1m | likely negative | — |

Full liquidity-tilting **destroys** the edge (Sortino 1.68 → 0.26), proving the
ceiling is structural. **Small capital is a feature, not a limitation.**
Target: **under $10k.**

### 6.3 Fragility — REAL
Top 10 days = **130%** of holdout P&L. Expect **long flat stretches** punctuated
by violent gains. Psychologically hard to hold.

### 6.4 The edge is decaying — the existential risk
Funding leg: +33% → +5% over six years on Binance. §3 proves nothing replaces
it. **This strategy has a shelf life.** Hyperliquid may extend it — but the same
arbitrageurs will eventually arrive there too.

### 6.5 Regime dependence — UNTESTED
Holdout (2025–26) was choppy and mean-reverting: the ideal regime for a
contrarian book. Full-sample Calmar (1.20) vs holdout Calmar (5.43) — **that 4.5x
gap IS the regime effect.**

---

## 7. NEXT STEPS

**PRIORITY 1 — running**
HL nightly collector in cron. Perishable. Cannot be backfilled.

**PRIORITY 2 — the main open question**
Test the strategy on **HL funding + Binance prices**. A *proxy* backtest: it
tests whether the HL funding *signal* has predictive power. It does NOT tell us
HL *execution* costs — HL liquidity is thinner than Binance's.

**Key unknown: HL settles funding HOURLY** (24×/day vs Binance's 3×). Higher
frequency may *smooth* rates and collapse the cross-sectional dispersion we need,
even though the *averages* look dispersed.
**High average funding ≠ better strategy. The edge is dispersion, not level.**

**PRIORITY 3 — validation**
Reservoir (free S3, HL data from 2025-08) gives more HL history than the API.
Cross-check the proxy backtest against it.

**PRIORITY 4 — practical blockers before live capital**
- Minimum order sizes ($5k / 26 assets ≈ $190/position — check HL minimums)
- Build the paper trader; run it with no money for months
- Verify HL execution costs empirically

---

## Appendix — code

`/opt/cdp/src/cdp/` — committed to `github.com/cjessulat/crypto-data-pipeline`

**Pipeline:** `config` `binance_vision` `funding` `store` `ingest` `quality`
`repair` `venues` `hl_backfill` `hl_daily`

**Research:** `funding_econ` `xs_funding` `xs_v2` `forensics` `holdout`
`leak_test` `holdout_forensics` `survivorship` `costs` `rerun_real_costs`
`liq_weight` `dispersion` `disp_sizing` `asym` `exits` `exit_funding`
`exit_trail` `exit_volstop` `blend`

**Validation performed:**
- Backtest engine recovered **+32.64%** against a known synthetic truth of
  **+32.85%**; gross exposure 1.00, net 0.000
- Lookahead check: **340,704 weights rebuilt causally — ZERO differences**
- Price-leg noise floor measured at **±7%**; any price-leg result inside that
  band is indistinguishable from luck
