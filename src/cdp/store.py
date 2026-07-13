"""
The Parquet store. This is the ONLY thing your strategy code should read.

Layout:
    /opt/marketdata/parquet/<dataset>/symbol=<SYM>/<SYM>-<period>.parquet

Why partition by symbol: every query you will ever write filters by symbol.
Hive partitioning lets pyarrow skip files entirely instead of reading them.

Why one file per period: makes incremental appends trivial and lets you
re-download a single bad month without rebuilding the world.

Invariants enforced on write:
  - tz-aware UTC timestamps
  - no duplicate (ts, symbol)
  - sorted by ts
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from . import config as cfg

log = logging.getLogger(__name__)


def _validate(df: pd.DataFrame, dataset: str) -> pd.DataFrame:
    if df.empty:
        return df
    if "ts" not in df.columns or "symbol" not in df.columns:
        raise ValueError(f"{dataset}: requires 'ts' and 'symbol' columns")
    if df["ts"].dt.tz is None:
        raise ValueError(f"{dataset}: ts must be tz-aware UTC")

    n0 = len(df)
    df = df.drop_duplicates(subset=["ts", "symbol"], keep="last")
    if len(df) != n0:
        log.warning("%s: dropped %d duplicate rows", dataset, n0 - len(df))

    return df.sort_values("ts").reset_index(drop=True)


def write(df: pd.DataFrame, dataset: str, symbol: str, period: str) -> Path | None:
    """Write one (dataset, symbol, period) partition. Overwrites in place."""
    df = _validate(df, dataset)
    if df.empty:
        return None

    out_dir = cfg.PARQUET_DIR / dataset / f"symbol={symbol}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{symbol}-{period}.parquet"

    # symbol is encoded in the partition path; don't duplicate it in the file
    table = pa.Table.from_pandas(df.drop(columns=["symbol"]), preserve_index=False)
    pq.write_table(table, path, compression="zstd")
    return path


def read(
    dataset: str,
    symbols: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """
    Read from the store. This is your main query entrypoint.

        df = store.read("perp_klines", ["BTCUSDT"], start="2023-01-01")
    """
    root = cfg.PARQUET_DIR / dataset
    if not root.exists():
        raise FileNotFoundError(f"no data for dataset '{dataset}' at {root}")

    dataset_obj = ds.dataset(root, format="parquet", partitioning="hive")

    filt = None
    if symbols:
        filt = ds.field("symbol").isin(symbols)
    if start:
        c = ds.field("ts") >= pd.Timestamp(start, tz="UTC")
        filt = c if filt is None else filt & c
    if end:
        c = ds.field("ts") <= pd.Timestamp(end, tz="UTC")
        filt = c if filt is None else filt & c

    df = dataset_obj.to_table(filter=filt).to_pandas()
    if df.empty:
        return df
    return df.sort_values(["ts", "symbol"]).reset_index(drop=True)


def summary() -> pd.DataFrame:
    """What's actually in the store. Run this after every ingest."""
    rows = []
    if not cfg.PARQUET_DIR.exists():
        return pd.DataFrame()

    for dset in sorted(p for p in cfg.PARQUET_DIR.iterdir() if p.is_dir()):
        for sym_dir in sorted(dset.glob("symbol=*")):
            files = list(sym_dir.glob("*.parquet"))
            if not files:
                continue
            try:
                d = ds.dataset(sym_dir, format="parquet").to_table(
                    columns=["ts"]
                ).to_pandas()
            except Exception as e:  # noqa: BLE001
                log.warning("unreadable: %s (%s)", sym_dir, e)
                continue
            rows.append({
                "dataset": dset.name,
                "symbol": sym_dir.name.split("=", 1)[1],
                "files": len(files),
                "rows": len(d),
                "start": d["ts"].min(),
                "end": d["ts"].max(),
                "mb": round(sum(f.stat().st_size for f in files) / 1e6, 1),
            })
    return pd.DataFrame(rows)
