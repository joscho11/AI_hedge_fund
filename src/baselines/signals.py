"""Baseline as-of-t signals. Each returns a long DataFrame[date, ticker, signal] scored on the
rebalance dates, using only information available at t.
"""
from __future__ import annotations

import pandas as pd

from ..backtest.engine import SIGNAL
from ..data.types import COL_CLOSE_ADJ, COL_DATE, COL_TICKER
from ..utils.calendars import offset_trading_days

# 12-1 momentum: 12 months ~ 252 trading days; skip the most recent 1 month ~ 21 trading days.
FORMATION_DAYS = 252
SKIP_DAYS = 21


def momentum_12_1(
    prices: pd.DataFrame, rebalance_dates: pd.DatetimeIndex, exchange: str = "XNYS"
) -> pd.DataFrame:
    """Trailing 12-month-minus-1-month total return per (ticker, rebalance date).

    signal(t) = adj(t - 21td) / adj(t - 252td) - 1. Uses only prices strictly before t (the most
    recent month is skipped, which is the standard short-term-reversal control) -> no lookahead.
    """
    reb = pd.DatetimeIndex(sorted(pd.DatetimeIndex(rebalance_dates).normalize().unique()))
    # Precompute the two lookback dates per rebalance date (shared across tickers).
    skip_date = {t: offset_trading_days(t, -SKIP_DAYS, exchange) for t in reb}
    form_date = {t: offset_trading_days(t, -FORMATION_DAYS, exchange) for t in reb}

    rows = []
    for ticker, grp in prices.sort_values(COL_DATE).groupby(COL_TICKER):
        s = grp.set_index(COL_DATE)[COL_CLOSE_ADJ]
        s = s[~s.index.duplicated(keep="last")].sort_index()
        if s.empty:
            continue
        first = s.index.min()
        for t in reb:
            df = form_date[t]
            if df < first:
                continue  # insufficient history to form the signal
            p_form, p_skip = s.asof(df), s.asof(skip_date[t])
            if pd.isna(p_form) or pd.isna(p_skip) or p_form <= 0:
                continue
            rows.append((t, ticker, p_skip / p_form - 1.0))
    return pd.DataFrame(rows, columns=[COL_DATE, COL_TICKER, SIGNAL])


def simple_value_stub(*args, **kwargs):  # noqa: D401
    """TODO(Phase 3): as-of-t valuation signal (e.g., trailing earnings yield or P/S).

    DEFERRED from Phase 2 by decision (see DECISIONS.md D7): a clean point-in-time valuation ratio
    requires TTM construction + shares-outstanding alignment from EDGAR, which is feature-layer work.
    Building it hastily here risks a restated/leaky metric, so it is intentionally not implemented
    until Phase 3, where the as-of selector and TTM logic live.
    """
    raise NotImplementedError(
        "Value baseline deferred to Phase 3 (see DECISIONS.md D7 and Phase 3 feature work)."
    )
