"""Forward-return targets (the LABEL — deliberately forward-looking) and the three target columns.

H-day forward return is computed on the ADJUSTED close (total return). Per (ticker, rebalance date)
the target uses prices from t to t+H; this is the label, not a feature, so its forward nature is
intended. The leakage guard here is the opposite one: when the H-day window extends past the last
available price for a ticker, the label is UNREALIZED and must be NaN (later dropped) — never
forward-filled, which would invent a return that did not exist.

Three columns (see DECISIONS D3):
  * fwd_ret_raw            — diagnostics only, never a training target
  * fwd_ret_excess_median  — minus the cross-sectional (universe) median on that date
  * fwd_ret_excess_sector  — minus the within-sector median on that date
Cross-sectional demeaning uses only same-date values => no temporal leakage.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.types import COL_CLOSE_ADJ, COL_DATE, COL_TICKER
from ..utils.calendars import offset_trading_days

COL_FWD_RAW = "fwd_ret_raw"
COL_FWD_EXCESS_MEDIAN = "fwd_ret_excess_median"
COL_FWD_EXCESS_SECTOR = "fwd_ret_excess_sector"
COL_SECTOR = "sector"


def compute_forward_returns(
    prices: pd.DataFrame,
    rebalance_dates: pd.DatetimeIndex,
    horizon_days: int,
    exchange: str = "XNYS",
) -> pd.DataFrame:
    """Raw H-day forward total return per (ticker, rebalance date).

    Returns DataFrame[date, ticker, fwd_ret_raw]; rows whose horizon is not fully realized (target
    session beyond the ticker's last price) are omitted.
    """
    reb = pd.DatetimeIndex(rebalance_dates).normalize()
    # Map each rebalance date to its target session once (same across tickers).
    target = {t: offset_trading_days(t, horizon_days, exchange) for t in reb}

    rows = []
    for ticker, grp in prices.sort_values(COL_DATE).groupby(COL_TICKER):
        s = grp.set_index(COL_DATE)[COL_CLOSE_ADJ]
        s = s[~s.index.duplicated(keep="last")].sort_index()
        if s.empty:
            continue
        first, last = s.index.min(), s.index.max()
        for t in reb:
            if t < first or t > last:
                continue  # not listed at t
            tgt = target[t]
            if tgt > last:
                continue  # horizon not realized -> no label (do NOT fill)
            p0 = s.asof(t)
            p1 = s.asof(tgt)
            if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
                continue
            rows.append((t, ticker, p1 / p0 - 1.0))

    out = pd.DataFrame(rows, columns=[COL_DATE, COL_TICKER, COL_FWD_RAW])
    return out.sort_values([COL_DATE, COL_TICKER]).reset_index(drop=True)


def add_excess_targets(fwd: pd.DataFrame, sector_map: dict[str, str]) -> pd.DataFrame:
    """Add cross-sectional excess-vs-median and excess-vs-sector-median columns.

    Demeaning is per rebalance date (and per sector within date), so it only ever uses contemporaneous
    information.
    """
    df = fwd.copy()
    df[COL_SECTOR] = df[COL_TICKER].map(sector_map)

    # Excess vs universe median (per date).
    med = df.groupby(COL_DATE)[COL_FWD_RAW].transform("median")
    df[COL_FWD_EXCESS_MEDIAN] = df[COL_FWD_RAW] - med

    # Excess vs sector median (per date x sector). Unknown sector -> NaN excess (flagged, not faked).
    sec_med = df.groupby([COL_DATE, COL_SECTOR])[COL_FWD_RAW].transform("median")
    df[COL_FWD_EXCESS_SECTOR] = np.where(
        df[COL_SECTOR].notna(), df[COL_FWD_RAW] - sec_med, np.nan
    )
    return df
