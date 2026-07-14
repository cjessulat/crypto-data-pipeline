"""
Nightly Hyperliquid collector. THE URGENT PIECE.

HL's public API retains only ~5000 candles (~7 months at 1h). Price history
BEFORE that is gone and CANNOT be recovered from the API. Every day this does
not run is a day of HL price data permanently lost.

Funding goes back to 2023 and is safe. PRICES are the perishable part.

Run nightly. In 12 months this gives a native HL dataset good enough to
backtest on. Today it gives nothing -- which is exactly why it must start now.
"""
from __future__ import annotations
import logging
import sys

from . import config as cfg
from . import store
from . import venues as v

log = logging.getLogger("hld")

# HL lists 24 of our 26 (VET and THETA are not on HL)
HL_UNIVERSE = [s for s in cfg.CORE_UNIVERSE
               if s not in ("VETUSDT", "THETAUSDT")]


def run():
    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        stream=sys.stdout)
    cfg.ensure_dirs()

    # --- PRICES: perishable. Top up whatever the API still holds.
    for sym in HL_UNIVERSE:
        try:
            d = v.hl_candles(sym, start="2025-01-01")
            if d.empty:
                continue
            # month-partitioned so nightly appends stay cheap
            for per, g in d.groupby(d.ts.dt.strftime("%Y-%m")):
                store.write(g, "hl_klines", sym, per)
            log.info("hl_klines  %-10s %5d rows  %s -> %s", sym, len(d),
                     d.ts.min().date(), d.ts.max().date())
        except Exception as e:
            log.error("hl_klines  %-10s ERROR %s", sym, str(e)[:40])

    # --- FUNDING: safe (2023+), but keep it current
    for sym in HL_UNIVERSE:
        try:
            d = v.hyperliquid(sym, start="2023-01-01")
            if d.empty:
                continue
            store.write(d[["ts", "symbol", "funding_rate"]]
                        .assign(mark_price=float("nan")),
                        "funding_hl", sym, "all")
        except Exception as e:
            log.error("funding_hl %-10s ERROR %s", sym, str(e)[:40])

    print("\n--- HL store ---")
    s = store.summary()
    print(s[s.dataset.str.contains("hl")].to_string(index=False))


if __name__ == "__main__":
    run()
