"""Assemble the labeled panel: eligible (ticker, rebalance date) rows joined to their realized
forward-return targets. This is the Phase 1 deliverable artifact.
"""
from __future__ import annotations

import pandas as pd

from ..data.types import COL_DATE, COL_TICKER
from ..universe.builder import rebalance_eligibility
from .forward_returns import (
    COL_FWD_EXCESS_MEDIAN,
    COL_FWD_RAW,
    add_excess_targets,
    compute_forward_returns,
)


def build_panel(
    prices: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    sector_map: dict[str, str],
    *,
    horizon_days: int,
    min_price: float,
    min_dollar_volume: float,
    exchange: str = "XNYS",
) -> pd.DataFrame:
    """Return the labeled panel: one row per eligible (date, ticker) with a realized target.

    Columns: date, ticker, sector, close_raw, dollar_vol_20d, fwd_ret_raw,
             fwd_ret_excess_median, fwd_ret_excess_sector.

    A row appears only if (a) it passed the as-of-t liquidity screen AND (b) its H-day forward
    return is realized. Excess targets are recomputed AFTER the eligibility+realized filter so the
    cross-sectional medians reflect the actual tradeable, labeled universe on each date.
    """
    elig = rebalance_eligibility(
        prices, rebalance_dates, min_price=min_price, min_dollar_volume=min_dollar_volume
    )
    elig = elig[elig["eligible"]].drop(columns="eligible")

    fwd = compute_forward_returns(prices, rebalance_dates, horizon_days, exchange)

    panel = elig.merge(fwd, on=[COL_DATE, COL_TICKER], how="inner")
    # Compute excess targets on the final eligible+realized set.
    panel = add_excess_targets(panel, sector_map)

    # fwd_ret_raw is guaranteed present; excess_median always defined; excess_sector NaN iff sector
    # unknown. Drop rows with no raw label (shouldn't happen post-merge, but be explicit).
    panel = panel.dropna(subset=[COL_FWD_RAW, COL_FWD_EXCESS_MEDIAN])
    return panel.sort_values([COL_DATE, COL_TICKER]).reset_index(drop=True)
