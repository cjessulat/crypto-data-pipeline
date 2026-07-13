"""
One-off repair: rewrite existing parquet files against the pinned schema.
Reads each file individually, casts it, writes it back. No re-download.
Safe to re-run.

    python -m cdp.repair
"""
from __future__ import annotations

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from . import config as cfg
from .store import SCHEMAS


def run() -> None:
    total = fixed = 0

    for dataset, schema in SCHEMAS.items():
        root = cfg.PARQUET_DIR / dataset
        if not root.exists():
            continue

        for path in sorted(root.rglob("*.parquet")):
            total += 1
            existing = ds.dataset(path, format="parquet").schema
            if existing.equals(schema):
                continue

            table = pq.read_table(path)
            arrays = []
            for field in schema:
                if field.name in table.column_names:
                    arrays.append(table.column(field.name).cast(field.type))
                else:
                    arrays.append(pa.nulls(len(table), field.type))

            out = pa.Table.from_arrays(arrays, schema=schema)
            tmp = path.with_suffix(".parquet.tmp")
            pq.write_table(out, tmp, compression="zstd")
            tmp.replace(path)
            fixed += 1

        print(f"{dataset:14s} scanned")

    print(f"\n{fixed} of {total} files rewritten to pinned schema")
    if fixed == 0:
        print("(already clean)")


if __name__ == "__main__":
    run()
