"""Generic, policy-driven backtest harness. Reused unchanged by the ML strategy in Phase 4/5, so it
knows nothing about any specific signal.

Key separation of concerns:
  * The 63-day LABEL (panel column) is for prediction evaluation (IC/quantiles) only.
  * The backtest earns REALIZED rebalance-to-next-rebalance returns (~1 month) computed here from
    adjusted closes. Horizon and rebalance frequency never get conflated.

Cost model: one-way rate c = (commission_bps + slippage_bps) / 1e4, charged on the traded fraction
Sum|w_target - w_drifted| each rebalance (previous weights are drifted by realized returns first, so
we never charge for passive drift). Net period return = gross - cost.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from ..data.types import COL_CLOSE_ADJ, COL_DATE, COL_TICKER

SIGNAL = "signal"


# --------------------------------------------------------------------------- holding returns
def holding_period_returns(
    prices: pd.DataFrame, rebalance_dates: pd.DatetimeIndex
) -> pd.DataFrame:
    """Realized total return for holding each ticker from one rebalance date to the next.

    Returns long DataFrame[date, ticker, ret] where `ret` is the return earned over [date, next
    rebalance date] on the adjusted close. The final rebalance date has no "next" and is omitted.
    """
    reb = pd.DatetimeIndex(sorted(pd.DatetimeIndex(rebalance_dates).normalize().unique()))
    rows = []
    for ticker, grp in prices.sort_values(COL_DATE).groupby(COL_TICKER):
        s = grp.set_index(COL_DATE)[COL_CLOSE_ADJ]
        s = s[~s.index.duplicated(keep="last")].sort_index()
        if s.empty:
            continue
        first, last = s.index.min(), s.index.max()
        for t, t_next in zip(reb[:-1], reb[1:]):
            if t < first or t_next > last:
                continue
            p0, p1 = s.asof(t), s.asof(t_next)
            if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
                continue
            rows.append((t, ticker, p1 / p0 - 1.0))
    return pd.DataFrame(rows, columns=[COL_DATE, COL_TICKER, "ret"])


# --------------------------------------------------------------------------- policies
class WeightingPolicy(Protocol):
    def weights(self, scored: pd.DataFrame) -> pd.Series:
        """Map a single date's scored universe (columns: ticker, signal) to target weights
        (index=ticker) summing to 1. Long-only."""
        ...


@dataclass
class EqualWeightAll:
    """Equal-weight every eligible name (the universe's own return)."""

    def weights(self, scored: pd.DataFrame) -> pd.Series:
        n = len(scored)
        return pd.Series(1.0 / n, index=scored[COL_TICKER].values) if n else pd.Series(dtype=float)


@dataclass
class TopFractionEqualWeight:
    """Equal-weight the top `frac` of names by signal (e.g., top decile)."""

    frac: float = 0.10

    def weights(self, scored: pd.DataFrame) -> pd.Series:
        n = len(scored)
        if n == 0:
            return pd.Series(dtype=float)
        k = max(1, int(round(n * self.frac)))
        top = scored.nlargest(k, SIGNAL)
        return pd.Series(1.0 / k, index=top[COL_TICKER].values)


# --------------------------------------------------------------------------- engine
@dataclass
class BacktestResult:
    gross_returns: pd.Series      # indexed by rebalance date t; return earned over [t, t_next]
    net_returns: pd.Series
    turnover: pd.Series           # one-way traded fraction Sum|dw|/2 per rebalance
    cost_drag: pd.Series          # gross - net per rebalance
    weights: pd.DataFrame         # date x ticker target weights

    @property
    def summary_index(self) -> pd.DatetimeIndex:
        return self.net_returns.index


def run_backtest(
    signal_panel: pd.DataFrame,
    holding_returns: pd.DataFrame,
    policy: WeightingPolicy,
    cost_bps: float,
) -> BacktestResult:
    """Run the backtest.

    signal_panel: long DataFrame[date, ticker, signal] — the as-of-t scored, eligible universe.
    holding_returns: long DataFrame[date, ticker, ret] from holding_period_returns().
    cost_bps: one-way cost (commission + slippage) in basis points.
    """
    c = cost_bps / 1e4
    ret_lookup = holding_returns.set_index([COL_DATE, COL_TICKER])["ret"]
    dates = sorted(d for d in signal_panel[COL_DATE].unique()
                   if d in set(holding_returns[COL_DATE].unique()))

    prev_w = pd.Series(dtype=float)
    gross, net, turn, drag, wrows = {}, {}, {}, {}, {}
    for t in dates:
        scored = signal_panel[signal_panel[COL_DATE] == t][[COL_TICKER, SIGNAL]]
        w = policy.weights(scored)
        if w.empty:
            continue
        rets = ret_lookup.loc[t].reindex(w.index).fillna(0.0)  # names w/o realized ret contribute 0
        gross_ret = float((w * rets).sum())

        # Drift previous weights by their realized returns to the start of this period.
        if prev_w.empty:
            traded = float(w.abs().sum())  # initial deployment from cash
        else:
            prev_rets = ret_lookup.loc[t].reindex(prev_w.index).fillna(0.0)
            drifted = prev_w * (1.0 + prev_rets)
            tot = drifted.sum()
            drifted = drifted / tot if tot > 0 else drifted
            allnames = w.index.union(drifted.index)
            traded = float((w.reindex(allnames, fill_value=0.0)
                            - drifted.reindex(allnames, fill_value=0.0)).abs().sum())
        cost = c * traded

        gross[t] = gross_ret
        net[t] = gross_ret - cost
        turn[t] = traded / 2.0
        drag[t] = cost
        wrows[t] = w
        prev_w = w

    weights = pd.DataFrame(wrows).T.sort_index() if wrows else pd.DataFrame()
    idx = pd.DatetimeIndex(sorted(gross))
    return BacktestResult(
        gross_returns=pd.Series(gross).reindex(idx),
        net_returns=pd.Series(net).reindex(idx),
        turnover=pd.Series(turn).reindex(idx),
        cost_drag=pd.Series(drag).reindex(idx),
        weights=weights,
    )
