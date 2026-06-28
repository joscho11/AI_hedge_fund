"""Canonical data shapes returned by providers.

Design rule that makes leakage structurally hard: every fundamental and macro record carries its
own *availability* date. Modeling code never asks "what was revenue for Q2-2021"; it asks
"what was the latest value KNOWN AS OF date t" via FundamentalsProvider.as_of.
"""
from __future__ import annotations

from dataclasses import dataclass

# ---- Column-name constants (avoid stringly-typed bugs across modules) ----

# Price frame (long, one row per ticker-date)
COL_TICKER = "ticker"
COL_DATE = "date"
COL_OPEN_RAW = "open_raw"
COL_HIGH_RAW = "high_raw"
COL_LOW_RAW = "low_raw"
COL_CLOSE_RAW = "close_raw"      # AS-OBSERVED close; use for price-level features at t
COL_CLOSE_ADJ = "close_adj"      # split+dividend adjusted; use for RETURN computation only
COL_VOLUME = "volume"

PRICE_COLUMNS = [
    COL_TICKER, COL_DATE,
    COL_OPEN_RAW, COL_HIGH_RAW, COL_LOW_RAW, COL_CLOSE_RAW, COL_CLOSE_ADJ, COL_VOLUME,
]

# Corporate-action event tables
COL_SPLIT_RATIO = "split_ratio"      # e.g. 4.0 for a 4:1 split
COL_DIVIDEND = "dividend"            # cash dividend per share (raw)

# Fundamental facts (long, one row per ticker-tag-period-vintage)
COL_CIK = "cik"
COL_TAG = "tag"                  # XBRL us-gaap concept, e.g. "Revenues"
COL_VALUE = "value"
COL_PERIOD_END = "period_end"    # fiscal period end (NOT an availability date)
COL_FILED = "filed"              # SEC filing/accepted date — THE availability date
COL_FORM = "form"                # 10-K, 10-Q, 10-K/A, ...
COL_FY = "fy"
COL_FP = "fp"
COL_UNIT = "unit"

FACT_COLUMNS = [
    COL_TICKER, COL_CIK, COL_TAG, COL_VALUE,
    COL_PERIOD_END, COL_FILED, COL_FORM, COL_FY, COL_FP, COL_UNIT,
]

# Macro series (long)
COL_SERIES = "series_id"
COL_VALUE_MACRO = "value"
COL_REALTIME = "is_realtime"     # False => series is revised; needs ALFRED vintages to be PIT


@dataclass(frozen=True)
class CompanyRef:
    """Static-ish reference data for a filer."""
    ticker: str
    cik: int
    title: str
    sic: str | None = None
    sic_description: str | None = None
