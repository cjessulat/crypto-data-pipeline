"""
Liquidity-weighted sizing.

WHAT IT DOES
    Instead of equal-weighting the signal across all 26 assets, size positions
    in proportion to each asset's dollar volume. Big in BTC/ETH, small in
    SNX/THETA. Directly reduces the cost of trading thin names.

THE HONEST FRAMING
    At <$10k of capital this is a solution to a problem you DO NOT HAVE. The
    capacity ceiling bites at $100k+. Below that, the illiquid names are
    affordable and they are where the edge lives.

    We run it anyway because it is DIAGNOSTIC:
      - if the edge SURVIVES liquidity weighting -> the edge is not really
        about illiquidity, and the capacity ceiling can be raised.
      - if the edge DIES -> confirms the liquidity-provision thesis. The
        ceiling is real and unavoidable, and small capital is a FEATURE.

    I expect the latter. Stating that before running.

    python -m cdp.liq_weight
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import store
from . import xs_funding as xs
from . import xs_v2 as v2
from . import costs as ck
from .survivorship import metrics
from .rerun_real_costs import backtest_real

BARS = 24 * 365
TRAIN_END = pd.Timestamp("2024-12-31", tz="UTC")


def positions(panel, liq_power=0.0, rebal_h=24, band=0.005, dd_scale=False,
              lb_h=24*7):
    """
    liq_power = 0.0  -> equal weight (current behaviour)
    liq_power = 0.5  -> weight by sqrt(dollar volume)   [partial tilt]
    liq_power = 1.0  -> weight by dollar volume         [full tilt]
    """
    d = v2.signal_z(panel, lb_h)
    d = v2.target_weights(d)

    if liq_power > 0:
        # build_panel() drops quote_volume -- pull it from the store and merge.
        if "quote_volume" not in d.columns:
            qv = store.read("perp_klines")[["ts", "symbol", "quote_volume"]]
            d = d.merge(qv, on=["ts", "symbol"], how="left")
            d = d.sort_values(["symbol", "ts"]).reset_index(drop=True)
        # trailing 30d dollar volume, LAGGED (must be knowable at the time)
        dv = (d.groupby("symbol")["quote_volume"]
                .transform(lambda s: s.rolling(24*30, min_periods=24*7).mean())
                .groupby(d["symbol"]).shift(1))
        d["liq"] = dv.fillna(dv.median())
        # normalise liquidity within each bar, then tilt
        rel = d["liq"] / d.groupby("ts")["liq"].transform("median")
        d["w_tgt"] = d["w_tgt"] * (rel ** liq_power)
        # re-neutralise and re-normalise gross to 1.0
        net = d.groupby("ts")["w_tgt"].transform("sum")
        cnt = d.groupby("ts")["w_tgt"].transform(lambda s: (s != 0).sum())
        d["w_tgt"] = d["w_tgt"] - np.where(cnt > 0, net/cnt, 0.0)
        gr = d.groupby("ts")["w_tgt"].transform(lambda s: s.abs().sum())
        d["w_tgt"] = np.where(gr > 0, d["w_tgt"]/gr, 0.0)

    if dd_scale:
        tmp = v2.apply_trading_rules(d, rebal_h, band)
        r0 = xs.backtest(tmp, 0, 5.0)
        eq = (1 + r0["pnl"]).cumprod()
        dd = (eq / eq.cummax() - 1).shift(1)
        sc = (1.0 + dd * 5.0).clip(0.25, 1.0)
        d["scale"] = d["ts"].map(sc).ffill().fillna(1.0)
        d["w_tgt"] = d["w_tgt"] * d["scale"]

    return v2.apply_trading_rules(d, rebal_h, band)


def run():
    pd.set_option("display.width", 240)
    panel = xs.build_panel()

    print("=" * 92)
    print("LIQUIDITY-WEIGHTED SIZING -- diagnostic, not optimisation")
    print("Prediction: the edge DIES, confirming it lives in the thin names.")
    print("=" * 92)

    for cap in [5_000, 10_000, 100_000]:
        cp = ck.build_cost_panel(cap)
        print("\n" + "=" * 92)
        print(f"capital ${cap:,}   (TRAIN 2020-2024)")
        print("=" * 92)
        rows = []
        for lp in [0.0, 0.25, 0.5, 1.0]:
            for dd in [False, True]:
                p = positions(panel, liq_power=lp, dd_scale=dd)
                r = backtest_real(p, cp)
                tr = r[r.index <= TRAIN_END]
                m = metrics(tr["pnl"])
                rows.append({
                    "liq_tilt": lp, "dd_scale": dd,
                    "sortino": m["sortino"], "calmar": m["calmar"],
                    "ret": m["ann_ret"], "maxdd": m["maxdd"],
                    "cost": -tr["cost"].sum()*BARS/len(tr),
                })
        df = pd.DataFrame(rows).sort_values("sortino", ascending=False)
        print(df.to_string(index=False, float_format=lambda x: f"{x:+8.3f}"))
        best = df.iloc[0]
        print(f"\n  best: liq_tilt={best.liq_tilt} dd={best.dd_scale}  "
              f"sortino {best.sortino:.2f}  ret {best.ret:+.1%}  "
              f"maxdd {best.maxdd:+.1%}")


if __name__ == "__main__":
    run()
