"""
IDEA 3 -- EXIT RULES.

WHY THIS IS STRUCTURALLY DIFFERENT FROM THE 4 FAILURES
    Vol targeting, liquidity weighting, dispersion sizing and the long tilt all
    SCALED the same return stream. Sortino correctly saw through every one --
    scaling a return stream scales its risk proportionally.

    Exit rules do not scale. They TRUNCATE the distribution. That genuinely
    changes the SHAPE of returns, which is the only kind of change a
    risk-adjusted metric can reward.

THE MECHANISM
    Our edge is mean reversion after dislocation. A trade therefore has a
    NATURAL LIFE: asset is hated -> we buy -> it bounces -> edge is spent.
    After that we hold a beaten-down altcoin with no thesis: pure beta, pure
    risk, no edge. Currently we hold until the funding signal rotates us out,
    which may be WEEKS after the bounce.

THE TRAP -- AND IT IS SEVERE
    Exit rules are the easiest place in all of systematic trading to overfit.
    Infinite variants, continuous parameters. Given a free hand I could turn
    ANY strategy into gold on the train set.

    CONSTRAINTS I AM IMPOSING ON MYSELF:
      1. Only exits with a STATED MECHANISM, declared before seeing results.
      2. A small PRE-DECLARED set. No sweeps. No parameter hunting.
      3. ADOPTION BAR, pre-committed: Sortino +0.30 on TRAIN *AND*
         non-negative change on HOLDOUT.
         (Idea 1 cleared a train bar and then died on holdout. Not twice.)

PREDICTIONS (before running):
    - PROFIT TARGETS hurt. They cut the RIGHT tail -- and our right tail is
      everything (10 days = 130% of holdout P&L).
    - STOP LOSSES hurt. Classic mean-reversion killer: you stop out at the
      bottom, immediately before the bounce you were paid to wait for.
    - SIGNAL-DECAY exit may help. Exit when the asset is no longer hated --
      i.e. the thesis is spent. The only variant with an honest mechanism.
    - TIME STOPS: coin flip.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import xs_funding as xs
from . import xs_v2 as v2
from . import store
from . import costs as ck
from .survivorship import metrics
from .rerun_real_costs import backtest_real
from .liq_weight import positions

BARS = 24*365
TRAIN_END = pd.Timestamp("2024-12-31", tz="UTC")
HO_START = pd.Timestamp("2025-01-01", tz="UTC")
CFG = dict(liq_power=0.25, rebal_h=24, band=0.005, dd_scale=False, lb_h=24*7)


def apply_exit(pos, mode, param):
    """
    Walk each symbol's position series, tracking the OPEN TRADE.

    FIXED. The first version had a bug: once exited, it only re-entered on an
    exact-zero or sign-flip target. With CONTINUOUS weights that essentially
    never happens, so every rule collapsed to "trade once, then stay flat
    forever" -- which is why every variant landed on the same ~11 turnover.

    Correct behaviour: an exit suppresses THIS TRADE. Re-entry is allowed when
    the signal genuinely REFRESHES -- the target flips sign, or moves
    materially (>50%) beyond the level at which we bailed out.
    """
    p = pos.sort_values(["symbol", "ts"]).copy()
    out = []

    for sym, g in p.groupby("symbol", sort=False):
        w = g["w"].to_numpy(copy=True)
        ret = g["ret"].fillna(0.0).to_numpy()
        z = g["z"].fillna(0.0).to_numpy() if "z" in g.columns else np.zeros(len(g))

        held = np.zeros(len(g))
        cur = 0.0          # position actually held
        cum = 0.0          # cum return of the OPEN trade
        bars = 0
        entry_z = 0.0
        blocked = False    # exited: suppress until signal refreshes
        block_w = 0.0      # target weight at the moment we exited

        for i in range(len(g)):
            tgt = w[i]

            if blocked:
                # RE-ENTRY TEST: sign flip, or target materially stronger
                # than when we bailed. Otherwise stay flat.
                refreshed = (
                    (tgt != 0 and block_w != 0 and np.sign(tgt) != np.sign(block_w))
                    or (abs(tgt) > abs(block_w) * 1.5)
                )
                if refreshed:
                    blocked = False
                    cur, cum, bars = tgt, 0.0, 0
                    entry_z = z[i]
                else:
                    held[i] = 0.0
                    continue

            # fresh entry from flat, or sign flip -> new trade
            if tgt != 0 and (cur == 0 or np.sign(tgt) != np.sign(cur)):
                cur, cum, bars = tgt, 0.0, 0
                entry_z = z[i]
            elif tgt == 0:
                cur, cum, bars = 0.0, 0.0, 0
            else:
                cur = tgt          # follow the signal while the trade is open

            if cur != 0:
                cum += np.sign(cur) * ret[i]
                bars += 1

                hit = False
                if mode == "profit" and cum >= param:
                    hit = True
                elif mode == "stop" and cum <= -param:
                    hit = True
                elif mode == "time" and bars >= param:
                    hit = True
                elif mode == "decay":
                    if entry_z != 0 and abs(z[i]) < abs(entry_z) * param:
                        hit = True

                if hit:
                    blocked, block_w = True, tgt
                    cur, cum, bars = 0.0, 0.0, 0
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

    # need z on the positions frame for the decay exit
    d = v2.signal_z(panel, CFG["lb_h"])
    base = positions(panel, **CFG)
    base = base.merge(d[["ts", "symbol", "z"]], on=["ts", "symbol"], how="left")

    cp = ck.build_cost_panel(5_000)

    print("=" * 104)
    print("IDEA 3 -- EXIT RULES")
    print("Adoption bar (pre-set): TRAIN sortino +0.30 AND holdout non-negative")
    print("=" * 104)

    variants = [
        ("baseline (no exit)",          None,     None),
        ("profit target +10%",          "profit", 0.10),
        ("profit target +20%",          "profit", 0.20),
        ("stop loss -10%",              "stop",   0.10),
        ("stop loss -20%",              "stop",   0.20),
        ("time stop 7d",                "time",   24*7),
        ("time stop 21d",               "time",   24*21),
        ("signal decay -> 50% of entry", "decay", 0.50),
        ("signal decay -> 25% of entry", "decay", 0.25),
    ]

    rows = []
    for lbl, mode, param in variants:
        p = base if mode is None else apply_exit(base, mode, param)
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
    print("  ADOPTION CHECK (bar was set BEFORE running)")
    print("-" * 104)
    any_pass = False
    for _, r in df.iloc[1:].iterrows():
        dt = r.tr_sortino - b.tr_sortino
        dh = r.ho_sortino - b.ho_sortino
        ok = (dt >= 0.30) and (dh >= 0)
        any_pass |= ok
        print(f"  {r.variant:30s} train {dt:+.3f}  holdout {dh:+.3f}   "
              f"{'PASS' if ok else 'fail'}")
    print()
    if not any_pass:
        print("  -> NO exit rule clears the bar. Idea 3 REJECTED. Keep no exits.")
    print("=" * 104)


if __name__ == "__main__":
    run()
