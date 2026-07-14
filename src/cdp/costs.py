"""
A CREDIBLE cost model.

WHY THE 5bps FLAT MODEL IS A LIE
    It prices a trade in SNX identically to a trade in BTC. Real cost has three
    parts, and only the first is flat:

      1. FEE     -- Binance taker ~4.5bps, maker ~2bps.  Known. Small.
      2. SPREAD  -- you cross the bid-ask. ~1bp on BTC, 5-20bps on thin alts.
                    THIS is what the flat model gets wrong.
      3. IMPACT  -- your own order moves the price. Zero at $1k, brutal at $1m.

    The strategy's P&L is concentrated in SNX, THETA, ICP, CRV -- precisely the
    names where 5bps flat is most wrong. So the cost model is not a detail; it
    may be the whole result.

HOW WE ESTIMATE SPREAD WITHOUT AN ORDER BOOK
    Binance Vision publishes no historical L2. But CORWIN & SCHULTZ (2012,
    Journal of Finance) derive the spread from HIGH-LOW RANGES alone.

    Intuition: a period's high-low range contains BOTH true volatility AND the
    spread. Volatility scales with time (2 periods -> ~2x variance); the spread
    does NOT (it is paid once either way). Comparing a single-period range to a
    two-period range therefore separates them.

    This is the accepted estimator when you have OHLC and no quotes.

IMPACT: the SQUARE-ROOT LAW (Almgren et al.)
    impact ~ sigma * sqrt(Q / V)
    Q = our order size, V = period volume, sigma = period volatility.
    Empirically validated across equities, futures and crypto.

    python -m cdp.costs
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import store

TAKER_FEE = 0.00045     # Binance USDT-M taker, standard tier
MAKER_FEE = 0.00020


def corwin_schultz(df: pd.DataFrame) -> pd.Series:
    """
    Corwin-Schultz (2012) high-low spread estimator, per symbol.

    beta  = sum of two consecutive single-period log(H/L)^2
    gamma = log(H2/L2)^2 over the COMBINED two-period range
    alpha = (sqrt(2*beta) - sqrt(beta)) / (3 - 2*sqrt(2))
            - sqrt(gamma / (3 - 2*sqrt(2)))
    S     = 2*(exp(alpha) - 1) / (1 + exp(alpha))

    Negative estimates are set to zero (the paper's own recommendation --
    they arise from estimation noise, not negative spreads).
    """
    out = []
    for sym, g in df.groupby("symbol"):
        g = g.sort_values("ts")
        hi, lo = g["high"], g["low"]

        b1 = np.log(hi / lo) ** 2
        beta = b1 + b1.shift(1)

        hi2 = pd.concat([hi, hi.shift(1)], axis=1).max(axis=1)
        lo2 = pd.concat([lo, lo.shift(1)], axis=1).min(axis=1)
        gamma = np.log(hi2 / lo2) ** 2

        k = 3 - 2 * np.sqrt(2)
        alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
        S = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
        S = S.clip(lower=0)

        out.append(pd.DataFrame({"ts": g["ts"], "symbol": sym, "spread": S}))

    return pd.concat(out).reset_index(drop=True)


def build_cost_panel(capital_usd: float = 100_000) -> pd.DataFrame:
    """
    Per (bar, symbol) round-trip cost in fractional terms.

    cost = fee + half_spread + impact
    """
    px = store.read("perp_klines")

    cs = corwin_schultz(px)
    d = px.merge(cs, on=["ts", "symbol"], how="left")

    # smooth the spread estimate -- CS is noisy bar-to-bar, but the UNDERLYING
    # liquidity of an asset changes slowly. 7d median is robust to outliers.
    d["spread_s"] = (d.groupby("symbol")["spread"]
                       .transform(lambda s: s.rolling(24*7, min_periods=24)
                                             .median()))
    d["spread_s"] = d.groupby("symbol")["spread_s"].ffill().fillna(0.001)

    # realised vol, for the impact term
    d["ret"] = d.groupby("symbol")["close"].pct_change()
    d["sigma"] = (d.groupby("symbol")["ret"]
                    .transform(lambda s: s.rolling(24*7, min_periods=24).std()))

    # SQUARE-ROOT IMPACT. Order size assumed = full position turnover at the
    # given capital. Conservative: assumes we cross in one go.
    d["dollar_vol"] = d["quote_volume"].replace(0, np.nan)
    participation = capital_usd / d["dollar_vol"]
    d["impact"] = d["sigma"] * np.sqrt(participation.clip(0, 1))
    d["impact"] = d["impact"].fillna(0.0)

    d["cost_taker"] = TAKER_FEE + d["spread_s"] / 2 + d["impact"]
    d["cost_maker"] = MAKER_FEE + d["impact"]      # maker earns the spread

    return d[["ts", "symbol", "spread_s", "sigma", "dollar_vol",
              "impact", "cost_taker", "cost_maker"]]


def run() -> None:
    pd.set_option("display.width", 200)
    print("=" * 84)
    print("COST MODEL -- Corwin-Schultz spread + square-root impact")
    print("=" * 84)

    for cap in [10_000, 100_000, 1_000_000]:
        c = build_cost_panel(cap)
        recent = c[c.ts >= "2025-01-01"]
        s = (recent.groupby("symbol")
                   .agg(spread_bps=("spread_s", lambda x: x.mean()*1e4/2),
                        impact_bps=("impact", lambda x: x.mean()*1e4),
                        cost_bps=("cost_taker", lambda x: x.mean()*1e4),
                        dvol_musd=("dollar_vol", lambda x: x.mean()/1e6))
                   .sort_values("cost_bps", ascending=False))
        print(f"\n--- capital = ${cap:,}  (2025-26 average, one-way, bps) ---")
        print(s.head(6).to_string(float_format=lambda x: f"{x:8.2f}"))
        print("   ...")
        print(s.tail(3).to_string(float_format=lambda x: f"{x:8.2f}"))
        print(f"   universe mean cost: {s.cost_bps.mean():.2f} bps  "
              f"(the flat model assumed 5.00)")

    print("\n" + "=" * 84)
    print("  The flat 5bps model is what every result so far assumed.")
    print("  Compare that to the numbers above, especially for the thin names")
    print("  where this strategy makes its money.")
    print("=" * 84)


if __name__ == "__main__":
    run()
