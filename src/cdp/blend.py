"""IDEA 4 -- BLEND CROWDING SIGNALS. Changes the SIGNAL, not the sizing."""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import store
from . import xs_funding as xs
from . import xs_v2 as v2
from . import costs as ck
from .survivorship import metrics
from .rerun_real_costs import backtest_real

BARS = 24*365
TRAIN_END = pd.Timestamp("2024-12-31", tz="UTC")
HO_START = pd.Timestamp("2025-01-01", tz="UTC")
LB = 24*7


def build_signals(panel):
    px = store.read("perp_klines")[
        ["ts", "symbol", "close", "volume", "quote_volume", "taker_buy_base"]]
    d = panel.merge(px.drop(columns=["close"]), on=["ts", "symbol"], how="left")
    d = d.sort_values(["symbol", "ts"]).reset_index(drop=True)
    g = d.groupby("symbol")

    d["s_funding"] = (g["known_funding"]
                      .transform(lambda s: s.rolling(LB, min_periods=LB//2).mean())
                      .groupby(d["symbol"]).shift(1))

    imb = (d["taker_buy_base"] / d["volume"].replace(0, np.nan)).clip(0, 1)
    d["s_taker"] = (imb.groupby(d["symbol"])
                       .transform(lambda s: s.rolling(LB, min_periods=LB//2).mean())
                       .groupby(d["symbol"]).shift(1))

    r = g["close"].pct_change()
    sv = r.groupby(d["symbol"]).transform(lambda s: s.rolling(LB).std())
    lv = r.groupby(d["symbol"]).transform(lambda s: s.rolling(24*60).std())
    d["s_vol"] = (sv / lv).groupby(d["symbol"]).shift(1)

    qv = d["quote_volume"]
    d["s_volu"] = ((qv / qv.groupby(d["symbol"])
                      .transform(lambda s: s.rolling(24*30, min_periods=24*7).mean()))
                   .groupby(d["symbol"]).shift(1))

    ma = g["close"].transform(lambda s: s.rolling(24*30, min_periods=24*7).mean())
    d["s_ext"] = ((d["close"] / ma - 1).groupby(d["symbol"]).shift(1))

    for c in ["s_funding", "s_taker", "s_vol", "s_volu", "s_ext"]:
        gg = d.groupby("ts")[c]
        d[c + "_z"] = ((d[c] - gg.transform("mean")) / gg.transform("std")).clip(-3, 3)
    return d


def positions_from(d, weights, liq_power=0.25, rebal_h=24, band=0.005):
    d = d.copy()
    d["z"] = sum(w * d[f"{k}_z"].fillna(0.0) for k, w in weights.items())
    d = v2.target_weights(d)
    if liq_power > 0:
        dv = (d.groupby("symbol")["quote_volume"]
                .transform(lambda s: s.rolling(24*30, min_periods=24*7).mean())
                .groupby(d["symbol"]).shift(1))
        d["liq"] = dv.fillna(dv.median())
        rel = d["liq"] / d.groupby("ts")["liq"].transform("median")
        d["w_tgt"] = d["w_tgt"] * (rel ** liq_power)
        net = d.groupby("ts")["w_tgt"].transform("sum")
        cnt = d.groupby("ts")["w_tgt"].transform(lambda s: (s != 0).sum())
        d["w_tgt"] = d["w_tgt"] - np.where(cnt > 0, net/cnt, 0.0)
        gr = d.groupby("ts")["w_tgt"].transform(lambda s: s.abs().sum())
        d["w_tgt"] = np.where(gr > 0, d["w_tgt"]/gr, 0.0)
    return v2.apply_trading_rules(d, rebal_h, band)


def run():
    pd.set_option("display.width", 240)
    panel = xs.build_panel()
    d = build_signals(panel)
    cp = ck.build_cost_panel(5_000)

    print("=" * 104)
    print("SIGNAL CORRELATIONS -- if taker just replicates funding, it cannot help")
    print("=" * 104)
    cols = ["s_funding_z", "s_taker_z", "s_vol_z", "s_volu_z", "s_ext_z"]
    print(d[cols].corr().to_string(float_format=lambda x: f"{x:+.3f}"))

    variants = [
        ("funding only (baseline)", {"s_funding": 1.0}),
        ("taker imbalance only",    {"s_taker": 1.0}),
        ("vol spike only",          {"s_vol": 1.0}),
        ("price extension only",    {"s_ext": 1.0}),
        ("funding + taker 50/50",   {"s_funding": 0.5, "s_taker": 0.5}),
        ("funding + taker 70/30",   {"s_funding": 0.7, "s_taker": 0.3}),
        ("funding+taker+ext",       {"s_funding": 0.5, "s_taker": 0.3, "s_ext": 0.2}),
        ("all four equal",          {"s_funding": 0.25, "s_taker": 0.25,
                                     "s_vol": 0.25, "s_ext": 0.25}),
    ]

    rows = []
    for lbl, wts in variants:
        r = backtest_real(positions_from(d, wts), cp)
        tr = r[r.index <= TRAIN_END]
        ho = r[r.index >= HO_START]
        m, mh = metrics(tr["pnl"]), metrics(ho["pnl"])
        rows.append({
            "variant": lbl,
            "tr_sortino": m["sortino"], "tr_calmar": m["calmar"],
            "tr_ret": m["ann_ret"], "tr_maxdd": m["maxdd"],
            "ho_sortino": mh["sortino"], "ho_ret": mh["ann_ret"],
            "ho_maxdd": mh["maxdd"],
        })

    df = pd.DataFrame(rows)
    print("\n" + "=" * 104)
    print("BLENDED SIGNALS")
    print("=" * 104)
    print(df.to_string(index=False, float_format=lambda x: f"{x:+8.3f}"))

    b = df.iloc[0]
    print("\n  ADOPTION CHECK (bar: train +0.30 AND holdout non-negative)")
    for _, r in df.iloc[1:].iterrows():
        dt = r.tr_sortino - b.tr_sortino
        dh = r.ho_sortino - b.ho_sortino
        ok = (dt >= 0.30) and (dh >= 0)
        print(f"  {r.variant:26s} train {dt:+.3f}  holdout {dh:+.3f}   "
              f"{'PASS' if ok else 'fail'}")

    print("\n  THE REAL QUESTION -- anything help in the LOW-FUNDING era?")
    print(f"  baseline holdout sortino : {b.ho_sortino:+.3f}")
    best = df.sort_values("ho_sortino", ascending=False).iloc[0]
    print(f"  best holdout             : {best.variant}  {best.ho_sortino:+.3f}")
    print("=" * 104)


if __name__ == "__main__":
    run()
