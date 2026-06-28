"""Phase 0 validation spot-check (live APIs).

Pulls a handful of tickers, reconciles EDGAR fundamentals against known filings with their filed
dates, and probes the survivorship gap with delisted names. Prints a report and emits
artifacts the audit note references. Run from repo root:

    .venv/Scripts/python.exe scripts/phase0_spotcheck.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.cache import ParquetCache
from src.data.interfaces import FundamentalsProvider
from src.data.providers.edgar_fundamentals import EdgarFundamentalsProvider
from src.data.providers.fred_macro import FredMacroProvider
from src.data.providers.yfinance_prices import YFinancePriceProvider
from src.data.types import (
    COL_CLOSE_ADJ,
    COL_CLOSE_RAW,
    COL_DATE,
    COL_FILED,
    COL_PERIOD_END,
    COL_TAG,
    COL_VALUE,
)
from src.utils.config import load_config

pd.set_option("display.width", 140)
pd.set_option("display.max_columns", 20)

REV_TAGS = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"]
LIVE = {"AAPL", "RKLB"}
DELISTED = ["SIVB", "BBBY"]  # both were public, then delisted (SVB bankrupcy 2023, BBBY 2023)


def hr(title):
    print("\n" + "=" * 88 + f"\n{title}\n" + "=" * 88)


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    prices = YFinancePriceProvider(cache)
    edgar = EdgarFundamentalsProvider(cache, cfg.paths.edgar_user_agent)
    fred = FredMacroProvider(cache, realtime_only=cfg.availability.macro_realtime_only)

    hr("1. PRICES — raw vs adjusted (AAPL, RKLB)")
    px = prices.get_prices(sorted(LIVE), "2023-01-01", "2023-06-01")
    for t in sorted(LIVE):
        sub = px[px["ticker"] == t]
        print(f"\n{t}: {len(sub)} rows, {sub[COL_DATE].min().date()}..{sub[COL_DATE].max().date()}")
        print(sub[[COL_DATE, COL_CLOSE_RAW, COL_CLOSE_ADJ]].head(3).to_string(index=False))
        # AAPL paid dividends in this window, so raw != adj historically.
        diff = (sub[COL_CLOSE_RAW] - sub[COL_CLOSE_ADJ]).abs().max()
        print(f"  max|raw-adj| = {diff:.4f}  (nonzero => dividend/split adjustment present)")

    hr("2. FUNDAMENTALS — EDGAR filed dates & reconciliation (AAPL)")
    facts = edgar.get_facts(["AAPL"], REV_TAGS, "2018-01-01", "2024-12-31")
    annual = facts[facts["form"] == "10-K"].sort_values(COL_FILED)
    print("AAPL annual revenue facts (concept, period_end, filed, value $B):")
    show = annual[[COL_TAG, COL_PERIOD_END, COL_FILED, COL_VALUE]].copy()
    show[COL_VALUE] = (show[COL_VALUE] / 1e9).round(2)
    print(show.tail(8).to_string(index=False))
    # Lag check: every filed date strictly after its period end (the whole point of PIT lag).
    lag_ok = (annual[COL_FILED] > annual[COL_PERIOD_END]).all()
    med_lag = (annual[COL_FILED] - annual[COL_PERIOD_END]).dt.days.median()
    print(f"\n  All 10-K filings dated AFTER their fiscal period end: {lag_ok}")
    print(f"  Median filing lag (period_end -> filed): {med_lag:.0f} days")

    hr("3. AS-OF SELECTOR on live data — no future leakage (AAPL revenue)")
    ref = edgar.company_ref(["AAPL"])
    print(f"  AAPL CIK={ref['AAPL'].cik}  SIC={ref['AAPL'].sic} ({ref['AAPL'].sic_description})")
    for asof in ["2022-10-01", "2022-12-01", "2023-12-01"]:
        got = FundamentalsProvider.as_of(facts, pd.Timestamp(asof), lag_trading_days=1)
        latest = facts[facts[COL_FILED] <= pd.Timestamp(asof)]
        maxfiled = latest[COL_FILED].max()
        vals = {k: round(v / 1e9, 2) for k, v in got.items()}
        print(f"  as_of {asof}: latest visible filing={maxfiled.date() if pd.notna(maxfiled) else None}, revenue($B)={vals}")

    hr("4. SURVIVORSHIP GAP — delisted tickers via yfinance")
    for t in DELISTED:
        sub = prices.get_prices([t], "2015-01-01", "2024-12-31")
        n = len(sub)
        rng = f"{sub[COL_DATE].min().date()}..{sub[COL_DATE].max().date()}" if n else "—"
        print(f"  {t}: {n} price rows ({rng})  <- gap if 0/sparse vs its true trading life")

    hr("5. MACRO — FRED real-time series + revised-series exclusion")
    macro = fred.get_series(["DGS10", "VIXCLS", "GDP"], "2023-01-01", "2023-06-01")
    kept = sorted(macro["series_id"].unique())
    print(f"  series kept (realtime_only=True): {kept}  (GDP excluded as revised)")
    print(macro.groupby("series_id")["value"].agg(["count", "first", "last"]).to_string())

    print("\nDONE. See LEAKAGE_AUDIT.md for the written findings.")


if __name__ == "__main__":
    main()
