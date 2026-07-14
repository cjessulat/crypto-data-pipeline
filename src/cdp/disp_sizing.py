"""
Dispersion-based sizing. Three variants, tested honestly.

STEP 1 ESTABLISHED: dispersion is highly forecastable (corr 0.69 with next 5d,
Q5/Q1 ratio 2.53x, autocorr +0.16 even at 63 days). Market RETURNS show ~0
autocorrelation, which confirms the estimator is not manufacturing structure.

STEP 2 ASKS A DIFFERENT QUESTION: does predicting dispersion let us make MONEY?
Not the same thing. Dispersion is symmetric -- assets can decouple AGAINST us.

THREE VARIANTS (they are NOT the same mechanism):
    UP   : size up when dispersion is HIGH -- be there for the episodes
    DOWN : size down when dispersion is LOW -- dead periods just bleed costs
    BOTH : continuous, proportional to expected dispersion

PREDICTIONS (stated before running):
    - DOWN wins. Costs are -16%/yr; halving them in flat stretches is a large,
      reliable gain. Avoiding bleed beats catching episodes.
    - UP disappoints. By the time dispersion is elevated we are often late.
    - Calmar improves more than return.
    - Improvement is MODEST: Sortino ~1.62 -> ~1.8, not -> 3.0.

CIRCULARITY WARNING: the dispersion lead was found BY LOOKING AT THE 10 BEST
DAYS. Everything here is fit on TRAIN only; holdout is checked once, and is
already partially contaminated by earlier observation.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import xs_funding as xs
from . import costs as ck
from .survivorship import metrics
from .rerun_real_costs import backtest_real
from .liq_weight import positions
from .dispersion import daily_dispersion

BARS = 24*365
TRAIN_END = pd.Timestamp("2024-12-31", tz="UTC")
HO_START = pd.Timestamp("2025-01-01", tz="UTC")
CFG = dict(liq_power=0.25, rebal_h=24, band=0.005, dd_scale=False, lb_h=24*7)


def disp_scale(panel, mode, lo=0.5, hi=1.5, win=10):
    """
    Build an hourly scaling series from LAGGED dispersion.

    Dispersion is z-scored against its own trailing 1y distribution, so the
    scaler adapts as the market's baseline dispersion drifts.
    """
    d = daily_dispersion(panel)
    ma = d["xs_disp"].rolling(win).mean().shift(1)      # LAGGED. no lookahead.

    # rank within trailing 1y -> 0..1 percentile
    pct = ma.rolling(365, min_periods=90).apply(
        lambda s: (s.iloc[-1] > s[:-1]).mean(), raw=False)

    if mode == "up":
        # neutral below median, scale UP above it
        s = 1.0 + (pct - 0.5).clip(lower=0) * 2 * (hi - 1.0)
    elif mode == "down":
        # neutral above median, scale DOWN below it
        s = 1.0 - (0.5 - pct).clip(lower=0) * 2 * (1.0 - lo)
    elif mode == "both":
        s = lo + pct * (hi - lo)
    else:
        s = pd.Series(1.0, index=pct.index)

    return s.fillna(1.0)


def run():
    pd.set_option("display.width", 240)
    panel = xs.build_panel()
    base = positions(panel, **CFG)
    cp = ck.build_cost_panel(5_000)

    print("=" * 96)
    print("DISPERSION SIZING -- three mechanisms, compared")
    print("=" * 96)

    rows = []
    variants = [
        ("baseline (no dispersion)", None, 1.0, 1.0),
        ("UP   (1.0 -> 1.5 in high disp)", "up",   1.0, 1.5),
        ("UP   (1.0 -> 2.0 in high disp)", "up",   1.0, 2.0),
        ("DOWN (0.5 -> 1.0 in low disp)",  "down", 0.5, 1.0),
        ("DOWN (0.3 -> 1.0 in low disp)",  "down", 0.3, 1.0),
        ("BOTH (0.5 -> 1.5)",              "both", 0.5, 1.5),
        ("BOTH (0.5 -> 2.0)",              "both", 0.5, 2.0),
    ]

    for lbl, mode, lo, hi in variants:
        p = base.copy()
        if mode is not None:
            s = disp_scale(panel, mode, lo, hi)
            day = p["ts"].dt.floor("D")
            p["w"] = p["w"] * day.map(s).ffill().fillna(1.0).to_numpy()
        r = backtest_real(p, cp)
        tr = r[r.index <= TRAIN_END]
        m = metrics(tr["pnl"])
        rows.append({
            "variant": lbl,
            "sortino": m["sortino"], "calmar": m["calmar"],
            "ret": m["ann_ret"], "maxdd": m["maxdd"],
            "cost": -tr["cost"].sum()*BARS/len(tr),
            "turnover": tr["turnover"].sum()*BARS/len(tr),
        })

    df = pd.DataFrame(rows)
    print("\nTRAIN 2020-2024 (fit here, holdout untouched)")
    print(df.to_string(index=False, float_format=lambda x: f"{x:+8.3f}"))

    b = df.iloc[0]
    best = df.iloc[1:].sort_values("sortino", ascending=False).iloc[0]
    print("\n" + "-" * 96)
    print(f"  baseline : sortino {b.sortino:.3f}  calmar {b.calmar:.3f}  "
          f"ret {b.ret:+.1%}  cost {b.cost:+.1%}")
    print(f"  best     : {best.variant}")
    print(f"             sortino {best.sortino:.3f}  calmar {best.calmar:.3f}  "
          f"ret {best.ret:+.1%}  cost {best.cost:+.1%}")
    print(f"  gain     : sortino {best.sortino-b.sortino:+.3f}   "
          f"calmar {best.calmar-b.calmar:+.3f}")

    print("\n  DID THE PREDICTIONS HOLD?")
    ups = df[df.variant.str.startswith("UP")]["sortino"].max()
    dns = df[df.variant.str.startswith("DOWN")]["sortino"].max()
    print(f"    best UP   variant: sortino {ups:.3f}")
    print(f"    best DOWN variant: sortino {dns:.3f}")
    print(f"    -> {'DOWN wins (predicted)' if dns > ups else 'UP wins (I was WRONG)'}")
    print("=" * 96)


if __name__ == "__main__":
    run()
