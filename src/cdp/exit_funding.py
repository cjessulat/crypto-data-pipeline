"""
EXIT IDEA #3 -- FUNDING NORMALISATION.

WHY THIS IS THE REAL GAP
    Every exit I tested before fired on PRICE (profit target, stop loss) or on
    THE CLOCK (time stop). Neither has anything to do with our thesis.

    The thesis is: funding is deeply negative -> the asset is HATED -> buy it,
    because you are being paid to be the only bidder.

    The thesis is SPENT when the market STOPS HATING IT -- i.e. when funding
    NORMALISES. That is not a price signal or a time signal. It is the actual
    thesis condition.

WHY THE EARLIER "SIGNAL DECAY" TEST MISSED THIS
    That test used the cross-sectional Z-SCORE, and it never fired -- the
    results were byte-identical to baseline. Reason: positions are already
    CONTINUOUSLY REWEIGHTED by z. As z decays, the weight shrinks on its own.
    The strategy already contains a z-decay exit; we just called it "continuous
    weighting".

    ABSOLUTE funding level is a DIFFERENT quantity. An asset can stay in the
    bottom decile cross-sectionally (z stays extreme, weight stays on) while
    its OWN funding has normalised back to zero. The thesis is dead but the
    position is still open. THAT is the gap.

PREDICTIONS (before running):
    - This will be the BEST of the three exit ideas -- it is the only one with
      a genuine mechanism.
    - It will STILL probably fail the bar. Tail-truncation does not care WHY
      you exit; any rule that ends a trade before the violent rebound costs
      you, and our rebounds ARE the edge.
    - The interesting case: a meaningful DRAWDOWN reduction for a modest
      return cost. CALMAR would reveal that before Sortino does.

BAR (pre-committed, unchanged): TRAIN sortino +0.30 AND holdout non-negative.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import xs_funding as xs
from . import xs_v2 as v2
from . import costs as ck
from .survivorship import metrics
from .rerun_real_costs import backtest_real
from .liq_weight import positions

BARS = 24*365
TRAIN_END = pd.Timestamp("2024-12-31", tz="UTC")
HO_START = pd.Timestamp("2025-01-01", tz="UTC")
CFG = dict(liq_power=0.25, rebal_h=24, band=0.005, dd_scale=False, lb_h=24*7)


def apply_funding_exit(pos, mode, param):
    """
    Exit when the ASSET'S OWN funding has normalised.

    mode 'cross'  : LONG  entered on negative funding -> exit when its trailing
                    funding crosses back ABOVE `param` (e.g. 0.0).
                    SHORT entered on positive funding -> exit when it crosses
                    BELOW -param.
    mode 'revert' : exit when trailing funding has retraced `param` of the way
                    from its ENTRY level back toward zero. (0.5 = halfway home)

    Re-entry allowed when the signal genuinely refreshes (sign flip, or target
    materially stronger than at exit) -- same guard as the fixed exits module.
    """
    p = pos.sort_values(["symbol", "ts"]).copy()
    out = []

    for sym, g in p.groupby("symbol", sort=False):
        w = g["w"].to_numpy(copy=True)
        f = g["f_ma"].ffill().fillna(0.0).to_numpy()   # trailing OWN funding
        held = np.zeros(len(g))

        cur = 0.0
        entry_f = 0.0
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
                    blocked = False
                    cur, entry_f = tgt, f[i]
                else:
                    held[i] = 0.0
                    continue

            if tgt != 0 and (cur == 0 or np.sign(tgt) != np.sign(cur)):
                cur, entry_f = tgt, f[i]      # new trade
            elif tgt == 0:
                cur = 0.0
            else:
                cur = tgt

            if cur != 0:
                hit = False
                if mode == "cross":
                    # LONG (cur>0) was entered because funding was NEGATIVE.
                    # Thesis spent once funding climbs back above the threshold.
                    if cur > 0 and f[i] > param:
                        hit = True
                    elif cur < 0 and f[i] < -param:
                        hit = True
                elif mode == "revert":
                    if entry_f != 0:
                        retraced = 1.0 - (f[i] / entry_f)
                        if retraced >= param:
                            hit = True
                if hit:
                    blocked, block_w = True, tgt
                    cur = 0.0
                    held[i] = 0.0
                    continue

            held[i] = cur

        gg = g.copy()
        gg["w"] = held
        out.append(gg)

    return pd.concat(out).sort_values(["ts", "symbol"]).reset_index(drop=True)


def run():
    pd.set_option("display.width", 240)
    panel = xs.build_panel()
    # positions() ALREADY returns f_ma and z -- merging them again suffixes
    # the columns to _x/_y and makes plain 'f_ma' disappear. Do not merge.
    base = positions(panel, **CFG)
    cp = ck.build_cost_panel(5_000)

    print("=" * 104)
    print("EXIT #3 -- FUNDING NORMALISATION (exit on the THESIS condition)")
    print("Bar (pre-set): TRAIN sortino +0.30 AND holdout non-negative")
    print("=" * 104)

    variants = [
        ("baseline (no exit)",                None,     None),
        ("exit when funding crosses 0",       "cross",  0.0),
        ("exit when funding crosses +0.0001", "cross",  0.0001),
        ("exit at 50% retrace to zero",       "revert", 0.50),
        ("exit at 75% retrace to zero",       "revert", 0.75),
        ("exit at 100% retrace (full)",       "revert", 1.00),
    ]

    rows = []
    for lbl, mode, param in variants:
        p = base if mode is None else apply_funding_exit(base, mode, param)
        r = backtest_real(p, cp)
        tr = r[r.index <= TRAIN_END]
        ho = r[r.index >= HO_START]
        m, mh = metrics(tr["pnl"]), metrics(ho["pnl"])
        rows.append({
            "variant": lbl,
            "tr_sortino": m["sortino"], "tr_calmar": m["calmar"],
            "tr_ret": m["ann_ret"], "tr_maxdd": m["maxdd"],
            "ho_sortino": mh["sortino"], "ho_ret": mh["ann_ret"],
            "ho_maxdd": mh["maxdd"],
            "turnover": tr["turnover"].sum()*BARS/len(tr),
        })

    df = pd.DataFrame(rows)
    print()
    print(df.to_string(index=False, float_format=lambda x: f"{x:+8.3f}"))

    b = df.iloc[0]
    print("\n" + "-" * 104)
    print("  ADOPTION CHECK")
    print("-" * 104)
    for _, r in df.iloc[1:].iterrows():
        dt = r.tr_sortino - b.tr_sortino
        dh = r.ho_sortino - b.ho_sortino
        dc = r.tr_calmar - b.tr_calmar
        ok = (dt >= 0.30) and (dh >= 0)
        print(f"  {r.variant:34s} sortino {dt:+.3f}  calmar {dc:+.3f}  "
              f"holdout {dh:+.3f}   {'PASS' if ok else 'fail'}")

    # did any variant do the INTERESTING thing -- cut drawdown cheaply?
    print("\n  DRAWDOWN vs RETURN trade-off (the interesting case):")
    for _, r in df.iterrows():
        dd_cut = (abs(b.tr_maxdd) - abs(r.tr_maxdd)) / abs(b.tr_maxdd)
        ret_cut = (b.tr_ret - r.tr_ret) / b.tr_ret if b.tr_ret else 0
        print(f"    {r.variant:34s} maxdd {r.tr_maxdd:+.1%}  "
              f"(cut {dd_cut:+.0%})   return cut {ret_cut:+.0%}")
    print("=" * 104)


if __name__ == "__main__":
    run()
