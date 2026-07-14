"""
Backfill Hyperliquid AND Bybit funding for the full universe.

WHY
    Binance funding is being arbitraged away (+33%/yr in 2020 -> +5%/yr 2025).
    Nine attempts to replace it failed: funding is a PAYMENT, not a pattern.
    So get more of it from elsewhere.

    BTC, same 2.5y window:  Hyperliquid +14.51%/yr   Bybit +7.08%/yr
    HL pays 2x -- plausibly newer, retail-heavier, fewer arbitrageurs.

THE TRAP -- HOURLY SETTLEMENT
    HL settles funding EVERY HOUR. Binance/Bybit every 8h. 24 settlements/day
    vs 3. Higher frequency may SMOOTH rates -> LOWER cross-sectional dispersion.

    HIGH AVERAGE FUNDING != BETTER STRATEGY. Our edge is DISPERSION, not level.
    A venue can pay more on average and still be worse to trade.
"""
from __future__ import annotations
import logging
import sys

from . import config as cfg
from . import store
from . import venues as v

log = logging.getLogger("bf")


def backfill(venue, dataset, start):
    fn = v.FETCH[venue]
    ok = miss = 0
    for sym in cfg.CORE_UNIVERSE:
        try:
            d = fn(sym, start=start)
            if d.empty:
                log.info("%-10s -- not listed", sym)
                miss += 1
                continue
            a = v.annualise(d)
            store.write(
                a[["ts", "symbol", "funding_rate"]].assign(mark_price=float("nan")),
                dataset, sym, "all")
            log.info("%-10s %6d rows  %s -> %s   ann %+.2f%%",
                     sym, len(d), d.ts.min().date(), d.ts.max().date(),
                     a.funding_ann.mean() * 100)
            ok += 1
        except Exception as e:
            log.error("%-10s ERROR %s", sym, str(e)[:50])
            miss += 1
    return ok, miss


def run():
    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        stream=sys.stdout)
    cfg.ensure_dirs()

    print("=" * 72)
    print("HYPERLIQUID  (hourly settlement -- 24x/day)")
    print("=" * 72)
    ok1, miss1 = backfill("hyperliquid", "funding_hl", "2023-01-01")

    print("\n" + "=" * 72)
    print("BYBIT  (8h settlement -- the control)")
    print("=" * 72)
    ok2, miss2 = backfill("bybit", "funding_bybit", "2023-01-01")

    print("\n" + "=" * 72)
    print(f"  Hyperliquid : {ok1} ok, {miss1} unavailable")
    print(f"  Bybit       : {ok2} ok, {miss2} unavailable")
    print("=" * 72)


if __name__ == "__main__":
    run()
