"""
Data quality checks. Run this after EVERY ingest, before ANY backtest.

Rationale: a backtest cannot tell you it was fed bad data. It will happily
produce a beautiful Sharpe ratio from a series with a 3-day gap, a stuck
price, or a decimal-shifted outlier. The only defence is to check the data
explicitly, and to be suspicious of it.

    python -m cdp.quality
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import store

EXPECTED_FREQ = {
    "spot_klines": pd.Timedelta("1h"),
    "perp_klines": pd.Timedelta("1h"),
    "funding": pd.Timedelta("8h"),
    "metrics": pd.Timedelta("5min"),
}


def check_dataset(dataset: str) -> pd.DataFrame:
    freq = EXPECTED_FREQ.get(dataset)
    try:
        df = store.read(dataset)
    except FileNotFoundError:
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()

    out = []
    for sym, g in df.groupby("symbol"):
        g = g.sort_values("ts")
        row = {"dataset": dataset, "symbol": sym, "rows": len(g)}

        # --- gaps
        if freq is not None and len(g) > 1:
            deltas = g["ts"].diff().dropna()
            gaps = deltas[deltas > freq * 1.5]
            row["gaps"] = len(gaps)
            row["max_gap_h"] = round(gaps.max().total_seconds()/3600, 1) if len(gaps) else 0.0
            expected = int((g.ts.max() - g.ts.min()) / freq) + 1
            row["completeness"] = round(len(g) / expected, 4) if expected else np.nan
        else:
            row["gaps"] = 0
            row["max_gap_h"] = 0.0
            row["completeness"] = np.nan

        # --- staleness (is the feed alive?)
        age = pd.Timestamp.now(tz="UTC") - g["ts"].max()
        row["stale_h"] = round(age.total_seconds()/3600, 1)

        # --- price sanity
        if "close" in g.columns:
            c = g["close"]
            row["zeros"] = int((c <= 0).sum())
            row["nans"] = int(c.isna().sum())
            ret = np.log(c / c.shift(1)).dropna()
            # A >40% move in ONE HOUR is possible in crypto but rare. Flag,
            # don't drop -- these are sometimes real (and are exactly the bars
            # that dominate a momentum backtest, so you want to eyeball them).
            row["ret_gt_40pct"] = int((ret.abs() > 0.40).sum())
            row["stuck_bars"] = int((c.diff() == 0).sum())
        else:
            row["zeros"] = row["nans"] = row["ret_gt_40pct"] = row["stuck_bars"] = 0

        out.append(row)

    return pd.DataFrame(out)


def run() -> pd.DataFrame:
    frames = [check_dataset(d) for d in EXPECTED_FREQ]
    frames = [f for f in frames if not f.empty]
    if not frames:
        print("store is empty -- run `python -m cdp.ingest --backfill` first")
        return pd.DataFrame()

    rep = pd.concat(frames, ignore_index=True)
    print(rep.to_string(index=False))

    # --- verdict
    print("\n" + "=" * 62)
    problems = []
    bad = rep[rep["completeness"] < 0.98]
    if not bad.empty:
        problems.append(f"{len(bad)} series <98% complete (gaps in history)")
    stale = rep[(rep["dataset"] != "metrics") & (rep["stale_h"] > 48)]
    if not stale.empty:
        problems.append(f"{len(stale)} series >48h stale (feed may be dead)")
    if rep["zeros"].sum() or rep["nans"].sum():
        problems.append("zero or NaN prices present")
    outl = rep["ret_gt_40pct"].sum()
    if outl:
        problems.append(f"{outl} hourly moves >40% -- INSPECT, may be real")

    if problems:
        print("ISSUES:")
        for p in problems:
            print("  -", p)
    else:
        print("all checks passed")
    print("=" * 62)
    return rep


if __name__ == "__main__":
    run()
