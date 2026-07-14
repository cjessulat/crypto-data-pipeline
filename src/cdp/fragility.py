"""
WHAT are the 10 days?

The holdout goes NEGATIVE if you drop its 10 best days (1.8% of the sample).
That is either fatal or fine, depending entirely on WHAT those days are:

  A) ONE MARKET EVENT (e.g. a single March-2025 liquidation cascade)
     -> the strategy is a bet on a rare event repeating. You could wait two
        years for the next one while bleeding costs. NOT DEPLOYABLE.

  B) SCATTERED across time and assets
     -> the strategy is simply LUMPY. Liquidity premiums are episodic by
        nature (Nagel 2012). Accept it and size accordingly. DEPLOYABLE.

We also compare against the TRAIN period, which was far less fragile -- if
train is diffuse and holdout is concentrated, that is the funding-decay story
showing up as increased fragility.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import xs_funding as xs
from . import costs as ck
from .rerun_real_costs import backtest_real
from .liq_weight import positions

BARS = 24*365
HO_START = pd.Timestamp("2025-01-01", tz="UTC")
TRAIN_END = pd.Timestamp("2024-12-31", tz="UTC")
CFG = dict(liq_power=0.25, rebal_h=24, band=0.005, dd_scale=False, lb_h=24*7)


def run():
    pd.set_option("display.width", 240)
    panel = xs.build_panel()
    pos = positions(panel, **CFG)
    cp = ck.build_cost_panel(5_000)

    # per (bar, symbol) pnl so we can attribute the big days
    d = pos.sort_values(["ts", "symbol"]).merge(
        cp[["ts", "symbol", "cost_taker"]], on=["ts", "symbol"], how="left")
    d["cost_taker"] = d["cost_taker"].fillna(0.002)
    d["w_prev"] = d.groupby("symbol")["w"].shift(1).fillna(0.0)
    d["price_pnl"] = d["w_prev"]*d["ret"].fillna(0.0)
    d["funding_pnl"] = np.where(d["settled"],
                                -d["w_prev"]*d["funding_rate"].fillna(0.0), 0.0)
    d["cost"] = (d["w"]-d["w_prev"]).abs()*d["cost_taker"]
    d["pnl"] = d["price_pnl"] + d["funding_pnl"] - d["cost"]
    d["date"] = d["ts"].dt.date

    ho = d[d.ts >= HO_START]
    daily = ho.groupby("date")["pnl"].sum().sort_values(ascending=False)
    top10 = daily.head(10)

    print("=" * 88)
    print("THE 10 DAYS -- one event, or scattered?")
    print("=" * 88)
    print("\nTOP 10 HOLDOUT DAYS")
    print(top10.to_string(float_format=lambda x: f"{x:+.2%}"))

    # --- ARE THEY CLUSTERED IN TIME?
    dts = pd.to_datetime(pd.Series(top10.index))
    print(f"\n  span: {dts.min().date()} .. {dts.max().date()}")
    print(f"  months covered: {sorted(dts.dt.to_period('M').unique().astype(str))}")
    gaps = dts.sort_values().diff().dt.days.dropna()
    print(f"  median gap between them: {gaps.median():.0f} days")
    n_months = dts.dt.to_period("M").nunique()
    print(f"  distinct months: {n_months} of "
          f"{ho.ts.dt.to_period('M').nunique()} in the holdout")

    # --- WHICH ASSETS?
    print("\n  contribution by asset on those 10 days:")
    big = ho[ho.date.isin(set(top10.index))]
    a = big.groupby("symbol")["pnl"].sum().sort_values(ascending=False)
    print(a.head(6).to_string(float_format=lambda x: f"{x:+.3f}"))
    print(f"  ...spread over {(a.abs() > 0.001).sum()} assets")

    # --- LONG or SHORT side?
    lng = big[big.w_prev > 0]["pnl"].sum()
    sht = big[big.w_prev < 0]["pnl"].sum()
    print(f"\n  from LONG positions : {lng:+.3f}")
    print(f"  from SHORT positions: {sht:+.3f}")

    # --- compare to TRAIN
    tr = d[d.ts <= TRAIN_END]
    td = tr.groupby("date")["pnl"].sum().sort_values(ascending=False)
    print("\n" + "-" * 88)
    print("CONCENTRATION: train vs holdout")
    print("-" * 88)
    for lbl, s in [("TRAIN 2020-24", td), ("HOLDOUT 2025-26", daily)]:
        tot = s.sum()
        print(f"  {lbl:16s} top10 = {s.head(10).sum()/tot:5.0%} of total P&L   "
              f"({len(s)} days)")

    # --- was it a MARKET-WIDE event? check cross-sectional dispersion
    print("\n" + "-" * 88)
    print("WERE THOSE DAYS MARKET-WIDE CRASHES?")
    print("-" * 88)
    mkt = ho.groupby("date")["ret"].mean()      # equal-weight market return
    vol = ho.groupby("date")["ret"].std()       # cross-sectional dispersion
    cmp_ = pd.DataFrame({"strat_pnl": daily, "mkt_ret": mkt, "xs_disp": vol})
    print("\n  on the 10 best days:")
    print(cmp_.loc[list(top10.index)].to_string(
        float_format=lambda x: f"{x:+.3f}"))
    print(f"\n  avg market return on those days : {mkt.loc[list(top10.index)].mean():+.2%}")
    print(f"  avg market return, all days     : {mkt.mean():+.2%}")
    print(f"  avg XS dispersion on those days : {vol.loc[list(top10.index)].mean():.3f}")
    print(f"  avg XS dispersion, all days     : {vol.mean():.3f}")
    print("=" * 88)


if __name__ == "__main__":
    run()
