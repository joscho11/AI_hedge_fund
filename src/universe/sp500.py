"""S&P 500 constituents (CURRENT membership) + GICS sector.

KNOWN BIAS (logged, not solved): the free stack cannot reconstruct historical index membership, so
we use *today's* constituents at every historical rebalance date. Today's members are
disproportionately past winners and dropped/delisted names are absent — a real lookahead/
survivorship bias. See DECISIONS.md D5/D6 and LEAKAGE_AUDIT.md. Fixed later with Sharadar's
historical constituent lists.
"""
from __future__ import annotations

import io

import pandas as pd
import requests

from ..data.cache import ParquetCache

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _to_yahoo_symbol(sym: str) -> str:
    # Wikipedia uses class-share dots (BRK.B); yfinance uses dashes (BRK-B).
    return sym.strip().upper().replace(".", "-")


def get_sp500_table(cache: ParquetCache | None = None, refresh: bool = False) -> pd.DataFrame:
    """Return DataFrame[ticker, security, sector, sub_industry]. `ticker` is yfinance-normalized.

    Cached; pass refresh=True to re-scrape.
    """
    if cache is not None and not refresh:
        cached = cache.get("universe", "sp500_current")
        if cached is not None:
            return cached

    resp = requests.get(WIKI_URL, headers={"User-Agent": _BROWSER_UA}, timeout=60)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    raw = tables[0]  # first table is the constituents list
    df = pd.DataFrame(
        {
            "ticker": raw["Symbol"].map(_to_yahoo_symbol),
            "security": raw["Security"],
            "sector": raw["GICS Sector"],
            "sub_industry": raw["GICS Sub-Industry"],
        }
    ).drop_duplicates(subset="ticker").reset_index(drop=True)

    if cache is not None:
        cache.put("universe", "sp500_current", df)
    return df
