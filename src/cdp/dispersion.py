"""
Is cross-sectional dispersion PREDICTABLE?

WHY THIS IS DANGEROUS
    This is regime timing, which I flagged in session 1 as "an overfitting
    superhighway". Worse: I found the dispersion signal BY LOOKING AT THE TEN
    BEST DAYS. Building a predictor of the thing I discovered by examining the
    outcome is textbook circularity. Left unchecked I will build something that
    "predicts" those exact ten days and nothing else.

THE DISCIPLINE
    STEP 1 tests whether dispersion predicts ITSELF -- a property of the
    MARKET, independent of our strategy or its P&L. If lagged dispersion does
    not forecast future dispersion, there is nothing to time, and we STOP. No
    hunting for a version that works.

    Only if STEP 1 passes do we look at STEP 2.

PREDICTION (before running):
    dispersion WILL be autocorrelated (vol-like quantities almost always are),
    but the TRADEABLE gain will be small -- by the time dispersion is elevated,
    the episode is often already underway.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import xs_funding as xs

BARS = 24*365


def daily_dispersion(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Cross-sectional dispersion = std of returns ACROSS assets, per day.
    High dispersion = assets decoupling. Low = everything moving together.
    """
    d = panel.copy()
    d["date"] = d["ts"].dt.floor("D")
    daily = (d.groupby(["date", "symbol"])["close"].last().unstack())
    rets = daily.pct_change()

    out = pd.DataFrame({
        "xs_disp": rets.std(axis=1),          # dispersion ACROSS assets
        "mkt_ret": rets.mean(axis=1),         # equal-weight market
        "mkt_absret": rets.mean(axis=1).abs(),
    })
    return out.dropna()


def run():
    pd.set_option("display.width", 200)
    panel = xs.build_panel()
    d = daily_dispersion(panel)

    print("=" * 84)
    print("STEP 1 -- IS DISPERSION PREDICTABLE FROM ITS OWN PAST?")
    print("If not, there is nothing to time. We stop here.")
    print("=" * 84)
    print(f"\n{len(d)} days, {d.index.min().date()} .. {d.index.max().date()}")
    print(f"mean dispersion {d.xs_disp.mean():.4f}   "
          f"std {d.xs_disp.std():.4f}")

    print("\n--- AUTOCORRELATION of daily dispersion ---")
    for lag in [1, 2, 3, 5, 10, 21, 63]:
        ac = d["xs_disp"].autocorr(lag)
        bar = "#" * int(max(0, ac) * 50)
        print(f"  lag {lag:3d}d : {ac:+.3f}  {bar}")

    print("\n  (for reference -- market RETURN autocorrelation, should be ~0)")
    for lag in [1, 5, 21]:
        print(f"  lag {lag:3d}d : {d['mkt_ret'].autocorr(lag):+.3f}")

    # --- does PAST dispersion predict FUTURE dispersion out of sample?
    print("\n--- PREDICTIVE TEST (strictly lagged, no lookahead) ---")
    d = d.copy()
    for w in [5, 10, 21]:
        d[f"disp_ma{w}"] = d["xs_disp"].rolling(w).mean().shift(1)

    fwd = d["xs_disp"].rolling(5).mean().shift(-5)   # NEXT 5 days
    rows = []
    for w in [5, 10, 21]:
        sig = d[f"disp_ma{w}"]
        ok = sig.notna() & fwd.notna()
        rows.append({
            "signal": f"trailing {w}d dispersion",
            "corr_with_next_5d": np.corrcoef(sig[ok], fwd[ok])[0, 1],
        })
    print(pd.DataFrame(rows).to_string(index=False,
                                       float_format=lambda x: f"{x:+.3f}"))

    # --- quintile test: sort days by trailing dispersion, look at what follows
    print("\n--- QUINTILE TEST ---")
    print("Sort days by TRAILING dispersion. What happens NEXT?")
    d["q"] = pd.qcut(d["disp_ma10"], 5, labels=["Q1 low", "Q2", "Q3", "Q4", "Q5 high"])
    fwd5 = d["xs_disp"].rolling(5).mean().shift(-5)
    d["fwd_disp"] = fwd5
    q = d.groupby("q", observed=True).agg(
        n=("fwd_disp", "size"),
        trailing_disp=("disp_ma10", "mean"),
        NEXT_5d_disp=("fwd_disp", "mean"),
    )
    print(q.to_string(float_format=lambda x: f"{x:.4f}"))

    lo = q.loc["Q1 low", "NEXT_5d_disp"]
    hi = q.loc["Q5 high", "NEXT_5d_disp"]
    print(f"\n  high-dispersion days are followed by {hi/lo:.2f}x the dispersion")
    print(f"  of low-dispersion days.")

    print("\n" + "=" * 84)
    ac1 = d["xs_disp"].autocorr(1)
    if ac1 < 0.1:
        print("  VERDICT: NOT PREDICTABLE. Nothing to time. STOP.")
    elif hi / lo < 1.3:
        print("  VERDICT: WEAKLY predictable. Probably not worth the complexity.")
    else:
        print("  VERDICT: PREDICTABLE. Worth testing as a sizing overlay.")
        print("  (but remember: predicting dispersion != predicting PROFIT)")
    print("=" * 84)


if __name__ == "__main__":
    run()
