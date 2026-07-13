"""
Funding economics: what does the raw material actually look like?
DESCRIPTIVE, not a backtest. Funding is a CASH FLOW, not a return.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import store

PERIODS_PER_YEAR = 3 * 365


def _ann(x):
    return x * PERIODS_PER_YEAR


def per_symbol():
    f = store.read("funding")
    rows = []
    for sym, g in f.groupby("symbol"):
        r = g["funding_rate"]
        rows.append({
            "symbol": sym,
            "years": round((g.ts.max() - g.ts.min()).days / 365.25, 1),
            "n": len(r),
            "mean_ann": _ann(r.mean()),
            "median_ann": _ann(r.median()),
            "pct_pos": (r > 0).mean(),
            "stream_sharpe": (r.mean() / r.std()) * np.sqrt(PERIODS_PER_YEAR),
            "worst_8h": r.min(),
            "best_8h": r.max(),
            "skew": r.skew(),
            "kurt": r.kurtosis(),
        })
    return pd.DataFrame(rows).sort_values("mean_ann", ascending=False)


def by_year():
    f = store.read("funding")
    f["year"] = f.ts.dt.year
    p = (f.groupby(["year", "symbol"])["funding_rate"].mean()
           .mul(PERIODS_PER_YEAR).unstack())
    p["MEAN"] = p.mean(axis=1)
    return p


def concentration():
    f = store.read("funding")
    rows = []
    for sym, g in f.groupby("symbol"):
        r = g["funding_rate"].abs().sort_values(ascending=False)
        tot = r.sum()
        rows.append({
            "symbol": sym,
            "top_1pct": r.head(max(1, len(r)//100)).sum() / tot,
            "top_5pct": r.head(max(1, len(r)//20)).sum() / tot,
            "top_10pct": r.head(max(1, len(r)//10)).sum() / tot,
        })
    return pd.DataFrame(rows).sort_values("top_1pct", ascending=False)


def persistence():
    f = store.read("funding")
    rows = []
    for sym, g in f.groupby("symbol"):
        r = g.sort_values("ts")["funding_rate"]
        rows.append({
            "symbol": sym,
            "ac_1": r.autocorr(1),
            "ac_3": r.autocorr(3),
            "ac_21": r.autocorr(21),
            "ac_90": r.autocorr(90),
        })
    return pd.DataFrame(rows)


def cost_hurdle():
    f = store.read("funding")
    mean_ann = _ann(f["funding_rate"].mean())
    print("\n" + "=" * 68)
    print("THE COST HURDLE -- the only number that matters")
    print("=" * 68)
    print(f"  gross funding (universe mean, annualised) : {mean_ann:+7.2%}")
    print()
    print("  costs for a 2-leg delta-neutral position:")
    for label, bps, rebals in [
        ("taker/taker, monthly rebalance", 5.0, 12),
        ("taker/taker, weekly rebalance", 5.0, 52),
        ("maker/maker, monthly rebalance", 2.0, 12),
    ]:
        cost = (bps / 1e4) * 2 * 2 * rebals
        print(f"    {label:34s} : {-cost:7.2%}   -> net {mean_ann - cost:+7.2%}")
    print()
    print("  NOTE: excludes slippage, borrow, and the spot leg's own drift.")
    print("=" * 68)


def run():
    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", lambda x: f"{x:,.4f}")
    print("=" * 68)
    print("FUNDING ECONOMICS -- descriptive, NOT a backtest")
    print("Funding is a CASH FLOW, not a return. Nothing here is P&L.")
    print("=" * 68)
    print("\n--- 1. PER SYMBOL (annualised) ---")
    print(per_symbol().to_string(index=False))
    print("\n--- 2. BY YEAR (annualised mean funding) ---")
    print(by_year().to_string())
    print("\n--- 3. CONCENTRATION (share of total |funding| in the tail) ---")
    print("If top 1% of settlements carry most of it, it is NOT a steady premium.")
    print(concentration().to_string(index=False))
    print("\n--- 4. PERSISTENCE (autocorrelation of funding) ---")
    print("Near-zero => today's funding does not predict tomorrow's => no edge.")
    print(persistence().to_string(index=False))
    cost_hurdle()


if __name__ == "__main__":
    run()
