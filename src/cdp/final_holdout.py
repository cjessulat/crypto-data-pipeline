"""
Holdout under REAL costs. The last honest validation available.

CAVEAT -- THE HOLDOUT IS NO LONGER PRISTINE
    We have looked at it (vol-target ablation, survivorship test). It has been
    contaminated by OBSERVATION. What remains clean is the SELECTION: the
    config below was chosen entirely on TRAIN-set evidence, under a cost model
    derived from first principles, with no reference to holdout performance.

PREDICTIONS (before running -- so they cannot be retrofitted):
    - holdout return HIGHER than train (~+40% vs +32%)
    - holdout drawdown SMALLER  (~-10% vs -24%)
    - NEITHER is evidence the strategy is better than the train set says.
      2025-26 was a calm, mean-reverting regime that suits a contrarian book.
      The TRAIN set contains COVID, the 2021 mania and the 2022 collapse.
      TRAIN IS THE HONEST NUMBER TO PLAN AROUND.
    - costs HIGHER in holdout (alt liquidity has thinned since 2021)
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import xs_funding as xs
from . import costs as ck
from .survivorship import metrics
from .rerun_real_costs import backtest_real
from .liq_weight import positions

BARS = 24 * 365
TRAIN_END = pd.Timestamp("2024-12-31", tz="UTC")
HO_START = pd.Timestamp("2025-01-01", tz="UTC")

# THE CONFIG. Chosen on train-set evidence only.
CFG = dict(liq_power=0.25, rebal_h=24, band=0.005, dd_scale=False, lb_h=24*7)


def run():
    pd.set_option("display.width", 240)
    panel = xs.build_panel()
    pos = positions(panel, **CFG)

    print("=" * 88)
    print("FINAL HOLDOUT -- real costs, config selected on TRAIN evidence only")
    print(f"config: {CFG}")
    print("=" * 88)

    for cap in [5_000, 10_000]:
        cp = ck.build_cost_panel(cap)
        r = backtest_real(pos, cp)
        tr = r[r.index <= TRAIN_END]
        ho = r[r.index >= HO_START]

        print(f"\n--- capital ${cap:,} ---")
        rows = []
        for lbl, seg in [("TRAIN 2020-24 (hostile regimes)", tr),
                         ("HOLDOUT 2025-26 (benign regime)", ho)]:
            m = metrics(seg["pnl"])
            rows.append({
                "period": lbl,
                "sortino": m["sortino"], "calmar": m["calmar"],
                "sharpe": m["sharpe"], "ret": m["ann_ret"],
                "maxdd": m["maxdd"],
                "cost": -seg["cost"].sum()*BARS/len(seg),
                "funding": seg["funding_pnl"].sum()*BARS/len(seg),
                "price": seg["price_pnl"].sum()*BARS/len(seg),
            })
        print(pd.DataFrame(rows).to_string(index=False,
                                           float_format=lambda x: f"{x:+8.3f}"))

    # year by year, at the size actually being deployed
    cp = ck.build_cost_panel(5_000)
    r = backtest_real(pos, cp)
    print("\n" + "=" * 88)
    print("BY YEAR (capital $5,000, real costs)")
    print("=" * 88)
    yr = []
    for y, g in r.groupby(r.index.year):
        if len(g) < 500:
            continue
        m = metrics(g["pnl"])
        yr.append({"year": y, "ret": m["ann_ret"], "sortino": m["sortino"],
                   "maxdd": m["maxdd"],
                   "funding": g["funding_pnl"].sum()*BARS/len(g),
                   "price": g["price_pnl"].sum()*BARS/len(g),
                   "cost": -g["cost"].sum()*BARS/len(g)})
    ydf = pd.DataFrame(yr).set_index("year")
    print(ydf.to_string(float_format=lambda x: f"{x:+.1%}" if abs(x) < 10 else f"{x:+.2f}"))

    print("\n  losing years:", int((ydf.ret < 0).sum()), "of", len(ydf))
    print("  worst year   :", f"{ydf.ret.min():+.1%}")
    print("  worst maxDD  :", f"{ydf.maxdd.min():+.1%}")

    # fragility, on the holdout, under real costs
    ho = r[r.index >= HO_START]
    print("\n" + "=" * 88)
    print("FRAGILITY (holdout, real costs)")
    print("=" * 88)
    daily = ho["pnl"].groupby(ho.index.date).sum()
    order = daily.sort_values(ascending=False)
    for n in [0, 5, 10, 20]:
        k = daily[~daily.index.isin(set(order.head(n).index))]
        dn = k[k < 0]
        so = (k.mean()*365) / (dn.std()*np.sqrt(365)) if len(dn) > 1 else np.nan
        print(f"   drop {n:3d} days -> ann {k.mean()*365:+7.2%}   sortino {so:5.2f}")
    print("=" * 88)


if __name__ == "__main__":
    run()
