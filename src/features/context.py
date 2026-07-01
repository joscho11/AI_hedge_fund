"""Sector / macro context family. Two distinct kinds, kept separate and labelled honestly:

  * SECTOR (cross-sectional): as-of sector id from TICKERS — varies across names, model conditioning
    / categorical (sector-relative *wrappers* live in the valuation/quality families, not here).
  * MACRO regime (date-level, FRED): term spread, credit spread, VIX, trailing market return. These
    are CONSTANT across names on a given date, so a standalone cross-sectional IC is ~0 by
    construction — they are conditioning inputs for the model (interactions), NOT ranking signals.

Because these are conditioning inputs, this family deliberately does NOT apply per-date z-score/rank
normalization and does NOT report a cross-sectional IC (see `cross_sectional = False`).
"""
from __future__ import annotations

import pandas as pd

from ..data.types import COL_CLOSE_ADJ, COL_DATE, COL_TICKER
from ..utils.calendars import offset_trading_days
from .base import FeatureFamily, FeatureSpec

MACRO_SERIES = {"term_spread": "T10Y2Y", "credit_spread": "BAMLH0A0HYM2", "vix": "VIXCLS"}
MKT_LOOKBACK = 63


class ContextFamily(FeatureFamily):
    name = "context"
    cross_sectional = False   # conditioning inputs; no cross-sectional IC reported
    specs = [
        FeatureSpec("sector_id", "as-of sector id (TICKERS, current classification)",
                    "integer code of the name's sector at t", "−1 if sector unknown"),
        FeatureSpec("term_spread", "10y-2y Treasury term spread (FRED T10Y2Y), date-level",
                    "FRED value as-of t (real-time series)", "ffill from last obs; date-level"),
        FeatureSpec("credit_spread", "ICE BofA US high-yield OAS (FRED BAMLH0A0HYM2), date-level",
                    "FRED value as-of t (real-time series)", "ffill from last obs; date-level"),
        FeatureSpec("vix", "CBOE VIX (FRED VIXCLS), date-level",
                    "FRED value as-of t (real-time series)", "ffill from last obs; date-level"),
        FeatureSpec("mkt_ret_63d", "trailing 63-day market (SPY) total return, date-level",
                    "SPY closeadj(t)/closeadj(t-63td)-1", "NaN until 63 sessions; date-level"),
    ]

    def compute_raw(self, panel, rebalance_dates, *, providers, exchange="XNYS") -> pd.DataFrame:
        prov = providers["fundamentals"]
        macro = providers["macro"]
        spy = providers["spy"]
        tickers = sorted(panel[COL_TICKER].unique())
        dates = pd.DatetimeIndex(sorted(pd.to_datetime(panel[COL_DATE].unique())))
        start = dates.min().strftime("%Y-%m-%d")
        end = dates.max().strftime("%Y-%m-%d")

        # sector id (cross-sectional). Normalize missing/non-string sectors to "Unknown" so the
        # code mapping is well-ordered (small-cap names can have a NaN sector).
        def _norm(v):
            return v if isinstance(v, str) and v else "Unknown"
        sectors = {t: _norm(s) for t, s in prov.sectors(tickers).items()}
        codes = {s: i for i, s in enumerate(sorted(set(sectors.values())))}
        keys = panel[[COL_DATE, COL_TICKER]].drop_duplicates().copy()
        keys["sector_id"] = keys[COL_TICKER].map(lambda t: codes.get(sectors.get(t, "Unknown"), -1))

        # macro date-level (as-of t)
        ms = macro.get_series(list(MACRO_SERIES.values()), start, end)
        wide = ms.pivot_table(index="date", columns="series_id", values="value").sort_index()
        macro_at = wide.reindex(wide.index.union(dates)).ffill().reindex(dates)
        md = pd.DataFrame({COL_DATE: dates})
        for col, sid in MACRO_SERIES.items():
            md[col] = macro_at[sid].to_numpy() if sid in macro_at.columns else pd.NA

        # trailing market return from SPY (date-level)
        s = spy.sort_values(COL_DATE).set_index(COL_DATE)[COL_CLOSE_ADJ]
        s = s[~s.index.duplicated(keep="last")].sort_index()
        md["mkt_ret_63d"] = [
            (s.asof(t) / s.asof(offset_trading_days(t, -MKT_LOOKBACK, exchange)) - 1.0)
            if s.index.min() <= offset_trading_days(t, -MKT_LOOKBACK, exchange) else float("nan")
            for t in dates
        ]

        out = keys.merge(md, on=COL_DATE, how="left")
        return out[[COL_DATE, COL_TICKER, *self.feature_names]]

    def build(self, panel, rebalance_dates, *, providers, exchange="XNYS") -> pd.DataFrame:
        """Conditioning inputs are stored RAW — no per-date normalization (would zero out the
        date-level macro features and is meaningless for a categorical sector id)."""
        raw = self.compute_raw(panel, rebalance_dates, providers=providers, exchange=exchange)
        keys = panel[[COL_DATE, COL_TICKER]].drop_duplicates()
        return keys.merge(raw, on=[COL_DATE, COL_TICKER], how="left").sort_values(
            [COL_DATE, COL_TICKER]).reset_index(drop=True)
