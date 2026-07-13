"""Forensics: is the XS-funding result real, or is it one lucky 2021 trade?"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import store
from . import xs_funding as xs

BARS_PER_YEAR = 24 * 365


def _run(panel, n_side=3, lb_h=24*7, fee_bps=5.0):
    b = xs.make_signal(panel, lb_h)
    p = xs.build_positions(b, n_side)
    return p, xs.backtest(p, n_side, fee_bps)


def attribution(pos):
    d = pos.copy()
    d["w_prev"] = d.groupby("symbol")["w"].shift(1).fillna(0.0)
    d["price_pnl"] = d["w_prev"] * d["ret"].fillna(0.0)
    d["funding_pnl"] = np.where(d["settled"],
                                -d["w_prev"] * d["funding_rate"].fillna(0.0), 0.0)
    d["pnl"] = d["price_pnl"] + d["funding_pnl"]

    print("\n" + "=" * 74)
    print("  1. ATTRIBUTION BY SYMBOL (whole sample)")
    print("=" * 74)
    a = (d.groupby("symbol")[["price_pnl", "funding_pnl", "pnl"]].sum()
           .sort_values("pnl", ascending=False))
    a["share"] = a["pnl"] / a["pnl"].sum()
    print(a.to_string(float_format=lambda x: f"{x:+8.3f}"))

    print("\n  --- 2021 ONLY ---")
    d21 = d[d.ts.dt.year == 2021]
    a21 = (d21.groupby("symbol")[["price_pnl", "funding_pnl", "pnl"]].sum()
              .sort_values("pnl", ascending=False))
    a21["share"] = a21["pnl"] / a21["pnl"].sum()
    print(a21.to_string(float_format=lambda x: f"{x:+8.3f}"))

    print("\n  --- TOP 10 SINGLE DAYS ---")
    daily = d.groupby(d.ts.dt.date)["pnl"].sum().sort_values(ascending=False)
    top = daily.head(10)
    print(top.to_string(float_format=lambda x: f"{x:+.2%}"))
    print(f"\n  those 10 days = {top.sum():+.1%} of {daily.sum():+.1%} total "
          f"({top.sum()/daily.sum():.0%} of ALL P&L)")


def leave_one_out(panel):
    print("\n" + "=" * 74)
    print("  2. LEAVE-ONE-OUT (drop each symbol, refit)")
    print("  A robust edge survives losing any single name.")
    print("=" * 74)
    _, full = _run(panel)
    base = xs.stats(full["pnl"])
    rows = [{"dropped": "(none)", "sharpe": base["sharpe"],
             "ann_ret": base["ann_ret"], "d_sharpe": 0.0}]
    for sym in sorted(panel.symbol.unique()):
        _, r = _run(panel[panel.symbol != sym].copy())
        s = xs.stats(r["pnl"])
        rows.append({"dropped": sym, "sharpe": s["sharpe"],
                     "ann_ret": s["ann_ret"],
                     "d_sharpe": s["sharpe"] - base["sharpe"]})
    df = pd.DataFrame(rows).sort_values("sharpe")
    print(df.to_string(index=False, float_format=lambda x: f"{x:+7.3f}"))


def drop_best_days(res):
    print("\n" + "=" * 74)
    print("  3. DROP THE BEST DAYS")
    print("  Real edge: degrades gracefully. Luck: collapses.")
    print("=" * 74)
    daily = res["pnl"].groupby(res.index.date).sum()
    order = daily.sort_values(ascending=False)
    rows = []
    for n in [0, 1, 3, 5, 10, 20, 40]:
        keep = daily[~daily.index.isin(set(order.head(n).index))]
        ann = keep.mean() * 365
        vol = keep.std() * np.sqrt(365)
        rows.append({"days_dropped": n, "pct_sample": n/len(daily),
                     "ann_ret": ann, "sharpe": ann/vol if vol else np.nan})
    df = pd.DataFrame(rows)
    print(df.to_string(index=False, float_format=lambda x: f"{x:8.3f}"))
    s0 = df.iloc[0]["sharpe"]
    s10 = df[df.days_dropped == 10].iloc[0]["sharpe"]
    print(f"\n  Sharpe {s0:.2f} -> {s10:.2f} after dropping 10 days "
          f"({10/len(daily):.1%} of sample)")
    if s10 < s0 * 0.5:
        print("  VERDICT: FRAGILE. Edge lives in a handful of days.")
    elif s10 < s0 * 0.75:
        print("  VERDICT: concentrated but not fatal.")
    else:
        print("  VERDICT: robust. Edge spread across the sample.")


def ex_2021(panel):
    print("\n" + "=" * 74)
    print("  4. THE BLUNT TEST -- excise 2021 entirely")
    print("=" * 74)
    _, r = _run(panel[panel.ts.dt.year != 2021].copy())
    s = xs.stats(r["pnl"])
    tot = r[["price_pnl", "funding_pnl", "cost"]].sum() * BARS_PER_YEAR / len(r)
    print(f"  WITHOUT 2021:")
    print(f"    ann return {s['ann_ret']:+7.2%}   vol {s['ann_vol']:6.2%}   "
          f"Sharpe {s['sharpe']:5.2f}   maxDD {s['maxdd']:7.2%}")
    print(f"    price leg  {tot['price_pnl']:+7.2%}")
    print(f"    funding    {tot['funding_pnl']:+7.2%}")
    print(f"    costs      {-tot['cost']:+7.2%}")


def run():
    pd.set_option("display.width", 200)
    panel = xs.build_panel()
    print("=" * 74)
    print("FORENSICS: is the XS-funding result real, or is it 2021?")
    print("=" * 74)
    pos, res = _run(panel)
    attribution(pos)
    leave_one_out(panel)
    drop_best_days(res)
    ex_2021(panel)


if __name__ == "__main__":
    run()
