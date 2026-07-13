"""
The Parquet store. This is the ONLY thing your strategy code should read.
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

_TS = pa.timestamp("us", tz="UTC")

SCHEMAS: dict[str, pa.Schema] = {
    "spot_klines": pa.schema([
        ("ts", _TS),
        ("open", pa.float64()), ("high", pa.float64()),
        ("low", pa.float64()), ("close", pa.float64()),
        ("volume", pa.float64()), ("quote_volume", pa.float64()),
        ("trades", pa.int64()),
        ("taker_buy_base", pa.float64()), ("taker_buy_quote", pa.float64()),
    ]),
    "funding": pa.schema([
        ("ts", _TS),
        ("funding_rate", pa.float64()),
        ("mark_price", pa.float64()),
    ]),
    "metrics": pa.schema([
        ("ts", _TS),
        ("sum_open_interest", pa.float64()),
        ("sum_open_interest_value", pa.float64()),
        ("count_toptrader_long_short_ratio", pa.float64()),
        ("sum_toptrader_long_short_ratio", pa.float64()),
        ("count_long_short_ratio", pa.float64()),
        ("sum_taker_long_short_vol_ratio", pa.float64()),
    ]),
}
SCHEMAS["perp_klines"] = SCHEMAS["spot_klines"]


def _coerce(df: pd.DataFrame, dataset: str) -> pa.Table:
    schema = SCHEMAS.get(dataset)
    if schema is None:
        return pa.Table.from_pandas(df, preserve_index=False)
    for field in schema:
        if field.name not in df.columns:
            df[field.name] = pd.NA
        elif field.name != "ts":
            df[field.name] = pd.to_numeric(df[field.name], errors="coerce")
    df = df[[f.name for f in schema]]
    return pa.Table.from_pandas(df, schema=schema, preserve_index=False)


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
    df = _validate(df, dataset)
    if df.empty:
        return None
    out_dir = cfg.PARQUET_DIR / dataset / f"symbol={symbol}"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{symbol}-{period}.parquet"
    table = _coerce(df.drop(columns=["symbol"]), dataset)
    pq.write_table(table, path, compression="zstd")
    return path


def read(dataset, symbols=None, start=None, end=None) -> pd.DataFrame:
    root = cfg.PARQUET_DIR / dataset
    if not root.exists():
        raise FileNotFoundError(f"no data for dataset '{dataset}' at {root}")

    schema = SCHEMAS.get(dataset)
    if schema is not None:
        schema = schema.append(pa.field("symbol", pa.string()))

    dataset_obj = ds.dataset(root, format="parquet", partitioning="hive",
                             schema=schema)

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
                    columns=["ts"]).to_pandas()
            except Exception as e:
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
