"""Honest universe: point-in-time membership (no name before add / after remove) and delisting-aware
terminal returns (a name wiped out inside the forward window earns its real loss, never NaN-dropped)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.universe.honest_sp500 import (
    members_on,
    membership_intervals,
    terminal_forward_return,
)


def _sp500():
    # AAA: added 2010, removed 2015, re-added 2018 (two intervals).
    # BBB: removed 2012 with no prior add (member before tracking) -> open from -inf.
    return pd.DataFrame([
        {"date": "2010-01-04", "action": "added", "ticker": "AAA"},
        {"date": "2015-06-30", "action": "removed", "ticker": "AAA"},
        {"date": "2018-03-01", "action": "added", "ticker": "AAA"},
        {"date": "2012-09-30", "action": "removed", "ticker": "BBB"},
    ])


def test_membership_intervals_and_reAddition():
    iv = membership_intervals(_sp500())
    aaa = iv[iv.ticker == "AAA"].sort_values("start")
    assert len(aaa) == 2
    assert pd.isna(aaa.iloc[1]["end"])  # re-added, still a member


def test_no_name_before_add_or_after_remove():
    iv = membership_intervals(_sp500())
    assert "AAA" not in members_on(iv, "2009-12-31")     # before first add
    assert "AAA" in members_on(iv, "2012-01-01")          # in first interval
    assert "AAA" not in members_on(iv, "2016-01-01")      # after removal, before re-add
    assert "AAA" in members_on(iv, "2020-01-01")          # re-added
    # BBB was a member before tracking began -> present until its 2012 removal, gone after.
    assert "BBB" in members_on(iv, "2011-01-01")
    assert "BBB" not in members_on(iv, "2013-01-01")


def _series(prices, start="2021-01-04"):
    idx = pd.bdate_range(start, periods=len(prices))
    return pd.Series(prices, index=idx, dtype=float)


def test_terminal_return_normal_within_history():
    s = _series([100, 101, 102, 103, 110, 106])
    t, tgt = s.index[0], s.index[4]
    assert np.isclose(terminal_forward_return(s, t, tgt), 0.10)


def test_terminal_return_acquisition_uses_terminal_price_not_nan():
    # History ends at idx 3 (delisted/acquired); horizon target is beyond it -> use terminal price.
    s = _series([100, 101, 102, 120])
    t = s.index[0]
    tgt = s.index[-1] + pd.Timedelta(days=30)  # past last price
    r = terminal_forward_return(s, t, tgt, is_liquidation=False)
    assert np.isclose(r, 0.20)  # 120/100 - 1, the realized deal outcome (NOT NaN)


def test_terminal_return_liquidation_is_total_loss():
    s = _series([100, 80, 5])  # collapsing
    t = s.index[0]
    tgt = s.index[-1] + pd.Timedelta(days=30)
    assert terminal_forward_return(s, t, tgt, is_liquidation=True) == -1.0


def test_not_held_at_t_returns_none():
    s = _series([100, 101, 102])
    assert terminal_forward_return(s, s.index[-1] + pd.Timedelta(days=5), s.index[-1] + pd.Timedelta(days=70)) is None


# --- delisting-aware monthly holding returns (the subtle survivorship trap in the backtest) ---
def test_holding_return_captures_midmonth_delisting_not_zero():
    from src.data.types import COL_CLOSE_ADJ, COL_DATE, COL_TICKER
    from src.labels.honest_panel import honest_holding_period_returns

    days = pd.bdate_range("2021-01-04", periods=60)
    # GOOD trades the whole window; DEAD's price history ends at day 35 (delists mid-month).
    good = pd.DataFrame({COL_TICKER: "GOOD", COL_DATE: days, COL_CLOSE_ADJ: 100.0})
    dead_days = days[:35]
    dead = pd.DataFrame({COL_TICKER: "DEAD", COL_DATE: dead_days,
                         COL_CLOSE_ADJ: list(pd.Series(range(35)).rmul(-2).add(100))})  # 100 -> 32
    prices = pd.concat([good, dead], ignore_index=True)
    reb = pd.DatetimeIndex([days[0], days[30], days[59]])  # DEAD delists between reb[1] and reb[2]

    # DEAD is a liquidation -> its second holding period must be -100%, never skipped/zero.
    hpr = honest_holding_period_returns(prices, reb, liquidation={"DEAD"})
    dead_rows = hpr[hpr[COL_TICKER] == "DEAD"].set_index(COL_DATE)["ret"]
    assert reb[1] in dead_rows.index, "delisting holding period must be present, not dropped"
    assert dead_rows.loc[reb[1]] == -1.0

    # Non-liquidation delisting (e.g., acquisition) -> realized terminal return, not zero.
    hpr2 = honest_holding_period_returns(prices, reb, liquidation=set())
    d2 = hpr2[hpr2[COL_TICKER] == "DEAD"].set_index(COL_DATE)["ret"]
    assert d2.loc[reb[1]] != 0.0 and d2.loc[reb[1]] < 0  # captured the decline to terminal price
