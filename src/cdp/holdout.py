"""
THE HOLDOUT TEST. One shot. Config is EXACTLY as pre-registered:
    26 symbols, 7d lookback, daily rebalance, 0.005 band, 15% vol target, 5bps
No tuning. No second attempt.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import xs_funding as xs
from . import xs_v2 as v2

BARS = 24 * 365
CFG = dict(lb_h=24*7, rebal_h=24, band=0.005, vol_target=0.15, fee_bps=5.0)


def run():
    pd.set_option("display.width", 220)
    full = xs.build_panel()

    print("=" * 78)
    print("HOLDOUT TEST -- pre-registered config, never tuned on this data")
    print("=" * 78)

    # Build signal on FULL history (signal needs warmup), then evaluate ONLY
    # on the holdout window. The signal is causal, so this is legitimate.
    res = v2.run_bt(full, **CFG)

    tr = res[res.index <= pd.Timestamp("2024-12-31", tz="UTC")]
    ho = res[res.index >= pd.Timestamp("2025-01-01", tz="UTC")]

    print(f"  train   : {tr.index.min().date()} .. {tr.index.max().date()}  ({len(tr):,} bars)")
    print(f"  HOLDOUT : {ho.index.min().date()} .. {ho.index.max().date()}  ({len(ho):,} bars)")

    rows = []
    for lbl, r in [("TRAIN (seen)", tr), ("HOLDOUT (unseen)", ho)]:
        s = xs.stats(r["pnl"])
        tot = r[["price_pnl", "funding_pnl", "cost"]].sum() * BARS / len(r)
        rows.append({"period": lbl, "sharpe": s["sharpe"], "ann_ret": s["ann_ret"],
                     "vol": s["ann_vol"], "maxdd": s["maxdd"],
                     "price": tot["price_pnl"], "funding": tot["funding_pnl"],
                     "cost": -tot["cost"]})
    print()
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:+8.3f}"))

    print("\n" + "=" * 78)
    print("HOLDOUT, BY YEAR")
    print("=" * 78)
    yr = []
    for y, g in ho.groupby(ho.index.year):
        if len(g) < 100:
            continue
        s = xs.stats(g["pnl"])
        yr.append({"year": y, "net": s["ann_ret"], "sharpe": s["sharpe"],
                   "maxdd": s["maxdd"],
                   "price": g["price_pnl"].sum()*BARS/len(g),
                   "funding": g["funding_pnl"].sum()*BARS/len(g)})
    print(pd.DataFrame(yr).set_index("year").to_string(
        float_format=lambda x: f"{x:+.2%}" if abs(x) < 10 else f"{x:.2f}"))

    print("\n" + "=" * 78)
    s_tr = xs.stats(tr["pnl"])["sharpe"]
    s_ho = xs.stats(ho["pnl"])["sharpe"]
    r_ho = xs.stats(ho["pnl"])["ann_ret"]
    f_ho = ho["funding_pnl"].sum() * BARS / len(ho)
    print(f"  train Sharpe   {s_tr:+.2f}")
    print(f"  HOLDOUT Sharpe {s_ho:+.2f}   ({s_ho/s_tr:.0%} of train)")
    print(f"  HOLDOUT return {r_ho:+.2%}")
    print(f"  HOLDOUT funding leg {f_ho:+.2%}  <- the thing we were testing")
    print()
    if r_ho <= 0:
        print("  VERDICT: FAILED. Negative out of sample. Walk away.")
    elif s_ho < 0.3:
        print("  VERDICT: FAILED. Edge does not survive out of sample.")
    elif s_ho < s_tr * 0.5:
        print("  VERDICT: WEAK. Heavy degradation. Most of the train edge was fitted.")
    else:
        print("  VERDICT: SURVIVED. Edge persists out of sample.")
    print("=" * 78)


if __name__ == "__main__":
    run()
