"""FRED macro provider.

Point-in-time note: market-based series (Treasury yields, credit spreads, VIX-like) are
real-time / not revised — safe to use as-of their date. Revised economic series (GDP,
unemployment) are NOT point-in-time without ALFRED vintages; we flag them via `is_realtime` and,
per config `availability.macro_realtime_only`, exclude non-real-time series by default.

Uses the public fredgraph CSV endpoint (no API key required) for the prototype.
"""
from __future__ import annotations

import io

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..cache import ParquetCache
from ..interfaces import MacroProvider
from ..types import COL_DATE, COL_REALTIME, COL_SERIES, COL_VALUE_MACRO

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

# Series we treat as real-time / unrevised (safe to use at their observation date).
REALTIME_SERIES = {
    "DGS3MO", "DGS2", "DGS10", "DGS30",   # Treasury constant-maturity yields
    "T10Y2Y", "T10Y3M",                    # yield-curve spreads
    "BAMLH0A0HYM2", "BAMLC0A0CM",          # ICE BofA credit spreads
    "VIXCLS",                              # CBOE VIX
    "DFF",                                 # effective fed funds rate
}


class FredMacroProvider(MacroProvider):
    def __init__(self, cache: ParquetCache, realtime_only: bool = True):
        self.cache = cache
        self.realtime_only = realtime_only
        self.session = requests.Session()
        # fred.stlouisfed.org filters generic/non-browser User-Agents (request hangs -> read
        # timeout). A browser-like UA is required for the public fredgraph CSV endpoint.
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _fetch_one(self, series_id: str, start: str, end: str) -> pd.DataFrame:
        resp = self.session.get(FRED_CSV_URL.format(series_id=series_id), timeout=60)
        resp.raise_for_status()
        raw = pd.read_csv(io.StringIO(resp.text))
        # fredgraph returns columns: observation_date (or DATE), <SERIES_ID>
        date_col = raw.columns[0]
        val_col = raw.columns[1]
        raw[date_col] = pd.to_datetime(raw[date_col]).dt.normalize()
        raw[val_col] = pd.to_numeric(raw[val_col], errors="coerce")
        df = pd.DataFrame(
            {
                COL_SERIES: series_id,
                COL_DATE: raw[date_col],
                COL_VALUE_MACRO: raw[val_col],
                COL_REALTIME: series_id in REALTIME_SERIES,
            }
        ).dropna(subset=[COL_VALUE_MACRO])
        mask = (df[COL_DATE] >= pd.Timestamp(start)) & (df[COL_DATE] <= pd.Timestamp(end))
        return df[mask]

    def get_series(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        frames = []
        for sid in series_ids:
            if self.realtime_only and sid not in REALTIME_SERIES:
                # Skip revised series by default; they need ALFRED vintages to be point-in-time.
                continue
            key = f"{sid}_{start}_{end}"
            cached = self.cache.get("fred", key)
            if cached is None:
                cached = self._fetch_one(sid, start, end)
                self.cache.put("fred", key, cached)
            frames.append(cached)
        cols = [COL_SERIES, COL_DATE, COL_VALUE_MACRO, COL_REALTIME]
        if not frames:
            return pd.DataFrame(columns=cols)
        return pd.concat(frames, ignore_index=True).sort_values([COL_SERIES, COL_DATE])
