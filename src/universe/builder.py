"""Per-rebalance-date universe eligibility from liquidity filters.

Eligibility at date t uses ONLY information available at t (the close at t and a trailing 20-day
window ending at t). No future data enters the eligibility decision — this is the half of the
no-lookahead guarantee that lives on the feature/universe side (the label is deliberately forward).

Liquidity uses RAW price and RAW volume (as observed at t), per the raw-vs-adjusted contract.
"""
from __future__ import annotations

import pandas as pd

from ..data.types import COL_CLOSE_RAW, COL_DATE, COL_TICKER, COL_VOLUME

DOLLAR_VOL_WINDOW = 20  # trailing trading days for the median dollar-volume screen


def _dollar_volume(prices: pd.DataFrame) -> pd.Series:
    return prices[COL_CLOSE_RAW] * prices[COL_VOLUME]


def rebalance_eligibility(
    prices: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    min_price: float,
    min_dollar_volume: float,
    window: int = DOLLAR_VOL_WINDOW,
) -> pd.DataFrame:
    """Return DataFrame[date, ticker, close_raw, dollar_vol_20d, eligible] for each rebalance date.

    A (ticker, date) is eligible iff, using only data up to and including t:
      * raw close at t >= min_price, AND
      * trailing `window`-day median dollar volume (close_raw * volume) >= min_dollar_volume.
    Tickers with no observation at t (not yet listed / gap) are absent => implicitly ineligible.
    """
    prices = prices.sort_values([COL_TICKER, COL_DATE]).copy()
    prices["_dv"] = _dollar_volume(prices)
    # Trailing median dollar volume per ticker, ending at each row (inclusive, past-only).
    prices["dollar_vol_20d"] = (
        prices.groupby(COL_TICKER, group_keys=False)["_dv"]
        .apply(lambda s: s.rolling(window, min_periods=window).median())
    )

    reb = set(pd.DatetimeIndex(rebalance_dates).normalize())
    at_reb = prices[prices[COL_DATE].isin(reb)].copy()

    at_reb["eligible"] = (
        (at_reb[COL_CLOSE_RAW] >= min_price)
        & (at_reb["dollar_vol_20d"] >= min_dollar_volume)
    ).fillna(False)

    cols = [COL_DATE, COL_TICKER, COL_CLOSE_RAW, "dollar_vol_20d", "eligible"]
    return at_reb[cols].sort_values([COL_DATE, COL_TICKER]).reset_index(drop=True)
