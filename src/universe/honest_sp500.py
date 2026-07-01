"""Point-in-time, delisting-inclusive S&P 500 universe from Sharadar SP500 + TICKERS + SEP + ACTIONS.

This replaces the survivorship-flattered "current membership" universe. At each rebalance date t the
universe is the set of names that were ACTUALLY index members as of t (added-date <= t < removed-date),
including names later removed or delisted.

Entity-key note: Sharadar's `ticker` namespace is non-recycled (verified: 0 of 31,467 tickers map to
>1 permaticker), so joining SP500/SEP/SF1 on `ticker` does not cross-wire companies here. We still
carry `permaticker` (from TICKERS) as the stable entity id and bound SEP/SF1 lookups to a name's
[firstpricedate, lastpricedate] as defense-in-depth.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ---- SP500 membership ---------------------------------------------------------------------------

def membership_intervals(sp500: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct [start, end) index-membership intervals per ticker from add/remove events.

    end is NaT for names still in the index. A 'removed' with no prior 'added' (membership began
    before event tracking) opens at Timestamp.min. Handles re-additions (multiple intervals).
    """
    evt = sp500[sp500["action"].isin(["added", "removed"])][["date", "ticker", "action"]].copy()
    evt["date"] = pd.to_datetime(evt["date"])
    evt = evt.sort_values(["ticker", "date"])
    rows = []
    for tk, g in evt.groupby("ticker"):
        start = None
        for d, action in zip(g["date"], g["action"]):
            if action == "added":
                if start is None:
                    start = d
            else:  # removed
                rows.append((tk, start if start is not None else pd.Timestamp.min, d))
                start = None
        if start is not None:
            rows.append((tk, start, pd.NaT))
    return pd.DataFrame(rows, columns=["ticker", "start", "end"])


def members_on(intervals: pd.DataFrame, t) -> set[str]:
    """Set of member tickers as of date t (start <= t < end)."""
    t = pd.Timestamp(t)
    end = intervals["end"].fillna(pd.Timestamp.max)
    mask = (intervals["start"] <= t) & (t < end)
    return set(intervals.loc[mask, "ticker"])


def membership_panel(sp500: pd.DataFrame, rebalance_dates) -> pd.DataFrame:
    """Long [date, ticker] of index members at each rebalance date (point-in-time)."""
    intervals = membership_intervals(sp500)
    out = []
    for t in pd.DatetimeIndex(sorted(pd.DatetimeIndex(rebalance_dates).normalize().unique())):
        for tk in members_on(intervals, t):
            out.append((t, tk))
    return pd.DataFrame(out, columns=["date", "ticker"]).sort_values(["date", "ticker"]).reset_index(drop=True)


def snapshot_members(sp500: pd.DataFrame) -> dict[pd.Timestamp, set[str]]:
    """The independent 'historical' quarterly membership snapshots, for cross-checking intervals."""
    h = sp500[sp500["action"].isin(["historical", "current"])].copy()
    h["date"] = pd.to_datetime(h["date"])
    return {d: set(g["ticker"]) for d, g in h.groupby("date")}


# ---- delisting-aware terminal return ------------------------------------------------------------
# Rule (documented in reports/honest_universe.md):
#   Forward return t -> t+H is computed on SEP adjusted close. If a name's price history ends before
#   t+H (it delisted inside the window), we use its TERMINAL adjusted close as the forward price --
#   capturing the realized delisting outcome rather than dropping the name (which would re-introduce
#   survivorship bias). For an acquisition the terminal price ~ the deal price (a real, usually small
#   move); for a bankruptcy/liquidation with no acquirer the terminal price reflects the wipeout, and
#   if ACTIONS marks such an event we floor the realized return at -100%.

# Only an explicit bankruptcy/liquidation with no residual is floored at -100%. Acquisitions,
# regulatory/voluntary delistings, etc. use the SEP terminal price, which already reflects the real
# last-traded value (deal price for an acquisition; near-zero for a distressed wipeout).
LIQUIDATION_ACTIONS = {"bankruptcyliquidation"}


def liquidated_tickers(actions: pd.DataFrame) -> set[str]:
    """Tickers with an explicit bankruptcy/liquidation action (terminal return floored at -100%)."""
    return set(actions.loc[actions["action"].isin(LIQUIDATION_ACTIONS), "ticker"])


def terminal_forward_return(
    adj_by_date: pd.Series, t, target_date, *, is_liquidation: bool = False
) -> float | None:
    """Realized H-day forward return for one name, delisting-aware.

    adj_by_date: that name's adjusted close indexed by trading date (sorted).
    Returns None only if the name has no price at/at-or-before t (not held) — never silently NaN for
    a delisting that occurred inside the window.
    """
    if adj_by_date.empty:
        return None
    t, target_date = pd.Timestamp(t), pd.Timestamp(target_date)
    last = adj_by_date.index.max()
    if t < adj_by_date.index.min() or t > last:
        return None  # not trading at t -> not a holdable member observation
    p0 = adj_by_date.asof(t)
    if pd.isna(p0) or p0 <= 0:
        return None
    if target_date <= last:
        p1 = adj_by_date.asof(target_date)          # normal: price realized within history
    else:
        # delisted before the horizon end -> realized terminal outcome
        if is_liquidation:
            return -1.0                              # wiped out: -100%
        p1 = adj_by_date.loc[:last].iloc[-1]         # terminal (e.g., acquisition/deal price)
    if pd.isna(p1) or p0 <= 0:
        return None
    return float(p1 / p0 - 1.0)
