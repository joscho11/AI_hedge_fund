"""Forward-return computation: correctness and the no-fill-past-the-end rule."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.corporate_actions import forward_returns_from_adjusted
from src.data.types import COL_CLOSE_ADJ, COL_DATE, COL_TICKER


def _prices(ticker: str, adj: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2021-01-04", periods=len(adj))
    return pd.DataFrame({COL_TICKER: ticker, COL_DATE: dates, COL_CLOSE_ADJ: adj})


def test_forward_return_value_and_horizon():
    prices = _prices("A", [100, 110, 121, 133.1])  # +10% each step
    fwd = forward_returns_from_adjusted(prices, horizon_days=1)
    # First three are +10%; last has no forward observation -> NaN.
    np.testing.assert_allclose(fwd.iloc[:3].to_numpy(), [0.1, 0.1, 0.1], rtol=1e-9)
    assert np.isnan(fwd.iloc[-1])


def test_forward_return_nan_when_horizon_exceeds_history():
    prices = _prices("A", [100, 101])
    fwd = forward_returns_from_adjusted(prices, horizon_days=5)
    assert fwd.isna().all()


def test_forward_return_is_per_ticker():
    a = _prices("A", [100, 200])   # +100%
    b = _prices("B", [100, 50])    # -50%
    fwd = forward_returns_from_adjusted(pd.concat([a, b], ignore_index=True), horizon_days=1)
    out = pd.concat([a, b], ignore_index=True).assign(fwd=fwd)
    assert out.loc[out[COL_TICKER] == "A", "fwd"].iloc[0] == 1.0
    assert out.loc[out[COL_TICKER] == "B", "fwd"].iloc[0] == -0.5
