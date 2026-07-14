"""
EXIT IDEA #2 -- VOLATILITY-NORMALISED STOPS. The last untested exit.

WHY THIS DESERVES A FAIR TEST
    My original stop-loss test used a FIXED -10% / -20% across all 26 assets.
    That is indefensible: a 10% move in BTC is a major event; in SNX it is a
    Tuesday. I effectively set a hair-trigger on the volatile names and no stop
    at all on the stable ones, then concluded "stops don't work".

    This is the version a real trader would run: stop at N x the asset's OWN
    trailing volatility.

WHAT WE ALREADY KNOW
    The trailing-stop test included VOL-NORMALISED trails (2x/4x/8x asset vol).
    Every one INCREASED drawdown. A plain vol stop is the same idea without the
    trailing part -- so it should be strictly WORSE: it sells the bottom rather
    than selling after a peak.

PREDICTION (before running):
    FAILS, and worse than the trailing stops. Same mechanism: exits break the
    hedge. The book is dollar-neutral by construction; exiting one leg leaves
    the other unhedged, turning a market-neutral portfolio into a lopsided
    directional bet. That is MORE volatile, not less.

BAR (pre-committed): TRAIN sortino +0.30 AND holdout non-negative.
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


def apply_volstop(pos, n_sigma, rehedge=False):
    """
    Stop out at n_sigma x the asset's OWN trailing daily volatility.

    rehedge=True : after stopping out, REDUCE THE OPPOSITE LEG proportionally
                   so the book stays dollar-neutral. This directly tests the
                   "exits break the hedge" hypothesis -- if that is the reason
                   exits fail, re-hedging should fix it.
    """
    p = pos.sort_values(["symbol", "ts"]).copy()
    p["vol"] = (p.groupby("symbol")["ret"]
                  .transform(lambda s: s.rolling(24*30, min_periods=24*5).std())
                  .groupby(p["symbol"]).shift(1))
    p["vol"] = p.groupby("symbol")["vol"].ffill().fillna(0.02)

    out = []
    for sym, g in p.groupby("symbol", sort=False):
        w = g["w"].to_numpy(copy=True)
        ret = g["ret"].fillna(0.0).to_numpy()
        vol = g["vol"].to_numpy()

        held = np.zeros(len(g))
        cur = cum = 0.0
        blocked = False
        block_w = 0.0

        for i in range(len(g)):
            tgt = w[i]
            if blocked:
                refreshed = (
                    (tgt != 0 and block_w != 0 and np.sign(tgt) != np.sign(block_w))
                    or (abs(tgt) > abs(block_w) * 1.5)
                )
                if refreshed:
                    blocked, cur, cum = False, tgt, 0.0
                else:
                    held[i] = 0.0
                    continue

            if tgt != 0 and (cur == 0 or np.sign(tgt) != np.sign(cur)):
                cur, cum = tgt, 0.0
            elif tgt == 0:
                cur, cum = 0.0, 0.0
            else:
                cur = tgt

            if cur != 0:
                cum += np.sign(cur) * ret[i]
                # daily-equivalent vol from hourly
                width = n_sigma * vol[i] * np.sqrt(24)
                if cum <= -width:
                    blocked, block_w = True, tgt
                    cur, cum = 0.0, 0.0
                    held[i] = 0.0
                    continue
            held[i] = cur

        gg = g.copy()
        gg["w"] = held
        out.append(gg)

    d = pd.concat(out).sort_values(["ts", "symbol"]).reset_index(drop=True)

    if rehedge:
        # RESTORE DOLLAR-NEUTRALITY after the stops have fired.
        # If the hedge-breaking hypothesis is right, this should recover most
        # of the damage.
        lng = d["w"].clip(lower=0).groupby(d["ts"]).transform("sum")
        sht = d["w"].clip(upper=0).abs().groupby(d["ts"]).transform("sum")
        tgt_g = pd.concat([lng, sht], axis=1).min(axis=1)
        d["w"] = np.where(
            d["w"] > 0,
            np.where(lng > 0, d["w"] / lng * tgt_g, 0.0),
            np.where(sht > 0, d["w"] / sht * tgt_g, 0.0),
        )
    return d


def run():
    pd.set_option("display.width", 240)
    panel = xs.build_panel()
    base = positions(panel, **CFG)
    cp = ck.build_cost_panel(5_000)

    print("=" * 108)
    print("EXIT #2 -- VOL-NORMALISED STOPS (+ a direct test of the hedge hypothesis)")
    print("=" * 108)

    variants = [
        ("baseline (no exit)",          None, False),
        ("stop 2 sigma",                2.0,  False),
        ("stop 3 sigma",                3.0,  False),
        ("stop 5 sigma",                5.0,  False),
        ("stop 3 sigma + RE-HEDGE",     3.0,  True),
        ("stop 5 sigma + RE-HEDGE",     5.0,  True),
    ]

    rows = []
    for lbl, ns, rh in variants:
        p = base if ns is None else apply_volstop(base, ns, rehedge=rh)
        r = backtest_real(p, cp)
        tr = r[r.index <= TRAIN_END]
        ho = r[r.index >= HO_START]
        m, mh = metrics(tr["pnl"]), metrics(ho["pnl"])
        rows.append({
            "variant": lbl,
            "tr_sortino": m["sortino"], "tr_calmar": m["calmar"],
            "tr_ret": m["ann_ret"], "tr_maxdd": m["maxdd"],
            "ho_sortino": mh["sortino"], "ho_ret": mh["ann_ret"],
        })

    df = pd.DataFrame(rows)
    print()
    print(df.to_string(index=False, float_format=lambda x: f"{x:+8.3f}"))

    b = df.iloc[0]
    print("\n" + "-" * 108)
    print("  ADOPTION CHECK")
    print("-" * 108)
    for _, r in df.iloc[1:].iterrows():
        dt = r.tr_sortino - b.tr_sortino
        dh = r.ho_sortino - b.ho_sortino
        ok = (dt >= 0.30) and (dh >= 0)
        print(f"  {r.variant:26s} sortino {dt:+.3f}  holdout {dh:+.3f}   "
              f"{'PASS' if ok else 'fail'}")

    print("\n" + "-" * 108)
    print("  THE HEDGE HYPOTHESIS -- does re-hedging rescue the exits?")
    print("-" * 108)
    for ns in [3.0, 5.0]:
        a = df[df.variant == f"stop {ns:.0f} sigma"].iloc[0]
        c = df[df.variant == f"stop {ns:.0f} sigma + RE-HEDGE"].iloc[0]
        print(f"  {ns:.0f} sigma:  no rehedge  sortino {a.tr_sortino:+.3f}  "
              f"maxdd {a.tr_maxdd:+.1%}")
        print(f"            RE-HEDGED   sortino {c.tr_sortino:+.3f}  "
              f"maxdd {c.tr_maxdd:+.1%}   "
              f"({'HELPS' if c.tr_sortino > a.tr_sortino else 'does not help'})")
    print("=" * 108)


if __name__ == "__main__":
    run()
