"""Valuation feature family — the first FUNDAMENTAL instance of the FeatureFamily template, built
against SharadarProvider (point-in-time SF1). The base owns normalization / panel-join / report;
this module implements only `compute_raw`.

As-of construction (the leakage-critical part):
  * NUMERATOR = price at t (panel `close_raw`, as observed at t).
  * DENOMINATOR = the latest fundamental with `datekey <= t` (provider as-of, AR* dimensions only —
    flow items eps/sps/ebitda from ART (TTM), stock items bvps/sharesbas/debt/cashneq from ARQ).
  A restated value (a newer datekey) never changes an earlier-t feature — see tests.

Missing-data rules (no silent fills; each surfaced in the report):
  * Negative/zero earnings -> earnings_yield undefined (NaN), NOT zero. Same for negative sales,
    negative book value, and non-positive EBITDA (EV/EBITDA undefined).
For each base metric we emit three views: level, sector-relative (minus the as-of sector median),
and own-history (z vs the stock's own trailing 5y of that metric).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.types import (
    COL_CLOSE_RAW,
    COL_DATE,
    COL_FILED,
    COL_TAG,
    COL_TICKER,
    COL_VALUE,
)
from .base import FeatureFamily, FeatureSpec

ART_TAGS = ["eps", "sps", "ebitda"]                       # trailing-twelve-month flows
ARQ_TAGS = ["bvps", "sharesbas", "debt", "cashneq"]       # latest-quarter stocks
BASE_METRICS = ["earnings_yield", "sales_yield", "ev_ebitda", "book_to_price"]
HIST_WIN, HIST_MIN = 60, 24      # own-history: 5y of monthly obs, need >=2y
FACTS_LOOKBACK_YEARS = 6         # pull filings this far before the first rebalance date

_AS_OF = {
    "earnings_yield": "ART eps (datekey<=t) / close_raw(t); neg/zero earnings -> NaN",
    "sales_yield": "ART sps (datekey<=t) / close_raw(t); neg/zero sales -> NaN",
    "ev_ebitda": "[close_raw(t)*ARQ sharesbas + ARQ debt - ARQ cashneq] / ART ebitda (all datekey<=t); EBITDA<=0 -> NaN (lower=cheaper)",
    "book_to_price": "ARQ bvps (datekey<=t) / close_raw(t); neg/zero book -> NaN",
}


def _spec(metric: str, view: str) -> FeatureSpec:
    base_desc = {
        "earnings_yield": "earnings yield (inverse P/E)",
        "sales_yield": "sales yield (inverse P/S)",
        "ev_ebitda": "EV/EBITDA (level; lower = cheaper)",
        "book_to_price": "book-to-price (inverse P/B)",
    }[metric]
    if view == "level":
        return FeatureSpec(metric, base_desc, _AS_OF[metric], "NaN if undefined (see as-of); never filled")
    if view == "sectrel":
        return FeatureSpec(f"{metric}_sectrel", f"{base_desc}, minus as-of sector median",
                           _AS_OF[metric] + "; sector from TICKERS (current classification)",
                           "NaN if level or sector missing; never filled")
    return FeatureSpec(f"{metric}_hist", f"{base_desc}, z vs own trailing 5y",
                       _AS_OF[metric] + f"; z over trailing {HIST_WIN}m (min {HIST_MIN}m) of own metric",
                       f"NaN until {HIST_MIN} prior monthly obs; never filled")


class ValuationFamily(FeatureFamily):
    name = "valuation"
    specs = [_spec(m, v) for m in BASE_METRICS for v in ("level", "sectrel", "hist")]

    def compute_raw(self, panel, rebalance_dates, *, providers, exchange="XNYS") -> pd.DataFrame:
        prov = providers["fundamentals"]
        tickers = sorted(panel[COL_TICKER].unique())
        dates = pd.DatetimeIndex(sorted(pd.to_datetime(panel[COL_DATE].unique())))
        facts_start = (dates.min() - pd.DateOffset(years=FACTS_LOOKBACK_YEARS)).strftime("%Y-%m-%d")
        facts_end = dates.max().strftime("%Y-%m-%d")

        art = prov.get_facts(tickers, ART_TAGS, facts_start, facts_end, dimension="ART")
        arq = prov.get_facts(tickers, ARQ_TAGS, facts_start, facts_end, dimension="ARQ")
        facts = pd.concat([art, arq], ignore_index=True)
        sector_map = prov.sectors(tickers)

        # As-of value per tag at each rebalance date: pivot on filing date, carry forward, sample.
        asof_rows = []
        for tk, g in facts.groupby(COL_TICKER):
            wide = g.pivot_table(index=COL_FILED, columns=COL_TAG, values=COL_VALUE, aggfunc="last")
            wide = wide.sort_index()
            full = wide.reindex(wide.index.union(dates)).ffill().reindex(dates)
            full[COL_TICKER] = tk
            full[COL_DATE] = dates
            asof_rows.append(full.reset_index(drop=True))
        if not asof_rows:
            return pd.DataFrame(columns=[COL_DATE, COL_TICKER, *self.feature_names])
        asof = pd.concat(asof_rows, ignore_index=True)

        df = asof.merge(panel[[COL_DATE, COL_TICKER, COL_CLOSE_RAW]],
                        on=[COL_DATE, COL_TICKER], how="inner")
        px = df[COL_CLOSE_RAW]
        for c in [*ART_TAGS, *ARQ_TAGS]:
            df[c] = df.get(c, np.nan)

        # ---- levels (negative fundamentals -> undefined, not zero) ----
        df["earnings_yield"] = np.where(df["eps"] > 0, df["eps"] / px, np.nan)
        df["sales_yield"] = np.where(df["sps"] > 0, df["sps"] / px, np.nan)
        ev_t = px * df["sharesbas"] + df["debt"] - df["cashneq"]
        df["ev_ebitda"] = np.where((df["ebitda"] > 0) & (df["sharesbas"] > 0), ev_t / df["ebitda"], np.nan)
        df["book_to_price"] = np.where(df["bvps"] > 0, df["bvps"] / px, np.nan)

        # ---- sector-relative (as-of sector median, same date) ----
        df["sector"] = df[COL_TICKER].map(sector_map)
        for m in BASE_METRICS:
            med = df.groupby([COL_DATE, "sector"])[m].transform("median")
            df[f"{m}_sectrel"] = df[m] - med

        # ---- own-history z (trailing window of the stock's own metric; only past+present) ----
        df = df.sort_values([COL_TICKER, COL_DATE])
        for m in BASE_METRICS:
            grp = df.groupby(COL_TICKER)[m]
            mean = grp.transform(lambda s: s.rolling(HIST_WIN, min_periods=HIST_MIN).mean())
            std = grp.transform(lambda s: s.rolling(HIST_WIN, min_periods=HIST_MIN).std())
            z = (df[m] - mean) / std
            df[f"{m}_hist"] = z.replace([np.inf, -np.inf], np.nan)

        return df[[COL_DATE, COL_TICKER, *self.feature_names]].reset_index(drop=True)
