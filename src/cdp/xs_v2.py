"""XS funding v2. PRE-REGISTERED. TRAIN ONLY (2020-2024). Holdout locked."""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import xs_funding as xs

BARS = 24 * 365
TRAIN_END = "2024-12-31"


def build(train_only=True):
    p = xs.build_panel()
    if train_only:
        p = p[p.ts <= pd.Timestamp(TRAIN_END, tz="UTC")].copy()
    return p


def signal_z(df, lb_h=24*7):
    df = df.copy()
    raw = (df.groupby("symbol")["known_funding"]
             .transform(lambda s: s.rolling(lb_h, min_periods=lb_h//2).mean()))
    df["f_ma"] = raw.groupby(df["symbol"]).shift(1)
    g = df.groupby("ts")["f_ma"]
    df["z"] = (df["f_ma"] - g.transform("mean")) / g.transform("std")
    df["z"] = df["z"].clip(-3, 3)
    return df


def target_weights(df):
    df = df.copy()
    raw = -df["z"]
    tot = raw.abs().groupby(df["ts"]).transform("sum")
    df["w_tgt"] = np.where(tot > 0, raw / tot, 0.0)
    df["w_tgt"] = df["w_tgt"].fillna(0.0)
    return df


def apply_trading_rules(df, rebal_h, band):
    df = df.sort_values(["symbol", "ts"]).copy()
    df["is_rebal"] = (df["ts"].dt.hour % rebal_h == 0)
    out = []
    for _, g in df.groupby("symbol", sort=False):
        tgt = g["w_tgt"].to_numpy()
        reb = g["is_rebal"].to_numpy()
        held = np.empty(len(g))
        cur = 0.0
        for i in range(len(g)):
            if reb[i] and abs(tgt[i] - cur) > band:
                cur = tgt[i]
            held[i] = cur
        gg = g.copy()
        gg["w"] = held
        out.append(gg)
    return pd.concat(out).sort_values(["ts", "symbol"]).reset_index(drop=True)


def run_bt(panel, lb_h=24*7, rebal_h=24, band=0.005, vol_target=0.15, fee_bps=5.0):
    d = signal_z(panel, lb_h)
    d = target_weights(d)
    if vol_target is not None:
        tmp = apply_trading_rules(d, rebal_h, band)
        r0 = xs.backtest(tmp, 0, fee_bps)
        rv = (r0["pnl"].rolling(24*30, min_periods=24*10).std()
              * np.sqrt(BARS)).shift(1)
        scale = (vol_target / rv).clip(0.25, 3.0)
        d["scale"] = d["ts"].map(scale).ffill().fillna(1.0)
        d["w_tgt"] = d["w_tgt"] * d["scale"]
    d = apply_trading_rules(d, rebal_h, band)
    return xs.backtest(d, 0, fee_bps)


def summarise(res, label):
    s = xs.stats(res["pnl"])
    tot = res[["price_pnl", "funding_pnl", "cost"]].sum() * BARS / len(res)
    return {"config": label, "sharpe": s["sharpe"], "ann_ret": s["ann_ret"],
            "vol": s["ann_vol"], "maxdd": s["maxdd"], "price": tot["price_pnl"],
            "funding": tot["funding_pnl"], "cost": -tot["cost"],
            "turnover": res["turnover"].sum()*BARS/len(res)}


def run():
    pd.set_option("display.width", 220)
    panel = build(train_only=True)
    print("=" * 78)
    print("XS FUNDING v2 -- PRE-REGISTERED, TRAIN SET ONLY")
    print(f"train: {panel.ts.min().date()} .. {panel.ts.max().date()}   HOLDOUT 2025-26 LOCKED")
    print(f"{panel.symbol.nunique()} symbols, {len(panel):,} bars")
    print("=" * 78)
    rows = [
        summarise(run_bt(panel, rebal_h=1,  band=0.0,   vol_target=None), "v1 base (hourly, no band, no vol)"),
        summarise(run_bt(panel, rebal_h=24, band=0.0,   vol_target=None), "+ daily rebalance"),
        summarise(run_bt(panel, rebal_h=24, band=0.005, vol_target=None), "+ no-trade band"),
        summarise(run_bt(panel, rebal_h=24, band=0.005, vol_target=0.15), "+ vol target (FULL v2)"),
    ]
    print("\nABLATION -- what is each lever worth?")
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:+8.3f}"))

    print("\n" + "=" * 78)
    print("FULL v2 -- BY YEAR (train only)")
    print("=" * 78)
    r = run_bt(panel, rebal_h=24, band=0.005, vol_target=0.15)
    yr = []
    for y, g in r.groupby(r.index.year):
        if len(g) < 200:
            continue
        s = xs.stats(g["pnl"])
        yr.append({"year": y, "net": s["ann_ret"], "sharpe": s["sharpe"],
                   "price": g["price_pnl"].sum()*BARS/len(g),
                   "funding": g["funding_pnl"].sum()*BARS/len(g),
                   "cost": -g["cost"].sum()*BARS/len(g)})
    print(pd.DataFrame(yr).set_index("year").to_string(
        float_format=lambda x: f"{x:+.2%}" if abs(x) < 10 else f"{x:.2f}"))

    print("\n" + "=" * 78)
    print("FRAGILITY -- drop the best days (the test that killed v1)")
    print("=" * 78)
    daily = r["pnl"].groupby(r.index.date).sum()
    order = daily.sort_values(ascending=False)
    for n in [0, 5, 10, 20, 40]:
        keep = daily[~daily.index.isin(set(order.head(n).index))]
        ann = keep.mean()*365
        vol = keep.std()*np.sqrt(365)
        print(f"  drop {n:3d} days -> ann {ann:+7.2%}  sharpe {ann/vol:5.2f}")


if __name__ == "__main__":
    run()
