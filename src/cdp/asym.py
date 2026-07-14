"""
IDEA 1 -- asymmetric long/short weighting.

THE OBSERVATION
    On the 10 best holdout days: LONG positions made +0.266, SHORT made +0.051.
    The long leg is 84% of the P&L. Yet we equal-weight the two legs and pay
    the same costs on both.

THE HYPOTHESIS
    Buying a hated asset (deeply negative funding) is genuinely CONTRARIAN --
    you are the only bidder. Shorting a crowded asset is itself a CROWDED
    TRADE -- you are doing what everyone else is doing. The asymmetry may be
    structural, not accidental.

WHY THIS CAN IMPROVE SORTINO WHERE THE LAST 3 FAILURES COULD NOT
    Vol targeting, liquidity weighting and dispersion sizing all RESIZED the
    same bet. Sortino sees through that: scaling a return stream scales its
    risk proportionally. This changes the COMPOSITION of the bet. That is the
    only kind of change Sortino can genuinely reward.

PREDICTION (before running)
    A long tilt HELPS, but by less than 84/16 implies -- because the short leg
    is probably doing HEDGING work that never shows up as P&L. Expect return
    UP, Sortino roughly FLAT or slightly up. If Sortino JUMPS, be suspicious:
    it likely means we have just taken on unhedged market beta in a period
    that happened to go up.

    We therefore also report BETA to the equal-weight crypto market. A tilt
    that "works" purely by picking up beta is not an edge -- it is a
    directional bet wearing a market-neutral costume.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import xs_funding as xs
from . import costs as ck
from .survivorship import metrics
from .rerun_real_costs import backtest_real
from .liq_weight import positions

BARS = 24*365
TRAIN_END = pd.Timestamp("2024-12-31", tz="UTC")
HO_START = pd.Timestamp("2025-01-01", tz="UTC")
CFG = dict(liq_power=0.25, rebal_h=24, band=0.005, dd_scale=False, lb_h=24*7)


def tilt(pos, long_share):
    """
    long_share = 0.5 -> equal (current). 0.7 -> 70% long / 30% short.
    Gross exposure held CONSTANT at 1.0 so we are not secretly adding leverage.
    """
    p = pos.copy()
    w = p["w"].to_numpy()
    lng = np.where(w > 0, w, 0.0)
    sht = np.where(w < 0, w, 0.0)

    # rescale each leg to its target share of gross
    gl = pd.Series(lng, index=p.index).abs().groupby(p["ts"]).transform("sum")
    gs = pd.Series(sht, index=p.index).abs().groupby(p["ts"]).transform("sum")
    lng = np.where(gl > 0, lng / gl * long_share, 0.0)
    sht = np.where(gs > 0, sht / gs * (1.0 - long_share), 0.0)

    p["w"] = lng + sht
    return p


def market_beta(pnl, panel):
    """Beta of the strategy to the equal-weight crypto market."""
    d = panel.copy()
    d["date"] = d["ts"].dt.floor("D")
    mkt = (d.groupby(["date", "symbol"])["close"].last().unstack()
             .pct_change().mean(axis=1))
    s = pnl.groupby(pnl.index.floor("D")).sum()
    j = pd.concat([s.rename("s"), mkt.rename("m")], axis=1).dropna()
    if len(j) < 50:
        return np.nan
    return np.polyfit(j["m"], j["s"], 1)[0]


def run():
    pd.set_option("display.width", 240)
    panel = xs.build_panel()
    base = positions(panel, **CFG)
    cp = ck.build_cost_panel(5_000)

    print("=" * 100)
    print("IDEA 1 -- ASYMMETRIC LONG/SHORT WEIGHTING")
    print("Gross exposure held constant at 1.0 -- this changes COMPOSITION,")
    print("not size. Beta reported: a tilt that works via beta is NOT an edge.")
    print("=" * 100)

    rows = []
    for ls in [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
        p = tilt(base, ls)
        r = backtest_real(p, cp)
        tr = r[r.index <= TRAIN_END]
        ho = r[r.index >= HO_START]
        m = metrics(tr["pnl"])
        mh = metrics(ho["pnl"])
        rows.append({
            "long_share": ls,
            "tr_sortino": m["sortino"], "tr_calmar": m["calmar"],
            "tr_ret": m["ann_ret"], "tr_maxdd": m["maxdd"],
            "beta": market_beta(tr["pnl"], panel),
            "ho_sortino": mh["sortino"], "ho_ret": mh["ann_ret"],
        })

    df = pd.DataFrame(rows)
    print("\nTRAIN 2020-2024   (0.5 = current equal-weight; 1.0 = long only)")
    print(df.to_string(index=False, float_format=lambda x: f"{x:+8.3f}"))

    b = df[df.long_share == 0.5].iloc[0]
    best = df.sort_values("tr_sortino", ascending=False).iloc[0]
    print("\n" + "-" * 100)
    print(f"  baseline (50/50) : sortino {b.tr_sortino:.3f}  ret {b.tr_ret:+.1%}  "
          f"maxdd {b.tr_maxdd:+.1%}  beta {b.beta:+.3f}")
    print(f"  best             : {best.long_share:.0%} long")
    print(f"                     sortino {best.tr_sortino:.3f}  ret {best.tr_ret:+.1%}  "
          f"maxdd {best.tr_maxdd:+.1%}  beta {best.beta:+.3f}")
    gain = best.tr_sortino - b.tr_sortino
    print(f"  gain             : sortino {gain:+.3f}")
    print()
    if gain < 0.05:
        print("  -> NOISE. Not a real improvement. (threshold set at +0.30 before running)")
    elif gain < 0.30:
        print("  -> MARGINAL. Below the +0.30 bar I set before running. Do not adopt.")
    else:
        print("  -> MATERIAL. Exceeds the pre-set +0.30 bar.")
    if abs(best.beta) > abs(b.beta) * 2 and abs(best.beta) > 0.2:
        print("  -> WARNING: the tilt works by taking on MARKET BETA.")
        print("     That is a directional bet, not an edge. Discount heavily.")
    print("=" * 100)


if __name__ == "__main__":
    run()
