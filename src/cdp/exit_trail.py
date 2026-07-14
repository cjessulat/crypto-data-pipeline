"""
EXIT IDEA #1 -- TRAILING STOPS.

WHY THIS IS THE ONLY EXIT PHILOSOPHY NOT ALREADY RULED OUT
    Every exit tested so far ends the trade EARLY:
      profit target  -> exits before the move finishes
      stop loss      -> exits at the bottom, before the bounce
      time stop      -> exits on an arbitrary clock
      funding-normalise -> exits exactly WHEN THE RECOVERY STARTS (the worst)

    A trailing stop does the opposite. It lets the trade run INDEFINITELY and
    only exits AFTER the move has happened and then reversed. It does not
    truncate the right tail -- it RIDES it, then protects it.

    For a strategy whose P&L is 130% concentrated in 10 days, that is the only
    coherent exit philosophy.

TWO VARIANTS
    FIXED %  : exit on giving back X% from the trade's peak. Simple -- but has
               the same flaw that probably broke my stop-loss test: a 10%
               giveback is nothing in SNX and enormous in BTC.
    ATR-NORM : trail by N x the asset's OWN volatility. What a real trader
               would actually use, and it fixes the one-size-fits-all problem.

PREDICTIONS (before running):
    - Best exit tested so far. The mechanism is right.
    - ATR-normalised BEATS fixed % (assets have wildly different vols).
    - Will STILL probably fail the +0.30 bar -- a trailing stop still exits
      sometimes, and may exit into a temporary pullback inside a larger rebound.
    - Best realistic case: modest return cost, real drawdown reduction.
      WATCH CALMAR, not Sortino.

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


def apply_trail(pos, mode, param):
    """
    mode 'pct' : exit when the trade gives back `param` (e.g. 0.15 = 15%)
                 from its PEAK cumulative return.
    mode 'atr' : exit when giveback exceeds `param` x the asset's trailing
                 daily volatility (so SNX gets a wide trail, BTC a tight one).
    """
    p = pos.sort_values(["symbol", "ts"]).copy()

    # trailing 30d vol of each asset, LAGGED
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
        cur = 0.0
        cum = 0.0        # cumulative return of the open trade
        peak = 0.0       # best cum return this trade has seen
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
                    cur, cum, peak = tgt, 0.0, 0.0
                else:
                    held[i] = 0.0
                    continue

            if tgt != 0 and (cur == 0 or np.sign(tgt) != np.sign(cur)):
                cur, cum, peak = tgt, 0.0, 0.0      # new trade
            elif tgt == 0:
                cur, cum, peak = 0.0, 0.0, 0.0
            else:
                cur = tgt

            if cur != 0:
                cum += np.sign(cur) * ret[i]
                peak = max(peak, cum)

                # trail width: fixed, or scaled to THIS asset's volatility
                if mode == "pct":
                    width = param
                else:  # atr
                    width = param * vol[i] * np.sqrt(24)   # daily-ish vol

                # only trail once the trade is ACTUALLY IN PROFIT --
                # otherwise it degenerates into a plain stop loss, which we
                # already know sells the bottom.
                if peak > 0 and (peak - cum) >= width:
                    blocked, block_w = True, tgt
                    cur, cum, peak = 0.0, 0.0, 0.0
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
    base = positions(panel, **CFG)
    cp = ck.build_cost_panel(5_000)

    print("=" * 104)
    print("EXIT #1 -- TRAILING STOPS (ride the tail, then protect it)")
    print("Bar (pre-set): TRAIN sortino +0.30 AND holdout non-negative")
    print("=" * 104)

    variants = [
        ("baseline (no exit)",        None,  None),
        ("trail 10% from peak",       "pct", 0.10),
        ("trail 20% from peak",       "pct", 0.20),
        ("trail 30% from peak",       "pct", 0.30),
        ("trail 2x asset vol",        "atr", 2.0),
        ("trail 4x asset vol",        "atr", 4.0),
        ("trail 8x asset vol",        "atr", 8.0),
    ]

    rows = []
    for lbl, mode, param in variants:
        p = base if mode is None else apply_trail(base, mode, param)
        r = backtest_real(p, cp)
        tr = r[r.index <= TRAIN_END]
        ho = r[r.index >= HO_START]
        m, mh = metrics(tr["pnl"]), metrics(ho["pnl"])
        rows.append({
            "variant": lbl,
            "tr_sortino": m["sortino"], "tr_calmar": m["calmar"],
            "tr_ret": m["ann_ret"], "tr_maxdd": m["maxdd"],
            "ho_sortino": mh["sortino"], "ho_ret": mh["ann_ret"],
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
        print(f"  {r.variant:24s} sortino {dt:+.3f}  calmar {dc:+.3f}  "
              f"holdout {dh:+.3f}   {'PASS' if ok else 'fail'}")

    print("\n  DID DRAWDOWN IMPROVE? (the realistic best case)")
    for _, r in df.iterrows():
        cut = (abs(b.tr_maxdd) - abs(r.tr_maxdd)) / abs(b.tr_maxdd)
        rc = (b.tr_ret - r.tr_ret) / b.tr_ret if b.tr_ret else 0
        flag = "  <-- BETTER DD" if cut > 0.10 and rc < 0.30 else ""
        print(f"    {r.variant:24s} maxdd {r.tr_maxdd:+.1%} (cut {cut:+.0%})  "
              f"ret cut {rc:+.0%}{flag}")
    print("=" * 104)


if __name__ == "__main__":
    run()
