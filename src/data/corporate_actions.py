"""Corporate-action utilities and the raw-vs-adjusted contract.

We persist BOTH series from the price provider:
  * close_raw  — the price as it actually traded at t (used for price-LEVEL features at t:
                 valuation ratios, distance-from-52wk-high, dollar-volume liquidity screens).
  * close_adj  — split + dividend adjusted (used ONLY for return computation).

Why this matters (yfinance pitfall): yfinance's "Adj Close" is re-adjusted to *today* every time a
new split/dividend occurs, so its absolute level is not what was observed at t. The RATIO of
adjacent adjusted closes is still a valid total return, but any feature that reads a price *level*
must use close_raw as-of t.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .types import COL_CLOSE_ADJ, COL_DATE, COL_TICKER


def forward_returns_from_adjusted(
    prices: pd.DataFrame, horizon_days: int
) -> pd.Series:
    """H-trading-day forward total return per (ticker, date) from adjusted closes.

    Computed strictly on the ADJUSTED series (close_adj). Returns NaN where the horizon extends
    past the last available observation for a ticker — those rows have no realized label and must
    be dropped, never filled.
    """
    out = []
    for ticker, grp in prices.sort_values([COL_TICKER, COL_DATE]).groupby(COL_TICKER):
        adj = grp[COL_CLOSE_ADJ].to_numpy(dtype=float)
        fwd = np.full(len(adj), np.nan)
        if len(adj) > horizon_days:
            fwd[:-horizon_days] = adj[horizon_days:] / adj[:-horizon_days] - 1.0
        s = pd.Series(fwd, index=grp.index)
        out.append(s)
    return pd.concat(out).sort_index()


def trailing_return(prices_ticker: pd.DataFrame, lookback_days: int) -> pd.Series:
    """Trailing total return over `lookback_days` for a single ticker's sorted frame (adjusted)."""
    adj = prices_ticker[COL_CLOSE_ADJ].to_numpy(dtype=float)
    out = np.full(len(adj), np.nan)
    if len(adj) > lookback_days:
        out[lookback_days:] = adj[lookback_days:] / adj[:-lookback_days] - 1.0
    return pd.Series(out, index=prices_ticker.index)
