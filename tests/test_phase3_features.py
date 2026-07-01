"""Phase 3: feature-family template + momentum family. Leakage (future prices can't change a
feature at t), per-date normalization (never pooled), and no-forward-fill of missing values."""
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
from src.features.momentum import MomentumFamily

FAM = MomentumFamily()


def _prices(ticker, dates, adj, vol=1_000_000):
    return pd.DataFrame({
        COL_TICKER: ticker, COL_DATE: pd.DatetimeIndex(dates),
        COL_CLOSE_ADJ: adj, COL_CLOSE_RAW: adj, COL_VOLUME: vol,
    })


def _daily(ticker, n, start="2018-01-01", growth=0.0005, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n)
    rets = rng.normal(growth, 0.01, n)
    adj = 100 * np.cumprod(1 + rets)
    vol = rng.integers(5_000_000, 9_000_000, n)
    return _prices(ticker, dates, adj, vol)


def test_future_price_spike_cannot_change_feature_at_t():
    px = _daily("A", 400, seed=1)
    dates = px[COL_DATE]
    t = dates.iloc[300]
    reb = pd.DatetimeIndex([t])
    panel = pd.DataFrame({COL_DATE: [t], COL_TICKER: ["A"]})

    base = FAM.compute_raw(panel, reb, providers={"prices": px})
    # Spike every price strictly AFTER t by 10x and recompute.
    spiked = px.copy()
    spiked.loc[spiked[COL_DATE] > t, [COL_CLOSE_ADJ, COL_CLOSE_RAW]] *= 10.0
    after = FAM.compute_raw(panel, reb, providers={"prices": spiked})

    b = base.set_index(COL_TICKER)[FAM.feature_names].loc["A"]
    a = after.set_index(COL_TICKER)[FAM.feature_names].loc["A"]
    pd.testing.assert_series_equal(a, b)  # identical -> no lookahead


def test_normalization_is_per_date_not_pooled():
    # Two dates with very different scales; z-scores must be computed WITHIN each date, so the
    # top-ranked name in each date gets the same z despite different raw magnitudes.
    d1, d2 = pd.Timestamp("2021-01-29"), pd.Timestamp("2021-02-26")
    raw = pd.DataFrame({
        COL_DATE: [d1, d1, d1, d2, d2, d2],
        COL_TICKER: list("ABCABC"),
        "ret_1m": [0.01, 0.02, 0.03, 10.0, 20.0, 30.0],
    })
    fam = MomentumFamily()
    fam.specs = [s for s in MomentumFamily.specs if s.name == "ret_1m"]
    out = fam.normalize(raw)
    z1 = out[out[COL_DATE] == d1].set_index(COL_TICKER)["ret_1m_z"]
    z2 = out[out[COL_DATE] == d2].set_index(COL_TICKER)["ret_1m_z"]
    assert np.isclose(z1["C"], z2["C"])           # both are the per-date max -> same z
    assert np.isclose(z1.mean(), 0.0, atol=1e-9)  # de-meaned within date
    assert (out["ret_1m_rank"].between(0, 1)).all()


def test_missing_history_is_nan_not_filled():
    # Only 100 sessions -> the 252-day features (ret_12_1, vol_12m, dist_52w_high, dvol_trend)
    # cannot be formed and must be NaN, not forward-filled from anything.
    px = _daily("A", 100, seed=2)
    t = px[COL_DATE].iloc[-1]
    reb = pd.DatetimeIndex([t])
    panel = pd.DataFrame({COL_DATE: [t], COL_TICKER: ["A"]})
    raw = FAM.compute_raw(panel, reb, providers={"prices": px}).iloc[0]
    for f in ["ret_12_1", "vol_12m", "dist_52w_high", "dvol_trend"]:
        assert pd.isna(raw[f]), f"{f} should be NaN with insufficient history"
    assert not pd.isna(raw["ret_1m"])  # short window is available


def test_build_joins_to_panel_and_emits_normalized_cols():
    px = pd.concat([_daily(t, 320, seed=i) for i, t in enumerate(["A", "B", "C", "D", "E"])],
                   ignore_index=True)
    t = px[COL_DATE].iloc[300]
    reb = pd.DatetimeIndex([t])
    panel = pd.DataFrame({COL_DATE: [t] * 5, COL_TICKER: ["A", "B", "C", "D", "E"]})
    feats = FAM.build(panel, reb, providers={"prices": px})
    assert len(feats) == 5
    for f in FAM.feature_names:
        assert f in feats and f"{f}_z" in feats and f"{f}_rank" in feats
