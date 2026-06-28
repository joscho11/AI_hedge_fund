"""Phase 1: prove no future data bleeds into time t, on both the universe and label sides."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.types import (
    COL_CLOSE_ADJ,
    COL_CLOSE_RAW,
    COL_DATE,
    COL_TICKER,
    COL_VOLUME,
)
from src.labels.forward_returns import (
    COL_FWD_EXCESS_MEDIAN,
    COL_FWD_EXCESS_SECTOR,
    COL_FWD_RAW,
    add_excess_targets,
    compute_forward_returns,
)
from src.labels.panel import build_panel
from src.universe.builder import rebalance_eligibility


def _prices(ticker, dates, close_raw, volume, close_adj=None):
    return pd.DataFrame(
        {
            COL_TICKER: ticker,
            COL_DATE: pd.DatetimeIndex(dates),
            COL_CLOSE_RAW: close_raw,
            COL_VOLUME: volume,
            COL_CLOSE_ADJ: close_adj if close_adj is not None else close_raw,
        }
    )


# ----------------------------- universe side -----------------------------

def test_eligibility_uses_only_trailing_data_no_future_spike():
    # Daily series; dollar volume is LOW up to and including t, then SPIKES after t.
    # Eligibility at t must NOT see the future spike.
    dates = pd.bdate_range("2021-01-01", periods=40)
    t = dates[25]
    vol = np.where(np.arange(40) <= 25, 1_000, 10_000_000)  # spike strictly after index 25
    px = _prices("A", dates, close_raw=[50.0] * 40, volume=vol)
    elig = rebalance_eligibility(px, pd.DatetimeIndex([t]), min_price=5.0,
                                 min_dollar_volume=5_000_000)
    row = elig.loc[elig[COL_DATE] == t].iloc[0]
    # 50 * 1000 = 50k median over trailing window << 5M threshold -> ineligible.
    assert not bool(row["eligible"])
    assert row["dollar_vol_20d"] == 50_000.0


def test_eligibility_price_floor():
    dates = pd.bdate_range("2021-01-01", periods=30)
    t = dates[25]
    px = _prices("PENNY", dates, close_raw=[2.0] * 30, volume=[10_000_000] * 30)
    elig = rebalance_eligibility(px, pd.DatetimeIndex([t]), min_price=5.0, min_dollar_volume=1.0)
    assert not bool(elig.iloc[0]["eligible"])  # price 2.0 < 5.0 floor


# ------------------------------- label side ------------------------------

def test_forward_return_value_uses_adjusted_and_calendar_horizon():
    # 10 business days; with horizon of 5 trading days, fwd return at t = adj[t+5]/adj[t]-1.
    dates = pd.bdate_range("2021-01-04", periods=10)
    adj = [100, 101, 102, 103, 104, 110, 106, 107, 108, 109]
    px = _prices("A", dates, close_raw=adj, volume=[1] * 10, close_adj=adj)
    fwd = compute_forward_returns(px, pd.DatetimeIndex([dates[0]]), horizon_days=5)
    # adj[5]/adj[0]-1 = 110/100 - 1 = 0.10
    assert np.isclose(fwd.iloc[0][COL_FWD_RAW], 0.10)


def test_forward_return_unrealized_is_dropped_not_filled():
    dates = pd.bdate_range("2021-01-04", periods=6)
    px = _prices("A", dates, close_raw=[100] * 6, volume=[1] * 6)
    # Horizon 10 trading days extends well past the 6 available -> no realized label.
    fwd = compute_forward_returns(px, pd.DatetimeIndex([dates[0]]), horizon_days=10)
    assert fwd.empty  # dropped, never forward-filled


def test_excess_targets_are_cross_sectional_same_date_only():
    # Two dates, three tickers. Excess = raw - median within the same date.
    d1, d2 = pd.Timestamp("2021-01-29"), pd.Timestamp("2021-02-26")
    fwd = pd.DataFrame(
        {
            COL_DATE: [d1, d1, d1, d2, d2, d2],
            COL_TICKER: ["A", "B", "C", "A", "B", "C"],
            COL_FWD_RAW: [0.10, 0.00, -0.10, 0.20, 0.10, 0.00],
        }
    )
    sectors = {"A": "Tech", "B": "Tech", "C": "Energy"}
    out = add_excess_targets(fwd, sectors)
    # Date 1 median = 0.0 -> excess equals raw.
    d1rows = out[out[COL_DATE] == d1].set_index(COL_TICKER)
    assert np.isclose(d1rows.loc["A", COL_FWD_EXCESS_MEDIAN], 0.10)
    assert np.isclose(d1rows.loc["C", COL_FWD_EXCESS_MEDIAN], -0.10)
    # Date 2 median = 0.10 -> A excess = 0.10.
    d2rows = out[out[COL_DATE] == d2].set_index(COL_TICKER)
    assert np.isclose(d2rows.loc["A", COL_FWD_EXCESS_MEDIAN], 0.10)


def test_excess_sector_uses_within_sector_median():
    d1 = pd.Timestamp("2021-01-29")
    fwd = pd.DataFrame(
        {
            COL_DATE: [d1, d1, d1],
            COL_TICKER: ["A", "B", "C"],
            COL_FWD_RAW: [0.10, 0.20, 0.05],
        }
    )
    sectors = {"A": "Tech", "B": "Tech", "C": "Energy"}
    out = add_excess_targets(fwd, sectors).set_index(COL_TICKER)
    # Tech median = 0.15 -> A = -0.05, B = +0.05. Energy has one name -> excess 0.
    assert np.isclose(out.loc["A", COL_FWD_EXCESS_SECTOR], -0.05)
    assert np.isclose(out.loc["B", COL_FWD_EXCESS_SECTOR], 0.05)
    assert np.isclose(out.loc["C", COL_FWD_EXCESS_SECTOR], 0.0)


def test_unknown_sector_yields_nan_excess_sector_not_zero():
    d1 = pd.Timestamp("2021-01-29")
    fwd = pd.DataFrame({COL_DATE: [d1, d1], COL_TICKER: ["A", "B"], COL_FWD_RAW: [0.1, 0.2]})
    out = add_excess_targets(fwd, {"A": "Tech"}).set_index(COL_TICKER)  # B unknown
    assert np.isnan(out.loc["B", COL_FWD_EXCESS_SECTOR])


# ------------------------------- end-to-end ------------------------------

def test_build_panel_only_eligible_and_realized_rows():
    # 40 days so the 20-day liquidity window is fully populated at t; horizon (5) realized.
    dates = pd.bdate_range("2021-01-04", periods=40)
    t = dates[25]
    # A: liquid, realized horizon. B: illiquid (excluded by screen).
    a = _prices("A", dates, close_raw=[50.0] * 40, volume=[1_000_000] * 40,
                close_adj=list(np.linspace(50, 60, 40)))
    b = _prices("B", dates, close_raw=[50.0] * 40, volume=[10] * 40,
                close_adj=[50.0] * 40)
    px = pd.concat([a, b], ignore_index=True)
    panel = build_panel(
        px, pd.DatetimeIndex([t]), {"A": "Tech", "B": "Tech"},
        horizon_days=5, min_price=5.0, min_dollar_volume=1_000_000,
    )
    assert set(panel[COL_TICKER]) == {"A"}  # B screened out
    assert panel[COL_FWD_RAW].notna().all()
