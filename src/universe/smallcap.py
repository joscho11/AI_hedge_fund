"""Point-in-time small/mid-cap US common-stock universe (Sharadar SEP + SF1 + TICKERS), delisted-
inclusive. Membership is defined purely by as-of-t filters (no index table): a name is in the
universe at rebalance t iff, using only data with date/datekey ≤ t, it is domestic common stock,
its market cap (price-at-t × as-of-t shares) is within the band, it is not a concurrent S&P 500
member, and it passes the price + dollar-volume liquidity floors.

See DECISIONS D18 for the pre-registered band/liquidity choices.
"""
from __future__ import annotations

import pandas as pd

from ..data.types import COL_CLOSE_RAW, COL_DATE, COL_TICKER
from ..features.base import asof_values
from ..universe.builder import rebalance_eligibility
from ..universe.honest_sp500 import members_on, membership_intervals

COMMON_CATEGORIES = {"Domestic Common Stock", "Domestic Common Stock Primary Class"}


def common_stock_tickers(tickers_df: pd.DataFrame) -> list[str]:
    """Domestic common-stock tickers (primary listings), deduped across the TICKERS `table` rows."""
    dc = tickers_df[tickers_df["category"].isin(COMMON_CATEGORIES)]
    return sorted(dc["ticker"].dropna().unique())


def market_cap_asof(
    prov, tickers: list[str], rebalance_dates: pd.DatetimeIndex, prices: pd.DataFrame,
) -> pd.DataFrame:
    """As-of-t shares (ARQ sharesbas, datekey≤t) joined to the raw close at t → market cap.

    Returns long [date, ticker, sharesbas, close_raw, market_cap]."""
    dates = pd.DatetimeIndex(sorted(pd.to_datetime(rebalance_dates).unique()))
    facts = prov.get_facts(tickers, ["sharesbas"], "1998-01-01",
                           dates.max().strftime("%Y-%m-%d"), dimension="ARQ")
    shares = asof_values(facts, dates)  # long [date, ticker, sharesbas]
    if shares.empty:
        return pd.DataFrame(columns=[COL_DATE, COL_TICKER, "sharesbas", COL_CLOSE_RAW, "market_cap"])
    px_at = prices[prices[COL_DATE].isin(set(dates))][[COL_DATE, COL_TICKER, COL_CLOSE_RAW]]
    mc = shares.merge(px_at, on=[COL_DATE, COL_TICKER], how="inner")
    mc["market_cap"] = mc[COL_CLOSE_RAW] * mc["sharesbas"]
    return mc


def build_smallcap_membership(
    prov, tickers_df: pd.DataFrame, prices: pd.DataFrame, sp500: pd.DataFrame,
    rebalance_dates, *, cap_low: float, cap_high: float, min_price: float, min_dollar_volume: float,
) -> pd.DataFrame:
    """Per-rebalance-date small/mid-cap membership. Returns long
    [date, ticker, market_cap, close_raw, dollar_vol_20d] for qualifying names.

    All filters use only as-of-t information; the only forward-looking artifact (the label) is added
    later in the panel build.
    """
    reb = pd.DatetimeIndex(sorted(pd.to_datetime(rebalance_dates).unique()))
    tickers = common_stock_tickers(tickers_df)
    px = prices[prices[COL_TICKER].isin(set(tickers))]

    # liquidity screen (price + 20d median dollar volume), as-of t, on raw prices
    elig = rebalance_eligibility(px, reb, min_price=min_price, min_dollar_volume=min_dollar_volume)
    elig = elig[elig["eligible"]].drop(columns="eligible")

    # market-cap band, as-of t
    mc = market_cap_asof(prov, tickers, reb, px)
    band = mc[(mc["market_cap"] >= cap_low) & (mc["market_cap"] <= cap_high)]

    universe = elig.merge(band[[COL_DATE, COL_TICKER, "market_cap"]], on=[COL_DATE, COL_TICKER],
                          how="inner")

    # exclude concurrent S&P 500 members (the large-cap arena already tested)
    intervals = membership_intervals(sp500)
    keep_rows = []
    for d, g in universe.groupby(COL_DATE):
        sp_members = members_on(intervals, d)
        keep_rows.append(g[~g[COL_TICKER].isin(sp_members)])
    out = pd.concat(keep_rows, ignore_index=True) if keep_rows else universe
    return out.sort_values([COL_DATE, COL_TICKER]).reset_index(drop=True)
