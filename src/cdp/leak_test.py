"""
Is the holdout contaminated?

The vol-target scalar was computed from a FULL-SAMPLE backtest, then sliced.
If that rolling vol estimate leaked future information, the holdout Sharpe of
2.45 is fiction.

TEST: recompute the holdout STRICTLY CAUSALLY -- at each bar, using only data
that existed at that bar -- and compare. If the weights differ, we leaked.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import xs_funding as xs
from . import xs_v2 as v2

BARS = 24 * 365
CFG = dict(lb_h=24*7, rebal_h=24, band=0.005, vol_target=0.15, fee_bps=5.0)
CUT = pd.Timestamp("2025-01-01", tz="UTC")


def weights_from(panel, **cfg):
    """Reproduce v2's weight construction, returning the weights themselves."""
    d = v2.signal_z(panel, cfg["lb_h"])
    d = v2.target_weights(d)
    if cfg["vol_target"] is not None:
        tmp = v2.apply_trading_rules(d, cfg["rebal_h"], cfg["band"])
        r0 = xs.backtest(tmp, 0, cfg["fee_bps"])
        rv = (r0["pnl"].rolling(24*30, min_periods=24*10).std()
              * np.sqrt(BARS)).shift(1)
        scale = (cfg["vol_target"] / rv).clip(0.25, 3.0)
        d["scale"] = d["ts"].map(scale).ffill().fillna(1.0)
        d["w_tgt"] = d["w_tgt"] * d["scale"]
    return v2.apply_trading_rules(d, cfg["rebal_h"], cfg["band"])


def run():
    pd.set_option("display.width", 200)
    full = xs.build_panel()

    print("=" * 78)
    print("LEAKAGE TEST -- did the vol-target peek at the future?")
    print("=" * 78)

    # A) what we DID: full panel, then slice
    w_full = weights_from(full, **CFG)
    w_full = w_full[w_full.ts >= CUT][["ts", "symbol", "w"]].rename(
        columns={"w": "w_full"})

    # B) STRICTLY CAUSAL: expanding window. At each month in the holdout,
    #    rebuild using ONLY data up to that month.
    print("\nrebuilding holdout causally, month by month...")
    months = pd.date_range(CUT, full.ts.max(), freq="MS", tz="UTC")
    pieces = []
    for m in months:
        nxt = m + pd.DateOffset(months=1)
        past = full[full.ts < nxt].copy()       # ONLY data that existed then
        w = weights_from(past, **CFG)
        seg = w[(w.ts >= m) & (w.ts < nxt)][["ts", "symbol", "w"]]
        pieces.append(seg)
    w_causal = pd.concat(pieces).rename(columns={"w": "w_causal"})

    m = w_full.merge(w_causal, on=["ts", "symbol"], how="inner")
    m["diff"] = (m["w_full"] - m["w_causal"]).abs()

    print(f"\ncompared {len(m):,} (bar, symbol) weights")
    print(f"  max  abs diff : {m['diff'].max():.8f}")
    print(f"  mean abs diff : {m['diff'].mean():.8f}")
    print(f"  n differing   : {(m['diff'] > 1e-9).sum():,}  "
          f"({(m['diff'] > 1e-9).mean():.2%})")

    print("\n" + "=" * 78)
    if m["diff"].max() < 1e-9:
        print("  CLEAN. Weights are identical. No lookahead. Holdout stands.")
    else:
        print("  *** LEAKAGE DETECTED ***")
        print("  The full-panel weights differ from the causal ones.")
        print("  The holdout result is CONTAMINATED and must be re-run.")
        # quantify the damage
        d = full.merge(w_causal, on=["ts", "symbol"], how="right")
        d = d.rename(columns={"w_causal": "w"})
        r = xs.backtest(d, 0, CFG["fee_bps"])
        s = xs.stats(r["pnl"])
        print(f"\n  TRUE causal holdout Sharpe : {s['sharpe']:+.2f}")
        print(f"  TRUE causal holdout return : {s['ann_ret']:+.2%}")
        print(f"  (reported was Sharpe +2.45, return +39.90%)")
    print("=" * 78)


if __name__ == "__main__":
    run()
