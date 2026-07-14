"""Lever ablation, judged by SORTINO and CALMAR (not Sharpe)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import xs_funding as xs
from . import xs_v2 as v2
from .survivorship import metrics

BARS = 24 * 365
TRAIN_END = pd.Timestamp("2024-12-31", tz="UTC")
HO_START = pd.Timestamp("2025-01-01", tz="UTC")


def build(panel, rebal_h=24, band=0.005, vol_target=None, dd_scale=False,
          lb_h=24*7, fee_bps=5.0):
    d = v2.signal_z(panel, lb_h)
    d = v2.target_weights(d)
    if vol_target is not None or dd_scale:
        tmp = v2.apply_trading_rules(d, rebal_h, band)
        r0 = xs.backtest(tmp, 0, fee_bps)
        scale = pd.Series(1.0, index=r0.index)
        if vol_target is not None:
            rv = (r0["pnl"].rolling(24*30, min_periods=24*10).std()
                  * np.sqrt(BARS)).shift(1)
            scale = scale * (vol_target / rv).clip(0.25, 3.0)
        if dd_scale:
            eq = (1 + r0["pnl"]).cumprod()
            dd = (eq / eq.cummax() - 1).shift(1)
            scale = scale * (1.0 + dd * 5.0).clip(0.25, 1.0)
        d["scale"] = d["ts"].map(scale).ffill().fillna(1.0)
        d["w_tgt"] = d["w_tgt"] * d["scale"]
    p = v2.apply_trading_rules(d, rebal_h, band)
    return xs.backtest(p, 0, fee_bps)


def row(res, label):
    tr = res[res.index <= TRAIN_END]
    ho = res[res.index >= HO_START]
    out = {"config": label}
    for tag, r in [("tr", tr), ("ho", ho)]:
        m = metrics(r["pnl"])
        out[f"{tag}_sortino"] = m["sortino"]
        out[f"{tag}_calmar"] = m["calmar"]
        out[f"{tag}_sharpe"] = m["sharpe"]
        out[f"{tag}_ret"] = m["ann_ret"]
        out[f"{tag}_dd"] = m["maxdd"]
    out["turnover"] = res["turnover"].sum()*BARS/len(res)
    return out


def run():
    pd.set_option("display.width", 260)
    panel = xs.build_panel()
    print("=" * 100)
    print("LEVER ABLATION -- judged by SORTINO and CALMAR (not Sharpe)")
    print("=" * 100)
    cfgs = [
        ("A hourly, no band, no vol", dict(rebal_h=1,  band=0.0,   vol_target=None)),
        ("B daily rebalance",         dict(rebal_h=24, band=0.0,   vol_target=None)),
        ("C + no-trade band",         dict(rebal_h=24, band=0.005, vol_target=None)),
        ("D + vol target 15%",        dict(rebal_h=24, band=0.005, vol_target=0.15)),
        ("E + vol target 10%",        dict(rebal_h=24, band=0.005, vol_target=0.10)),
        ("F + DD-scaling (new)",      dict(rebal_h=24, band=0.005, vol_target=None, dd_scale=True)),
        ("G vol target + DD",         dict(rebal_h=24, band=0.005, vol_target=0.15, dd_scale=True)),
    ]
    rows = [row(build(panel, **kw), lbl) for lbl, kw in cfgs]
    df = pd.DataFrame(rows)

    print("\nTRAIN (2020-2024)")
    print(df[["config","tr_sortino","tr_calmar","tr_sharpe","tr_ret","tr_dd","turnover"]]
          .to_string(index=False, float_format=lambda x: f"{x:+8.3f}"))
    print("\nHOLDOUT (2025-2026)")
    print(df[["config","ho_sortino","ho_calmar","ho_sharpe","ho_ret","ho_dd"]]
          .to_string(index=False, float_format=lambda x: f"{x:+8.3f}"))

    print("\n" + "=" * 100)
    print("DID THE PREDICTIONS HOLD?")
    print("=" * 100)
    c = df.set_index("config")
    base, vt = "C + no-trade band", "D + vol target 15%"
    for m in ["calmar", "sortino", "sharpe"]:
        a, b = c.loc[base, f"tr_{m}"], c.loc[vt, f"tr_{m}"]
        print(f"  vol target on {m.upper():8s}(train): {a:6.2f} -> {b:6.2f}   "
              f"{'IMPROVED' if b > a else 'WORSE'}")
    print(f"  vol target on MAXDD   (train): {c.loc[base,'tr_dd']:+.1%} -> "
          f"{c.loc[vt,'tr_dd']:+.1%}")
    print("\n  best by TRAIN Calmar :", df.loc[df.tr_calmar.idxmax(), "config"])
    print("  best by TRAIN Sortino:", df.loc[df.tr_sortino.idxmax(), "config"])
    print("  best by TRAIN Sharpe :", df.loc[df.tr_sharpe.idxmax(), "config"])
    print("=" * 100)


if __name__ == "__main__":
    run()
