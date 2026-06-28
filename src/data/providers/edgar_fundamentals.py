"""SEC EDGAR XBRL fundamentals provider — the authoritative, point-in-time source.

Why EDGAR: every fact carries its SEC `filed` date, so we can lag fundamentals to actual
availability instead of fiscal period-end (the classic lookahead trap). Delisted filers' filings
persist in EDGAR, so fundamentals are delisting-inclusive even on the free stack.

Pitfalls handled here:
  * `filed` (filing/accepted date) is the availability date — NOT `end` (period end).
  * Amendments (10-K/A) appear as later vintages for the same period; we KEEP all vintages so the
    as-of selector (FundamentalsProvider.as_of) can pick the value as known at t, not the restated one.
  * ticker->CIK mapping is current-only (company_tickers.json); historical/delisted mapping is the
    survivorship gap on the free stack.
  * XBRL tags drift across taxonomy years; callers should pass tag fallback chains.

SEC requires a descriptive User-Agent and rate-limits to ~10 req/s; we cache aggressively.
"""
from __future__ import annotations

import time

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

_MIN_INTERVAL = 0.12  # seconds between SEC requests (~8 req/s, under the 10 req/s ceiling)


class EdgarFundamentalsProvider(FundamentalsProvider):
    def __init__(self, cache: ParquetCache, user_agent: str):
        self.cache = cache
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self._last_request = 0.0
        self._ticker_map: dict[str, dict] | None = None

    # ---- HTTP with polite rate limiting ----
    def _get_json(self, url: str) -> dict | None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        resp = self.session.get(url, timeout=30)
        self._last_request = time.monotonic()
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    # ---- ticker -> CIK / reference ----
    def _load_ticker_map(self) -> dict[str, dict]:
        if self._ticker_map is not None:
            return self._ticker_map
        data = self._get_json(TICKERS_URL) or {}
        m = {}
        for row in data.values():
            m[row["ticker"].upper()] = {"cik": int(row["cik_str"]), "title": row.get("title", "")}
        self._ticker_map = m
        return m

    def company_ref(self, tickers: list[str]) -> dict[str, CompanyRef]:
        tmap = self._load_ticker_map()
        out: dict[str, CompanyRef] = {}
        for t in tickers:
            info = tmap.get(t.upper())
            if info is None:
                continue
            cik = info["cik"]
            sub = self._get_json(SUBMISSIONS_URL.format(cik=cik)) or {}
            out[t] = CompanyRef(
                ticker=t,
                cik=cik,
                title=info.get("title", ""),
                sic=str(sub.get("sic")) if sub.get("sic") else None,
                sic_description=sub.get("sicDescription"),
            )
        return out

    # ---- fundamentals ----
    def _facts_for_cik(self, ticker: str, cik: int) -> pd.DataFrame:
        """All us-gaap facts for a CIK, long format, all vintages. Cached per CIK."""
        key = f"{cik}"
        cached = self.cache.get("edgar_facts", key)
        if cached is not None:
            return cached
        data = self._get_json(FACTS_URL.format(cik=cik))
        rows = []
        if data:
            usgaap = data.get("facts", {}).get("us-gaap", {})
            for tag, tagdata in usgaap.items():
                for unit, entries in tagdata.get("units", {}).items():
                    for e in entries:
                        if e.get("filed") is None or e.get("val") is None:
                            continue
                        rows.append(
                            {
                                COL_TICKER: ticker,
                                COL_CIK: cik,
                                COL_TAG: tag,
                                COL_VALUE: float(e["val"]),
                                COL_PERIOD_END: pd.Timestamp(e.get("end")) if e.get("end") else pd.NaT,
                                COL_FILED: pd.Timestamp(e["filed"]),
                                COL_FORM: e.get("form"),
                                COL_FY: e.get("fy"),
                                COL_FP: e.get("fp"),
                                COL_UNIT: unit,
                            }
                        )
        df = pd.DataFrame(rows, columns=FACT_COLUMNS)
        self.cache.put("edgar_facts", key, df)
        return df

    def get_facts(
        self, tickers: list[str], tags: list[str], start: str, end: str
    ) -> pd.DataFrame:
        tmap = self._load_ticker_map()
        tagset = set(tags)
        frames = []
        for t in tickers:
            info = tmap.get(t.upper())
            if info is None:
                continue
            df = self._facts_for_cik(t, info["cik"])
            if df.empty:
                continue
            df = df[df[COL_TAG].isin(tagset)]
            # Window on the AVAILABILITY date (filed), not the period end.
            df = df[(df[COL_FILED] >= pd.Timestamp(start)) & (df[COL_FILED] <= pd.Timestamp(end))]
            frames.append(df)
        if not frames:
            return pd.DataFrame(columns=FACT_COLUMNS)
        return pd.concat(frames, ignore_index=True).sort_values([COL_TICKER, COL_TAG, COL_FILED])
