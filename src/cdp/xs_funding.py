"""Cross-sectional funding: long lowest-funding, short highest. Dollar-neutral."""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import store

PPY = 3 * 365
BARS_PER_YEAR = 24 * 365


def build_panel():
    px = store.read("perp_klines")[["ts", "symbol", "close"]]
    fx = store.read("funding")[["ts", "symbol", "funding_rate"]].copy()
    fx["ts"] = fx["ts"].dt.floor("h")
    fx = fx.drop_duplicates(subset=["ts", "symbol"], keep="last")
    df = px.merge(fx, on=["ts", "symbol"], how="left")
    df = df.sort_values(["symbol", "ts"]).reset_index(drop=True)
    df["settled"] = df["funding_rate"].notna()
    df["known_funding"] = df.groupby("symbol")["funding_rate"].ffill()
    df["ret"] = df.groupby("symbol")["close"].pct_change()
    return df


def make_signal(df, lookback_h):
    df = df.copy()
    raw = (df.groupby("symbol")["known_funding"]
             .transform(lambda s: s.rolling(lookback_h, min_periods=lookback_h//2).mean()))
    df["signal"] = raw.groupby(df["symbol"]).shift(1)
    return df


def _assert_no_lookahead(df):
    g = df[df.symbol == df.symbol.iloc[0]].sort_values("ts")
    raw = g["known_funding"].rolling(24, min_periods=12).mean()
    chk = g["signal"].reset_index(drop=True)
    ref = raw.shift(1).reset_index(drop=True)
    both = chk.notna() & ref.notna()
    if both.sum() and not np.allclose(chk[both], ref[both]):
        raise AssertionError("LOOKAHEAD DETECTED")


def build_positions(df, n_side):
    df = df.copy()
    df["rank"] = df.groupby("ts")["signal"].rank(method="first")
    df["n_avail"] = df.groupby("ts")["signal"].transform("count")
    w = pd.Series(0.0, index=df.index)
    ok = df["n_avail"] >= 2 * n_side
    w[ok & (df["rank"] <= n_side)] = 0.5 / n_side
    w[ok & (df["rank"] > df["n_avail"] - n_side)] = -0.5 / n_side
    df["w"] = w
    return df


def backtest(df, n_side, fee_bps):
    df = df.sort_values(["ts", "symbol"]).copy()
    df["w_prev"] = df.groupby("symbol")["w"].shift(1).fillna(0.0)
    df["price_pnl"] = df["w_prev"] * df["ret"].fillna(0.0)
    df["funding_pnl"] = np.where(df["settled"],
                                 -df["w_prev"] * df["funding_rate"].fillna(0.0), 0.0)
    df["turnover"] = (df["w"] - df["w_prev"]).abs()
    df["cost"] = df["turnover"] * (fee_bps / 1e4)
    out = df.groupby("ts").agg(
        price_pnl=("price_pnl", "sum"), funding_pnl=("funding_pnl", "sum"),
        cost=("cost", "sum"), turnover=("turnover", "sum"),
        gross=("w", lambda s: s.abs().sum()), net=("w", "sum"))
    out["pnl"] = out["price_pnl"] + out["funding_pnl"] - out["cost"]
    return out


def stats(p):
    if p.std() == 0 or len(p) < 100:
        return {"ann_ret": np.nan, "ann_vol": np.nan, "sharpe": np.nan, "maxdd": np.nan}
    ar = p.mean() * BARS_PER_YEAR
    av = p.std() * np.sqrt(BARS_PER_YEAR)
    eq = (1 + p).cumprod()
    return {"ann_ret": ar, "ann_vol": av, "sharpe": ar/av if av else np.nan,
            "maxdd": (eq/eq.cummax() - 1).min()}


def report(res, label):
    s = stats(res["pnl"])
    print("\n" + "=" * 74)
    print(f"  {label}")
    print("=" * 74)
    print(f"  ann return {s['ann_ret']:+7.2%}   vol {s['ann_vol']:6.2%}   "
          f"Sharpe {s['sharpe']:5.2f}   maxDD {s['maxdd']:7.2%}")
    tot = res[["price_pnl", "funding_pnl", "cost"]].sum() * BARS_PER_YEAR / len(res)
    print("\n  P&L DECOMPOSITION (annualised):")
    print(f"    price leg   {tot['price_pnl']:+7.2%}   <- the delta bet")
    print(f"    funding     {tot['funding_pnl']:+7.2%}   <- the carry")
    print(f"    costs       {-tot['cost']:+7.2%}")
    print("    " + "-" * 26)
    print(f"    net         {s['ann_ret']:+7.2%}")
    print("\n  BY YEAR  (does it work OUTSIDE 2021?)")
    yr = []
    for y, g in res.groupby(res.index.year):
        if len(g) < 200:
            continue
        ys = stats(g["pnl"])
        yr.append({"year": y, "net": ys["ann_ret"], "sharpe": ys["sharpe"],
                   "price": g["price_pnl"].sum()*BARS_PER_YEAR/len(g),
                   "funding": g["funding_pnl"].sum()*BARS_PER_YEAR/len(g)})
    print(pd.DataFrame(yr).set_index("year").to_string(
        float_format=lambda x: f"{x:+.2%}" if abs(x) < 10 else f"{x:.2f}"))


def run():
    pd.set_option("display.width", 200)
    print("=" * 74)
    print("CROSS-SECTIONAL FUNDING")
    print("Long lowest-funding, short highest-funding. Dollar-neutral.")
    print("=" * 74)
    panel = build_panel()
    print(f"panel: {len(panel):,} bars  {panel.ts.min().date()} -> "
          f"{panel.ts.max().date()}  {panel.symbol.nunique()} symbols")
    base = make_signal(panel, 24*7)
    _assert_no_lookahead(make_signal(panel, 24))
    print("no-lookahead assertion: PASSED")
    pos = build_positions(base, n_side=3)
    report(backtest(pos, 3, 5.0), "BASE: 7d lookback, 3 long / 3 short, 5bps")
    print("\n" + "=" * 74)
    print("  PARAMETER SENSITIVITY -- Sharpe")
    print("  Want a FLAT surface. A lone spike = overfitting, not edge.")
    print("=" * 74)
    grid = []
    for lb in [1, 3, 7, 14, 30]:
        row = {"lookback_d": lb}
        for ns in [2, 3, 4]:
            b = make_signal(panel, 24*lb)
            p = build_positions(b, ns)
            row[f"n={ns}"] = stats(backtest(p, ns, 5.0)["pnl"])["sharpe"]
        grid.append(row)
    print(pd.DataFrame(grid).set_index("lookback_d").to_string(
        float_format=lambda x: f"{x:6.2f}"))


if __name__ == "__main__":
    run()
