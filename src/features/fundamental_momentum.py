"""Fundamental-momentum feature family — improving fundamentals before price reprices.

Every feature is a strict TWO-POINT as-of construction: both endpoints are taken as-of their date
(latest filing with datekey <= that date), so neither a future filing nor a later restatement of
either endpoint can change an earlier-t value. Uses ART (trailing-twelve-month) figures to avoid
seasonality.

  * YoY growth     g(t)      = v_asof(t) / v_asof(t-252td) - 1        (undefined if year-ago base<=0)
  * Acceleration   g(t)-g(t-63td)  where g(t-63td)=v_asof(t-63)/v_asof(t-315)-1   (2nd derivative)
  * Margin trend   m_asof(t) - m_asof(t-252td)

Estimate revisions are intentionally ABSENT: SF1 is reported fundamentals, not analyst estimates.
We do not fabricate a proxy; their absence is noted in the report.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.types import COL_DATE, COL_TICKER
from ..utils.calendars import offset_trading_days
from .base import FeatureFamily, FeatureSpec, asof_values

TAGS = ["revenue", "epsusd", "gp", "fcf", "netmargin", "grossmargin"]
Q, Y, QY = 63, 252, 315          # prior quarter, prior year, prior-quarter-minus-a-year (trading days)
FACTS_LOOKBACK_YEARS = 7

_SPECS = [
    FeatureSpec("rev_yoy", "revenue YoY growth (TTM)", "revenue_asof(t)/revenue_asof(t-252td)-1", "NaN if year-ago revenue<=0"),
    FeatureSpec("eps_yoy", "EPS YoY growth (TTM, USD)", "epsusd_asof(t)/epsusd_asof(t-252td)-1", "NaN if year-ago EPS<=0"),
    FeatureSpec("gp_yoy", "gross-profit YoY growth (TTM)", "gp_asof(t)/gp_asof(t-252td)-1", "NaN if year-ago GP<=0"),
    FeatureSpec("fcf_yoy", "FCF YoY growth (TTM)", "fcf_asof(t)/fcf_asof(t-252td)-1", "NaN if year-ago FCF<=0"),
    FeatureSpec("rev_accel", "revenue-growth acceleration", "rev_yoy(t) - rev_yoy(t-63td)", "NaN if either YoY undefined"),
    FeatureSpec("eps_accel", "EPS-growth acceleration", "eps_yoy(t) - eps_yoy(t-63td)", "NaN if either YoY undefined"),
    FeatureSpec("net_margin_trend", "net-margin change YoY", "netmargin_asof(t) - netmargin_asof(t-252td)", "NaN if either endpoint missing"),
    FeatureSpec("gross_margin_trend", "gross-margin change YoY", "grossmargin_asof(t) - grossmargin_asof(t-252td)", "NaN if either endpoint missing"),
]


def _yoy(num, den):
    return np.where(den > 0, num / den - 1.0, np.nan)


class FundamentalMomentumFamily(FeatureFamily):
    name = "fundamental_momentum"
    specs = _SPECS

    def compute_raw(self, panel, rebalance_dates, *, providers, exchange="XNYS") -> pd.DataFrame:
        prov = providers["fundamentals"]
        tickers = sorted(panel[COL_TICKER].unique())
        reb = pd.DatetimeIndex(sorted(pd.to_datetime(panel[COL_DATE].unique())))

        # the four as-of dates per rebalance date
        off = {"0": {t: t for t in reb},
               "q": {t: offset_trading_days(t, -Q, exchange) for t in reb},
               "y": {t: offset_trading_days(t, -Y, exchange) for t in reb},
               "qy": {t: offset_trading_days(t, -QY, exchange) for t in reb}}
        lookup_dates = pd.DatetimeIndex(sorted({d for m in off.values() for d in m.values()}))

        start = (reb.min() - pd.DateOffset(years=FACTS_LOOKBACK_YEARS)).strftime("%Y-%m-%d")
        end = reb.max().strftime("%Y-%m-%d")
        facts = prov.get_facts(tickers, TAGS, start, end, "ART")
        asof = asof_values(facts, lookup_dates)
        if asof.empty:
            return pd.DataFrame(columns=[COL_DATE, COL_TICKER, *self.feature_names])

        base = panel[[COL_DATE, COL_TICKER]].drop_duplicates().copy()
        for lab, mp in off.items():
            base[f"_d{lab}"] = base[COL_DATE].map(mp)
            ren = {COL_DATE: f"_d{lab}", **{tag: f"{tag}_{lab}" for tag in TAGS if tag in asof.columns}}
            base = base.merge(asof.rename(columns=ren), on=[COL_TICKER, f"_d{lab}"], how="left")

        g = base
        # Guarantee every endpoint column exists (a tag that is entirely NaN drops out of the pivot).
        for lab in off:
            for tag in TAGS:
                c = f"{tag}_{lab}"
                if c not in g.columns:
                    g[c] = np.nan
        g["rev_yoy"] = _yoy(g["revenue_0"], g["revenue_y"])
        g["eps_yoy"] = _yoy(g["epsusd_0"], g["epsusd_y"])
        g["gp_yoy"] = _yoy(g["gp_0"], g["gp_y"])
        g["fcf_yoy"] = _yoy(g["fcf_0"], g["fcf_y"])
        g["rev_accel"] = g["rev_yoy"] - _yoy(g["revenue_q"], g["revenue_qy"])
        g["eps_accel"] = g["eps_yoy"] - _yoy(g["epsusd_q"], g["epsusd_qy"])
        g["net_margin_trend"] = g["netmargin_0"] - g["netmargin_y"]
        g["gross_margin_trend"] = g["grossmargin_0"] - g["grossmargin_y"]

        return g[[COL_DATE, COL_TICKER, *self.feature_names]].reset_index(drop=True)
