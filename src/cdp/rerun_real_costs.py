"""
Re-run EVERY config under the REAL cost model.

The flat 5bps assumption was wrong by 4-8x, and wrong in the worst possible
way: it most understated the cost of exactly the thin names (SNX, THETA, ICP,
CRV) where this strategy makes its money.

Every conclusion drawn so far is downstream of that error. This re-derives
them honestly.

PREDICTION (before running):
    - high-turnover configs (A/B/C, 68-97x) go NEGATIVE
    - low-turnover configs (vol target, DD-scale) survive, not because they
      improve the signal but because they trade less
    - the strategy is marginal at $100k and likely unrunnable at $1m
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import xs_funding as xs
from . import xs_v2 as v2
from . import costs as ck
from .survivorship import metrics

BARS = 24 * 365
TRAIN_END = pd.Timestamp("2024-12-31", tz="UTC")
HO_START = pd.Timestamp("2025-01-01", tz="UTC")


def backtest_real(pos, cost_panel):
    """Same engine, but cost is PER-ASSET, PER-BAR, from the real model."""
    d = pos.sort_values(["ts", "symbol"]).copy()
    d = d.merge(cost_panel[["ts", "symbol", "cost_taker"]],
                on=["ts", "symbol"], how="left")
    d["cost_taker"] = d["cost_taker"].fillna(0.002)   # 20bps if unknown

    d["w_prev"] = d.groupby("symbol")["w"].shift(1).fillna(0.0)
    d["price_pnl"] = d["w_prev"] * d["ret"].fillna(0.0)
    d["funding_pnl"] = np.where(d["settled"],
                                -d["w_prev"]*d["funding_rate"].fillna(0.0), 0.0)
    d["turnover"] = (d["w"] - d["w_prev"]).abs()
    d["cost"] = d["turnover"] * d["cost_taker"]      # <-- the real number

    out = d.groupby("ts").agg(
        price_pnl=("price_pnl", "sum"), funding_pnl=("funding_pnl", "sum"),
        cost=("cost", "sum"), turnover=("turnover", "sum"))
    out["pnl"] = out["price_pnl"] + out["funding_pnl"] - out["cost"]
    return out


def positions(panel, rebal_h=24, band=0.005, vol_target=None, dd_scale=False,
              lb_h=24*7):
    d = v2.signal_z(panel, lb_h)
    d = v2.target_weights(d)
    if vol_target is not None or dd_scale:
        tmp = v2.apply_trading_rules(d, rebal_h, band)
        r0 = xs.backtest(tmp, 0, 5.0)
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
    return v2.apply_trading_rules(d, rebal_h, band)


def run():
    pd.set_option("display.width", 240)
    panel = xs.build_panel()

    cfgs = [
        ("A hourly",              dict(rebal_h=1,  band=0.0,   vol_target=None)),
        ("B daily",               dict(rebal_h=24, band=0.0,   vol_target=None)),
        ("C daily + band",        dict(rebal_h=24, band=0.005, vol_target=None)),
        ("D + vol target 15%",    dict(rebal_h=24, band=0.005, vol_target=0.15)),
        ("E + vol target 10%",    dict(rebal_h=24, band=0.005, vol_target=0.10)),
        ("F + DD-scaling",        dict(rebal_h=24, band=0.005, vol_target=None, dd_scale=True)),
        ("G vol + DD",            dict(rebal_h=24, band=0.005, vol_target=0.15, dd_scale=True)),
        ("H weekly rebal",        dict(rebal_h=168, band=0.01, vol_target=None)),
        ("I weekly + DD",         dict(rebal_h=168, band=0.01, vol_target=None, dd_scale=True)),
    ]
    pos_cache = {lbl: positions(panel, **kw) for lbl, kw in cfgs}

    for cap in [10_000, 100_000]:
        cp = ck.build_cost_panel(cap)
        print("\n" + "=" * 96)
        print(f"REAL COSTS -- capital ${cap:,}")
        print("=" * 96)
        rows = []
        for lbl, _ in cfgs:
            r = backtest_real(pos_cache[lbl], cp)
            tr = r[r.index <= TRAIN_END]
            m = metrics(tr["pnl"])
            rows.append({
                "config": lbl,
                "sortino": m["sortino"], "calmar": m["calmar"],
                "ret": m["ann_ret"], "maxdd": m["maxdd"],
                "cost": -tr["cost"].sum()*BARS/len(tr),
                "turnover": tr["turnover"].sum()*BARS/len(tr),
            })
        df = pd.DataFrame(rows).sort_values("sortino", ascending=False)
        print("\nTRAIN (2020-2024) -- the period WITH hostile regimes")
        print(df.to_string(index=False, float_format=lambda x: f"{x:+8.3f}"))

        alive = df[df.ret > 0]
        print(f"\n  configs still profitable: {len(alive)} of {len(df)}")
        if len(alive):
            print(f"  best: {alive.iloc[0]['config']}  "
                  f"sortino {alive.iloc[0]['sortino']:.2f}  "
                  f"ret {alive.iloc[0]['ret']:+.1%}  "
                  f"cost {alive.iloc[0]['cost']:+.1%}")


if __name__ == "__main__":
    run()
