"""SharadarProvider — point-in-time fundamentals behind the existing FundamentalsProvider interface.

Why we bought this: SF1 carries `datekey`, the date each figure became publicly available, so we can
key fundamentals on actual availability. The single most important leakage rule lives here:

  * Use ONLY the as-reported dimensions (ARQ / ART / ARY). The MR* dimensions (MRQ/MRT/MRY)
    retroactively backfill restatements into past periods and WOULD leak — we never use them.
  * A feature at rebalance `t` may use only rows with `datekey <= t`. The inherited
    FundamentalsProvider.as_of (max filed<=t per tag, with `filed` = `datekey`) enforces this.

The provider reads bulk tables cached locally as parquet (see scripts/ingest_sharadar.py). It does not
hit the network at query time. Feature families talk only to this interface, so they never know
whether the source is EDGAR or Sharadar.
"""
from __future__ import annotations

import pandas as pd

from ..cache import ParquetCache
from ..interfaces import FundamentalsProvider
from ..types import (
    COL_CIK,
    COL_FILED,
    COL_FORM,
    COL_FP,
    COL_FY,
    COL_PERIOD_END,
    COL_TAG,
    COL_TICKER,
    COL_UNIT,
    COL_VALUE,
    FACT_COLUMNS,
    CompanyRef,
)

CACHE_NS = "sharadar"
AR_DIMENSIONS = {"ARQ", "ART", "ARY"}  # as-reported; MR* are restatement-backfilled => banned


class SharadarProvider(FundamentalsProvider):
    def __init__(self, cache: ParquetCache):
        self.cache = cache

    def _load_table(self, name: str) -> pd.DataFrame:
        df = self.cache.get(CACHE_NS, name)
        if df is None:
            raise FileNotFoundError(
                f"Sharadar table {name!r} not cached. Run scripts/ingest_sharadar.py first."
            )
        return df

    def get_facts(
        self, tickers: list[str], tags: list[str], start: str, end: str,
        dimension: str = "ART",
    ) -> pd.DataFrame:
        """Long fact frame (FACT_COLUMNS) for one as-reported dimension, `filed` = SF1 `datekey`.

        Refuses MR* dimensions outright — using them would backfill restatements and leak. Returns
        ALL datekey vintages in [start, end] so as_of can pick the value known at a given date.
        """
        if dimension not in AR_DIMENSIONS:
            raise ValueError(
                f"dimension {dimension!r} is not as-reported; only {sorted(AR_DIMENSIONS)} are "
                "allowed (MR* dimensions backfill restatements and would leak)."
            )
        sf1 = self._load_table("SF1")
        sf1 = sf1[(sf1["ticker"].isin(tickers)) & (sf1["dimension"] == dimension)].copy()
        sf1[COL_FILED] = pd.to_datetime(sf1["datekey"])
        sf1 = sf1[(sf1[COL_FILED] >= pd.Timestamp(start)) & (sf1[COL_FILED] <= pd.Timestamp(end))]
        present = [t for t in tags if t in sf1.columns]
        if sf1.empty or not present:
            return pd.DataFrame(columns=FACT_COLUMNS)

        id_cols = ["ticker", COL_FILED, "calendardate", "dimension"]
        long = sf1[id_cols + present].melt(
            id_vars=id_cols, value_vars=present, var_name=COL_TAG, value_name=COL_VALUE
        ).dropna(subset=[COL_VALUE])
        out = pd.DataFrame({
            COL_TICKER: long["ticker"],
            COL_CIK: 0,                                   # Sharadar is ticker-keyed
            COL_TAG: long[COL_TAG],
            COL_VALUE: pd.to_numeric(long[COL_VALUE], errors="coerce"),
            COL_PERIOD_END: pd.to_datetime(long["calendardate"]),
            COL_FILED: long[COL_FILED],                   # datekey = availability date (PIT)
            COL_FORM: long["dimension"],
            COL_FY: pd.NA,
            COL_FP: pd.NA,
            COL_UNIT: "native",
        }).dropna(subset=[COL_VALUE])
        return out[FACT_COLUMNS].sort_values([COL_TICKER, COL_TAG, COL_FILED])

    def company_ref(self, tickers: list[str]) -> dict[str, CompanyRef]:
        """Reference data (sector / SIC) from the TICKERS table. Sharadar's classification is current
        (not historically versioned); sector rarely changes, but this is a documented caveat for the
        sector-relative valuation features."""
        tk = self._load_table("TICKERS")
        tk = tk[tk["ticker"].isin(tickers)]
        # Prefer equity rows; keep the most recent per ticker if duplicated.
        if "table" in tk.columns:
            tk = tk[tk["table"] == "SF1"] if (tk["table"] == "SF1").any() else tk
        tk = tk.drop_duplicates(subset="ticker", keep="last")
        out: dict[str, CompanyRef] = {}
        for _, r in tk.iterrows():
            out[r["ticker"]] = CompanyRef(
                ticker=r["ticker"], cik=0, title=r.get("name", "") or "",
                sic=str(r.get("siccode")) if pd.notna(r.get("siccode")) else None,
                sic_description=r.get("sector") or r.get("sicsector"),
            )
        return out

    def sectors(self, tickers: list[str]) -> dict[str, str]:
        """ticker -> sector string (convenience for sector-relative features)."""
        return {t: (ref.sic_description or "Unknown") for t, ref in self.company_ref(tickers).items()}
