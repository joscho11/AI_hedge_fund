"""Phase 2: backtest harness + metrics. Known-signal sanity (perfect signal => monotonic deciles
and IC=1) and exact cost-application checks."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.backtest.engine import (
    SIGNAL,
    EqualWeightAll,
    TopFractionEqualWeight,
    holding_period_returns,
    run_backtest,
)
from src.data.types import COL_CLOSE_ADJ, COL_DATE, COL_TICKER
from src.eval.metrics import (
    information_coefficient,
    performance_stats,
    quantile_returns,
)

TARGET = "fwd_ret_raw"


def _perfect_panel(n_dates=6, n_names=50, seed=0):
    """Panel where signal == realized target (a perfect predictor)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-29", periods=n_dates, freq="BME")
    rows = []
    for d in dates:
        for i in range(n_names):
            tgt = float(rng.normal(0, 0.1))
            rows.append((d, f"T{i:03d}", tgt, tgt))
    return pd.DataFrame(rows, columns=[COL_DATE, COL_TICKER, SIGNAL, TARGET])


def test_perfect_signal_gives_monotonic_deciles_and_unit_ic():
    panel = _perfect_panel()
    ic_series, ic = information_coefficient(panel, SIGNAL, TARGET)
    assert ic.mean_ic > 0.999            # perfect rank agreement each date
    assert ic.frac_positive == 1.0

    q = quantile_returns(panel, SIGNAL, TARGET, n_quantiles=10)
    assert q.monotonicity > 0.999        # deciles strictly increasing
    assert q.top_minus_bottom > 0
    means = [q.mean_by_quantile[k] for k in sorted(q.mean_by_quantile)]
    assert means == sorted(means)        # non-decreasing


def test_random_signal_has_near_zero_ic():
    rng = np.random.default_rng(1)
    dates = pd.bdate_range("2021-01-29", periods=12, freq="BME")
    rows = []
    for d in dates:
        for i in range(60):
            rows.append((d, f"T{i:03d}", rng.normal(), rng.normal()))
    panel = pd.DataFrame(rows, columns=[COL_DATE, COL_TICKER, SIGNAL, TARGET])
    _, ic = information_coefficient(panel, SIGNAL, TARGET)
    assert abs(ic.mean_ic) < 0.15        # no systematic edge
    assert abs(ic.t_stat) < 2.5          # not significant


# ----------------------------------------------------------------- holding returns + cost model
def _two_name_prices():
    dates = pd.bdate_range("2021-01-01", periods=80)
    # A doubles over the window, B flat. Use adj close.
    a = pd.DataFrame({COL_TICKER: "A", COL_DATE: dates,
                      COL_CLOSE_ADJ: np.linspace(100, 200, 80)})
    b = pd.DataFrame({COL_TICKER: "B", COL_DATE: dates,
                      COL_CLOSE_ADJ: [100.0] * 80})
    return pd.concat([a, b], ignore_index=True)


def test_holding_period_returns_between_rebalances():
    px = _two_name_prices()
    reb = pd.DatetimeIndex([px[COL_DATE].iloc[0], px[COL_DATE].iloc[40], px[COL_DATE].iloc[79]])
    hpr = holding_period_returns(px, reb)
    # Two holding periods per name (first->second, second->third); last date has no "next".
    assert set(hpr[COL_DATE].unique()) == {reb[0], reb[1]}
    b = hpr[hpr[COL_TICKER] == "B"]["ret"]
    assert np.allclose(b, 0.0)           # flat name earns nothing


def test_cost_applied_on_turnover():
    # One date, two names; equal-weight all. First deployment from cash => traded fraction = 1.0,
    # so net = gross - c*1. cost_bps=10 => c=1e-3.
    px = _two_name_prices()
    reb = pd.DatetimeIndex([px[COL_DATE].iloc[0], px[COL_DATE].iloc[40]])
    hpr = holding_period_returns(px, reb)
    signal = pd.DataFrame({COL_DATE: [reb[0], reb[0]], COL_TICKER: ["A", "B"], SIGNAL: [1.0, 1.0]})
    res = run_backtest(signal, hpr, EqualWeightAll(), cost_bps=10.0)
    t = reb[0]
    assert np.isclose(res.cost_drag[t], 1e-3)            # c * traded(=1.0)
    assert np.isclose(res.gross_returns[t] - res.net_returns[t], 1e-3)
    assert np.isclose(res.turnover[t], 0.5)              # Sum|dw|/2 = 1.0/2


def test_zero_cost_gross_equals_net():
    px = _two_name_prices()
    reb = pd.DatetimeIndex([px[COL_DATE].iloc[0], px[COL_DATE].iloc[40], px[COL_DATE].iloc[79]])
    hpr = holding_period_returns(px, reb)
    sig = pd.concat([
        pd.DataFrame({COL_DATE: d, COL_TICKER: ["A", "B"], SIGNAL: [2.0, 1.0]})
        for d in reb[:-1]
    ], ignore_index=True)
    res = run_backtest(sig, hpr, TopFractionEqualWeight(frac=0.5), cost_bps=0.0)
    assert np.allclose(res.gross_returns.values, res.net_returns.values)


def test_performance_stats_basic():
    r = pd.Series([0.02, -0.01, 0.03, 0.00, 0.015])
    p = performance_stats(r, periods_per_year=12)
    assert p.n_periods == 5
    assert 0.0 <= p.hit_rate <= 1.0
    assert p.max_drawdown <= 0.0
