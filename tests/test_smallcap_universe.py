"""Small-cap universe: point-in-time membership — a name enters the band only when its as-of-t
market cap and liquidity qualify it, never earlier (synthetic Sharadar, no API)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.cache import ParquetCache
from src.data.providers.sharadar import SharadarProvider
from src.data.types import COL_CLOSE_ADJ, COL_CLOSE_RAW, COL_DATE, COL_TICKER, COL_VOLUME
from src.universe.smallcap import build_smallcap_membership


def _tickers():
    return pd.DataFrame([
        {"table": "SF1", "ticker": "SML", "category": "Domestic Common Stock",
         "permaticker": 1, "isdelisted": "N", "sector": "Tech", "siccode": 1.0, "name": "SML"},
        {"table": "SF1", "ticker": "ETFX", "category": "ETF",
         "permaticker": 2, "isdelisted": "N", "sector": None, "siccode": None, "name": "ETFX"},
    ])


def _sf1_shares(shares=50_000_000):
    # ARQ sharesbas available from 2020-02-15 onward
    rows = [{"ticker": "SML", "dimension": "ARQ", "datekey": "2020-02-15",
             "calendardate": "2019-12-31", "sharesbas": shares}]
    return pd.DataFrame(rows)


def _prices():
    # SML: illiquid+small until mid-2021, then price & volume jump so it qualifies only from ~2021-07.
    days = pd.bdate_range("2020-06-01", "2021-12-31")
    n = len(days)
    # price 4 (below $5 floor) until day 250, then 20
    price = np.where(np.arange(n) < 250, 4.0, 20.0)
    vol = np.where(np.arange(n) < 250, 1_000, 2_000_000)
    df = pd.DataFrame({COL_TICKER: "SML", COL_DATE: days, COL_CLOSE_RAW: price,
                       COL_CLOSE_ADJ: price, COL_VOLUME: vol})
    return df


def test_smallcap_membership_is_point_in_time(tmp_path):
    cache = ParquetCache(tmp_path)
    cache.put("sharadar", "SF1", _sf1_shares())
    prov = SharadarProvider(cache)
    tickers = _tickers()
    prices = _prices()
    # empty S&P500 table (no exclusions)
    sp500 = pd.DataFrame(columns=["date", "action", "ticker"])

    reb = pd.DatetimeIndex(["2021-01-29", "2021-11-30"])  # before vs after it qualifies
    mem = build_smallcap_membership(prov, tickers, prices, sp500, reb,
                                    cap_low=300e6, cap_high=5e9, min_price=5.0, min_dollar_volume=1e6)
    early = set(mem[mem[COL_DATE] == pd.Timestamp("2021-01-29")][COL_TICKER])
    late = set(mem[mem[COL_DATE] == pd.Timestamp("2021-11-30")][COL_TICKER])
    assert "SML" not in early       # priced $4 / illiquid -> fails price+liquidity at t
    assert "SML" in late            # $20 × 50M = $1B in band, liquid -> qualifies
    assert "ETFX" not in early and "ETFX" not in late   # ETF excluded by category always


def test_market_cap_band_excludes_out_of_band(tmp_path):
    cache = ParquetCache(tmp_path)
    cache.put("sharadar", "SF1", _sf1_shares(shares=2_000_000_000))  # 20 × 2bn = $40B > $5B ceiling
    prov = SharadarProvider(cache)
    prices = _prices()
    sp500 = pd.DataFrame(columns=["date", "action", "ticker"])
    reb = pd.DatetimeIndex(["2021-11-30"])
    mem = build_smallcap_membership(prov, _tickers(), prices, sp500, reb,
                                    cap_low=300e6, cap_high=5e9, min_price=5.0, min_dollar_volume=1e6)
    assert "SML" not in set(mem[COL_TICKER])  # $40B is above the band ceiling
