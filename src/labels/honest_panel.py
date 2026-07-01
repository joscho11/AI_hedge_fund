"""Honest (point-in-time, delisting-inclusive) labeled panel + delisting-aware monthly holding
returns, both fed by Sharadar SEP on the reconstructed honest universe.

Survivorship hides in two places, so BOTH are made delisting-aware here:
  * the forward LABEL (t -> t+H): a name that delists inside the window earns its terminal/realized
    return (−100% for bankruptcy), never a NaN-drop;
  * the monthly HOLDING return used by the backtest: a held name that delists before the next
    rebalance likewise earns its real loss, not a silent 0.

Price columns from SEP: close_raw = `closeunadj` (as-traded; price-level features / liquidity),
close_adj = `closeadj` (total-return adjusted; returns).
"""
from __future__ import annotations

import pandas as pd

from ..data.types import COL_CLOSE_ADJ, COL_CLOSE_RAW, COL_DATE, COL_TICKER, COL_VOLUME
from ..universe.builder import rebalance_eligibility
from ..universe.honest_sp500 import members_on, membership_intervals, terminal_forward_return
from ..utils.calendars import offset_trading_days
from .forward_returns import COL_FWD_RAW, add_excess_targets


def sep_price_frame(sep: pd.DataFrame) -> pd.DataFrame:
    """Map raw SEP to the project's price-frame contract."""
    out = pd.DataFrame({
        COL_TICKER: sep["ticker"],
        COL_DATE: pd.to_datetime(sep["date"]),
        COL_CLOSE_RAW: pd.to_numeric(sep["closeunadj"], errors="coerce"),
        COL_CLOSE_ADJ: pd.to_numeric(sep["closeadj"], errors="coerce"),
        COL_VOLUME: pd.to_numeric(sep["volume"], errors="coerce"),
    })
    return out.dropna(subset=[COL_CLOSE_ADJ]).sort_values([COL_TICKER, COL_DATE])


def _adj_series_by_ticker(prices: pd.DataFrame) -> dict[str, pd.Series]:
    out = {}
    for tk, g in prices.sort_values(COL_DATE).groupby(COL_TICKER):
        s = g.set_index(COL_DATE)[COL_CLOSE_ADJ]
        out[tk] = s[~s.index.duplicated(keep="last")].sort_index()
    return out


def delisting_aware_forward_returns(
    prices: pd.DataFrame, member_pairs: pd.DataFrame, horizon_days: int,
    liquidation: set[str], exchange: str = "XNYS",
) -> pd.DataFrame:
    """Forward H-day return per (date, ticker) for member rows, delisting-aware.

    member_pairs: long [date, ticker] of names that are index members at each date.
    """
    adj = _adj_series_by_ticker(prices)
    dates = pd.DatetimeIndex(sorted(member_pairs[COL_DATE].unique()))
    target = {t: offset_trading_days(t, horizon_days, exchange) for t in dates}
    rows = []
    for t, tk in member_pairs[[COL_DATE, COL_TICKER]].itertuples(index=False):
        s = adj.get(tk)
        if s is None:
            continue
        r = terminal_forward_return(s, t, target[t], is_liquidation=(tk in liquidation))
        if r is not None:
            rows.append((t, tk, r))
    return pd.DataFrame(rows, columns=[COL_DATE, COL_TICKER, COL_FWD_RAW])


def honest_holding_period_returns(
    prices: pd.DataFrame, rebalance_dates, liquidation: set[str],
) -> pd.DataFrame:
    """Realized return for holding each name from one rebalance to the next, delisting-aware.

    If a held name delists between t and t_next, it earns its terminal return (−100% for a
    bankruptcy/liquidation), NOT a silently skipped 0.
    """
    adj = _adj_series_by_ticker(prices)
    reb = pd.DatetimeIndex(sorted(pd.DatetimeIndex(rebalance_dates).normalize().unique()))
    rows = []
    for tk, s in adj.items():
        if s.empty:
            continue
        first, last = s.index.min(), s.index.max()
        liq = tk in liquidation
        for t, t_next in zip(reb[:-1], reb[1:]):
            if t < first or t > last:
                continue  # not held at t
            p0 = s.asof(t)
            if pd.isna(p0) or p0 <= 0:
                continue
            if t_next <= last:
                p1 = s.asof(t_next)
                if pd.isna(p1):
                    continue
                rows.append((t, tk, float(p1 / p0 - 1.0)))
            else:  # delisted inside the holding month
                rows.append((t, tk, -1.0 if liq else float(s.loc[:last].iloc[-1] / p0 - 1.0)))
    return pd.DataFrame(rows, columns=[COL_DATE, COL_TICKER, "ret"])


def build_honest_panel(
    prices: pd.DataFrame, sp500: pd.DataFrame, sector_map: dict[str, str],
    liquidation: set[str], rebalance_dates, *,
    horizon_days: int, min_price: float, min_dollar_volume: float, exchange: str = "XNYS",
) -> pd.DataFrame:
    """Honest labeled panel: (member ∩ liquidity-eligible) rows with delisting-aware targets.

    Mirrors the Phase-1 leakage discipline (as-of-t liquidity screen; forward label dropped only if
    truly not held), now on the point-in-time, delisting-inclusive universe.
    """
    intervals = membership_intervals(sp500)
    reb = pd.DatetimeIndex(sorted(pd.DatetimeIndex(rebalance_dates).normalize().unique()))
    members = pd.DataFrame(
        [(t, tk) for t in reb for tk in members_on(intervals, t)],
        columns=[COL_DATE, COL_TICKER],
    )

    elig = rebalance_eligibility(prices, reb, min_price=min_price,
                                 min_dollar_volume=min_dollar_volume)
    elig = elig[elig["eligible"]].drop(columns="eligible")
    universe = members.merge(elig, on=[COL_DATE, COL_TICKER], how="inner")  # member AND liquid

    fwd = delisting_aware_forward_returns(prices, universe[[COL_DATE, COL_TICKER]],
                                          horizon_days, liquidation, exchange)
    panel = universe.merge(fwd, on=[COL_DATE, COL_TICKER], how="inner")
    panel = add_excess_targets(panel, sector_map)
    panel = panel.dropna(subset=[COL_FWD_RAW, "fwd_ret_excess_median"])
    return panel.sort_values([COL_DATE, COL_TICKER]).reset_index(drop=True)
