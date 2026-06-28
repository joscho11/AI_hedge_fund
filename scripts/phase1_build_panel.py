"""Phase 1: build the labeled panel for the S&P 500 (current membership) and report diagnostics.

    .venv/Scripts/python.exe scripts/phase1_build_panel.py [--max-tickers N] [--start YYYY-MM-DD]

Saves the panel to <cache>/panel/panel_<n>tickers.parquet and prints a summary + leak-free sanity
checks. Per-ticker price pulls are cached, so re-runs and scale-ups are resumable.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.cache import ParquetCache
from src.data.providers.yfinance_prices import YFinancePriceProvider
from src.labels.forward_returns import (
    COL_FWD_EXCESS_MEDIAN,
    COL_FWD_EXCESS_SECTOR,
    COL_FWD_RAW,
    COL_SECTOR,
)
from src.labels.panel import build_panel
from src.universe.sp500 import get_sp500_table
from src.utils.calendars import month_end_rebalance_dates
from src.utils.config import load_config

pd.set_option("display.width", 140)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-tickers", type=int, default=None, help="cap universe size (sampling)")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    cfg = load_config()
    start = args.start or cfg.dates.start
    end = args.end or cfg.dates.end
    cache = ParquetCache(cfg.cache_path)

    table = get_sp500_table(cache)
    if args.max_tickers:
        # Stratify by sector so the sample keeps cross-sectional/sector structure.
        per = max(1, args.max_tickers // table["sector"].nunique())
        table = (
            table.groupby("sector", group_keys=False)
            .head(per)
            .head(args.max_tickers)
            .reset_index(drop=True)
        )
    tickers = table["ticker"].tolist()
    sector_map = dict(zip(table["ticker"], table["sector"]))
    print(f"Universe: {len(tickers)} tickers (current S&P 500), {table['sector'].nunique()} sectors")

    prices = YFinancePriceProvider(cache).get_prices(tickers, start, end)
    got = prices["ticker"].nunique()
    print(f"Prices: {len(prices):,} rows for {got}/{len(tickers)} tickers, "
          f"{prices['date'].min().date()}..{prices['date'].max().date()}")

    reb = month_end_rebalance_dates(start, end, cfg.calendar.exchange)
    panel = build_panel(
        prices, reb, sector_map,
        horizon_days=cfg.label.horizon_days,
        min_price=cfg.universe.min_price,
        min_dollar_volume=cfg.universe.min_dollar_volume,
        exchange=cfg.calendar.exchange,
    )

    out_path = cache.put("panel", f"panel_{got}tickers", panel)
    print(f"\nPANEL: {len(panel):,} labeled rows  ->  {out_path}")
    print(f"  rebalance dates: {panel['date'].nunique()} "
          f"({panel['date'].min().date()}..{panel['date'].max().date()})")
    print(f"  median names/date: {panel.groupby('date')['ticker'].size().median():.0f}")
    sec_cov = panel[COL_SECTOR].notna().mean()
    print(f"  sector coverage: {sec_cov:.1%}  (excess_sector defined where sector known)")

    print("\nTarget distributions:")
    print(panel[[COL_FWD_RAW, COL_FWD_EXCESS_MEDIAN, COL_FWD_EXCESS_SECTOR]].describe().round(4).to_string())

    # --- Leak-free / correctness sanity checks ---
    print("\nSanity checks:")
    per_date_med = panel.groupby("date")[COL_FWD_EXCESS_MEDIAN].median().abs().max()
    print(f"  max |per-date median of excess_median|: {per_date_med:.2e}  (should be ~0 by construction)")
    # No label should be exactly forward-fillable past data end: spot the last rebalance date that
    # could carry a realized H-day label given `end`.
    last_label_date = panel["date"].max()
    print(f"  last labeled rebalance date: {last_label_date.date()} "
          f"(later dates correctly have no realized {cfg.label.horizon_days}d label)")
    print("\nHead:")
    print(panel.head(6).to_string(index=False))


if __name__ == "__main__":
    main()
