"""Survivorship bias: a BOUND, not a fix. Sortino/Calmar metrics."""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import xs_funding as xs
from . import xs_v2 as v2

BARS = 24 * 365
CFG = dict(lb_h=24*7, rebal_h=24, band=0.005, vol_target=0.15, fee_bps=5.0)


def metrics(p):
    if len(p) < 100 or p.std() == 0:
        return dict(ann_ret=np.nan, ann_vol=np.nan, sharpe=np.nan,
                    sortino=np.nan, calmar=np.nan, maxdd=np.nan)
    ann_ret = p.mean() * BARS
    ann_vol = p.std() * np.sqrt(BARS)
    dn = p[p < 0]
    dnside = dn.std() * np.sqrt(BARS) if len(dn) > 1 else np.nan
    eq = (1 + p).cumprod()
    maxdd = (eq / eq.cummax() - 1).min()
    return dict(ann_ret=ann_ret, ann_vol=ann_vol,
                sharpe=ann_ret/ann_vol if ann_vol else np.nan,
                sortino=ann_ret/dnside if dnside and dnside > 0 else np.nan,
                calmar=ann_ret/abs(maxdd) if maxdd else np.nan, maxdd=maxdd)


def flag_distress(panel):
    d = panel.sort_values(["symbol", "ts"]).copy()
    d["ret90"] = (d.groupby("symbol")["close"].transform(lambda s: s.pct_change(24*90))
                    .groupby(d["symbol"]).shift(1))
    vol = d["quote_volume"] if "quote_volume" in d.columns else d["close"]
    d["dv30"] = (vol.groupby(d["symbol"])
                    .transform(lambda s: s.rolling(24*30, min_periods=24*7).mean())
                    .groupby(d["symbol"]).shift(1))
    d["r_ret"] = d.groupby("ts")["ret90"].rank(pct=True)
    d["r_vol"] = d.groupby("ts")["dv30"].rank(pct=True)
    d["distressed"] = (d["r_ret"] < 0.25) & (d["r_vol"] < 0.25)
    return d


def positions(panel, exclude_distressed=False):
    d = v2.signal_z(panel, CFG["lb_h"])
    d = v2.target_weights(d)
    if exclude_distressed:
        d.loc[d["distressed"].fillna(False), "w_tgt"] = 0.0
        net = d.groupby("ts")["w_tgt"].transform("sum")
        cnt = d.groupby("ts")["w_tgt"].transform(lambda s: (s != 0).sum())
        adj = np.where(cnt > 0, net/cnt, 0.0)
        d["w_tgt"] = np.where(d["w_tgt"] != 0, d["w_tgt"] - adj, 0.0)
        gr = d.groupby("ts")["w_tgt"].transform(lambda s: s.abs().sum())
        d["w_tgt"] = np.where(gr > 0, d["w_tgt"]/gr, 0.0)
    tmp = v2.apply_trading_rules(d, CFG["rebal_h"], CFG["band"])
    r0 = xs.backtest(tmp, 0, CFG["fee_bps"])
    rv = (r0["pnl"].rolling(24*30, min_periods=24*10).std()*np.sqrt(BARS)).shift(1)
    d["scale"] = d["ts"].map((CFG["vol_target"]/rv).clip(0.25, 3.0)).ffill().fillna(1.0)
    d["w_tgt"] = d["w_tgt"] * d["scale"]
    return v2.apply_trading_rules(d, CFG["rebal_h"], CFG["band"])


def run():
    pd.set_option("display.width", 220)
    panel = flag_distress(xs.build_panel())
    print("=" * 78)
    print("SURVIVORSHIP BIAS -- a bound, not a fix")
    print("=" * 78)
    print(f"\n'distressed' bars (bottom-25% ret AND vol): {panel['distressed'].mean():.1%}")
    top = (panel[panel.distressed].groupby("symbol").size()
           / panel.groupby("symbol").size()).dropna().sort_values(ascending=False)
    print("\nmost-distressed names (share of own history flagged):")
    print(top.head(8).to_string(float_format=lambda x: f"{x:.1%}"))

    pos = positions(panel, False)
    pos["w_prev"] = pos.groupby("symbol")["w"].shift(1).fillna(0.0)
    pos["price_pnl"] = pos["w_prev"] * pos["ret"].fillna(0.0)
    pos["funding_pnl"] = np.where(pos["settled"],
                                  -pos["w_prev"]*pos["funding_rate"].fillna(0.0), 0.0)
    pos["pnl"] = pos["price_pnl"] + pos["funding_pnl"]
    dpos = pos[pos["distressed"].fillna(False)]
    tot, dis = pos["pnl"].sum(), dpos["pnl"].sum()
    print("\n" + "-" * 78)
    print("P&L FROM DISTRESSED POSITIONS")
    print("-" * 78)
    print(f"  total P&L       : {tot:+8.3f}")
    print(f"  from distressed : {dis:+8.3f}   ({dis/tot:.0%} of total)")
    print(f"  share of expo   : "
          f"{dpos['w_prev'].abs().sum()/pos['w_prev'].abs().sum():.1%}")

    print("\n" + "=" * 78)
    print("THE TEST -- re-run EXCLUDING all distressed positions")
    print("(conservative: also drops the winners, so this is a LOWER bound)")
    print("=" * 78)
    rows = []
    for label, excl in [("baseline (all)", False), ("EXCL distressed", True)]:
        r = xs.backtest(positions(panel, excl), 0, CFG["fee_bps"])
        ho = r[r.index >= pd.Timestamp("2025-01-01", tz="UTC")]
        for per, rr in [("full", r), ("holdout", ho)]:
            m = metrics(rr["pnl"])
            rows.append({"config": label, "period": per, "sortino": m["sortino"],
                         "calmar": m["calmar"], "sharpe": m["sharpe"],
                         "ann_ret": m["ann_ret"], "maxdd": m["maxdd"]})
    df = pd.DataFrame(rows)
    print()
    print(df.to_string(index=False, float_format=lambda x: f"{x:+8.3f}"))

    b = df[(df.config == "baseline (all)") & (df.period == "holdout")].iloc[0]
    e = df[(df.config == "EXCL distressed") & (df.period == "holdout")].iloc[0]
    print("\n" + "=" * 78)
    print(f"  holdout Sortino {b.sortino:.2f} -> {e.sortino:.2f} "
          f"({e.sortino/b.sortino:.0%} retained)")
    print(f"  holdout return  {b.ann_ret:+.2%} -> {e.ann_ret:+.2%}")
    if e.ann_ret <= 0:
        print("\n  VERDICT: SEVERE. Edge lives entirely in distressed names. STOP.")
    elif e.sortino < b.sortino * 0.5:
        print("\n  VERDICT: MATERIAL. Real returns well below reported.")
    else:
        print("\n  VERDICT: MILD. Edge survives. Bias inflates but does not create.")
    print("=" * 78)


if __name__ == "__main__":
    run()
