"""Momentum feature family — the reference instance of the FeatureFamily template.

Price-only, every feature a strictly TRAILING window on the adjusted close (returns/vol/high-distance
are ratios or daily-return stats, so yfinance's back-adjustment cancels and does not leak). The
dollar-volume trend uses raw close × volume as observed at t. All windows are in trading sessions
(the daily series is one row per session), computed with `min_periods == window` so a partial window
yields NaN rather than a look-ahead-free-but-unstable value — and never a forward fill.

This is NOT a new baseline: Phase 2 used a single 12-1 momentum signal; here we build the richer
momentum feature set through the standard pipeline to feed the Phase 4 model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.types import COL_CLOSE_ADJ, COL_CLOSE_RAW, COL_DATE, COL_TICKER, COL_VOLUME
from .base import FeatureFamily, FeatureSpec

R1, R3, R6 = 21, 63, 126          # 1m/3m/6m in trading days
SKIP, FORM = 21, 252              # 12-1: skip recent month, form over 12m
V6, V12 = 126, 252                # realized-vol windows
HIGH = 252                        # 52-week high window
DV_SHORT, DV_LONG = 21, 252       # dollar-volume trend windows


class MomentumFamily(FeatureFamily):
    name = "momentum"
    specs = [
        FeatureSpec("ret_1m", "trailing 1-month total return",
                    "adj(t)/adj(t-21td) - 1", "NaN until 21 trailing sessions; never filled"),
        FeatureSpec("ret_3m", "trailing 3-month total return",
                    "adj(t)/adj(t-63td) - 1", "NaN until 63 trailing sessions; never filled"),
        FeatureSpec("ret_6m", "trailing 6-month total return",
                    "adj(t)/adj(t-126td) - 1", "NaN until 126 trailing sessions; never filled"),
        FeatureSpec("ret_12_1", "12-month-minus-1-month total return (skip recent month)",
                    "adj(t-21td)/adj(t-252td) - 1", "NaN until 252 trailing sessions; never filled"),
        FeatureSpec("vol_6m", "realized volatility of daily returns, trailing 6m",
                    "std of daily adj returns over (t-126td, t]", "NaN until 126 sessions; never filled"),
        FeatureSpec("vol_12m", "realized volatility of daily returns, trailing 12m",
                    "std of daily adj returns over (t-252td, t]", "NaN until 252 sessions; never filled"),
        FeatureSpec("dist_52w_high", "distance below the trailing 52-week high (<=0)",
                    "adj(t)/max(adj over (t-252td, t]) - 1", "NaN until 252 sessions; never filled"),
        FeatureSpec("dvol_trend", "log ratio of recent vs long-run mean dollar volume",
                    "log( mean$vol(t-21td,t] / mean$vol(t-252td,t] ), raw close x volume",
                    "NaN until 252 sessions; never filled"),
    ]

    def compute_raw(self, panel, rebalance_dates, *, providers, exchange="XNYS") -> pd.DataFrame:
        prices: pd.DataFrame = providers["prices"]
        reb_set = set(pd.DatetimeIndex(rebalance_dates).normalize())
        tickers = set(panel[COL_TICKER].unique())
        px = prices[prices[COL_TICKER].isin(tickers)].sort_values(COL_DATE)

        frames = []
        for tk, g in px.groupby(COL_TICKER):
            s = g.set_index(COL_DATE)
            s = s[~s.index.duplicated(keep="last")].sort_index()
            adj = s[COL_CLOSE_ADJ].astype(float)
            dvol = (s[COL_CLOSE_RAW].astype(float) * s[COL_VOLUME].astype(float))
            dret = adj.pct_change()

            feat = pd.DataFrame(index=adj.index)
            feat["ret_1m"] = adj / adj.shift(R1) - 1.0
            feat["ret_3m"] = adj / adj.shift(R3) - 1.0
            feat["ret_6m"] = adj / adj.shift(R6) - 1.0
            feat["ret_12_1"] = adj.shift(SKIP) / adj.shift(FORM) - 1.0
            feat["vol_6m"] = dret.rolling(V6, min_periods=V6).std()
            feat["vol_12m"] = dret.rolling(V12, min_periods=V12).std()
            feat["dist_52w_high"] = adj / adj.rolling(HIGH, min_periods=HIGH).max() - 1.0
            dv_short = dvol.rolling(DV_SHORT, min_periods=DV_SHORT).mean()
            dv_long = dvol.rolling(DV_LONG, min_periods=DV_LONG).mean()
            # Guard against log(0)/div-by-zero for any zero-volume window (-> NaN, never filled).
            ratio = (dv_short / dv_long).where((dv_short > 0) & (dv_long > 0))
            feat["dvol_trend"] = np.log(ratio)
            feat = feat.replace([np.inf, -np.inf], np.nan)

            feat = feat[feat.index.isin(reb_set)]
            if feat.empty:
                continue
            feat[COL_TICKER] = tk
            frames.append(feat.reset_index())  # index name is 'date' -> column 'date'

        if not frames:
            return pd.DataFrame(columns=[COL_DATE, COL_TICKER, *self.feature_names])
        out = pd.concat(frames, ignore_index=True)
        return out[[COL_DATE, COL_TICKER, *self.feature_names]]
