"""
Forensics on the HOLDOUT. Same tests that killed v1.

The holdout made +39.9% -- but +37.3% of that was the PRICE leg, not funding.
v1 had the same profile, and forensics showed it was ~10 lucky days.

If the holdout fails these tests, the Sharpe of 2.45 is a story about a few
trades, not a strategy.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import xs_funding as xs
from . import xs_v2 as v2

BARS = 24 * 365
CFG = dict(lb_h=24*7, rebal_h=24, band=0.005, vol_target=0.15, fee_bps=5.0)
CUT = pd.Timestamp("2025-01-01", tz="UTC")


def positions(panel):
    d = v2.signal_z(panel, CFG["lb_h"])
    d = v2.target_weights(d)
    tmp = v2.apply_trading_rules(d, CFG["rebal_h"], CFG["band"])
    r0 = xs.backtest(tmp, 0, CFG["fee_bps"])
    rv = (r0["pnl"].rolling(24*30, min_periods=24*10).std()*np.sqrt(BARS)).shift(1)
    d["scale"] = d["ts"].map((CFG["vol_target"]/rv).clip(0.25, 3.0)).ffill().fillna(1.0)
    d["w_tgt"] = d["w_tgt"] * d["scale"]
    return v2.apply_trading_rules(d, CFG["rebal_h"], CFG["band"])


def run():
    pd.set_option("display.width", 200)
    full = xs.build_panel()
    pos = positions(full)
    res = xs.backtest(pos, 0, CFG["fee_bps"])

    ho = res[res.index >= CUT]
    hp = pos[pos.ts >= CUT].copy()

    print("=" * 78)
    print("HOLDOUT FORENSICS -- the tests that killed v1")
    print("=" * 78)

    # --- drop best days
    print("\n1. DROP THE BEST DAYS")
    daily = ho["pnl"].groupby(ho.index.date).sum()
    order = daily.sort_values(ascending=False)
    for n in [0, 3, 5, 10, 20]:
        keep = daily[~daily.index.isin(set(order.head(n).index))]
        ann = keep.mean()*365
        vol = keep.std()*np.sqrt(365)
        print(f"   drop {n:3d} ({n/len(daily):5.1%}) -> ann {ann:+7.2%}  sharpe {ann/vol:5.2f}")
    s0 = daily.mean()*365/(daily.std()*np.sqrt(365))
    k = daily[~daily.index.isin(set(order.head(10).index))]
    s10 = k.mean()*365/(k.std()*np.sqrt(365))
    print(f"\n   Sharpe {s0:.2f} -> {s10:.2f} after dropping 10 days")
    print("   VERDICT:", "FRAGILE" if s10 < s0*0.5 else
          ("concentrated" if s10 < s0*0.75 else "ROBUST"))

    # --- attribution
    print("\n2. ATTRIBUTION BY SYMBOL (holdout)")
    hp["w_prev"] = hp.groupby("symbol")["w"].shift(1).fillna(0.0)
    hp["price_pnl"] = hp["w_prev"]*hp["ret"].fillna(0.0)
    hp["funding_pnl"] = np.where(hp["settled"],
                                 -hp["w_prev"]*hp["funding_rate"].fillna(0.0), 0.0)
    hp["pnl"] = hp["price_pnl"] + hp["funding_pnl"]
    a = (hp.groupby("symbol")[["price_pnl","funding_pnl","pnl"]].sum()
           .sort_values("pnl", ascending=False))
    a["share"] = a["pnl"]/a["pnl"].sum()
    print(a.head(8).to_string(float_format=lambda x: f"{x:+8.3f}"))
    print("   ...")
    print(a.tail(4).to_string(float_format=lambda x: f"{x:+8.3f}"))
    top3 = a["share"].head(3).sum()
    print(f"\n   top 3 symbols = {top3:.0%} of holdout P&L")

    # --- leave one out
    print("\n3. LEAVE-ONE-OUT (holdout)")
    base = xs.stats(ho["pnl"])["sharpe"]
    rows = []
    for sym in sorted(full.symbol.unique()):
        p = positions(full[full.symbol != sym].copy())
        r = xs.backtest(p, 0, CFG["fee_bps"])
        r = r[r.index >= CUT]
        rows.append({"dropped": sym, "sharpe": xs.stats(r["pnl"])["sharpe"]})
    d = pd.DataFrame(rows).sort_values("sharpe")
    print(f"   base (all 26): {base:.2f}")
    print("   worst 5 when dropped:")
    print(d.head(5).to_string(index=False, float_format=lambda x: f"{x:+7.2f}"))
    print(f"\n   min across all drops: {d.sharpe.min():.2f}  "
          f"({d.sharpe.min()/base:.0%} of base)")

    # --- funding leg alone
    print("\n4. THE FUNDING LEG ALONE (no price bet)")
    f_only = hp.groupby("ts")["funding_pnl"].sum()
    c = hp.groupby("ts").apply(lambda g: (g["w"]-g["w_prev"]).abs().sum()
                               * CFG["fee_bps"]/1e4, include_groups=False)
    net = f_only - c
    ann = net.mean()*BARS
    vol = net.std()*np.sqrt(BARS)
    print(f"   funding only, net of cost: {ann:+.2%}/yr  vol {vol:.2%}  "
          f"sharpe {ann/vol:.2f}")
    print("   (this is the part with a MECHANISM. the price leg is noise.)")
    print("=" * 78)


if __name__ == "__main__":
    run()
