"""Quality feature family — profitability, balance-sheet strength, cash generation, stability.
Sharadar SF1, point-in-time (datekey<=t, AR* only). Numerators that need price use price-at-t
(panel close_raw); everything else is the latest as-of-t filing.

Missing-data rules (no fills): ROE / debt-to-equity undefined when equity<=0 (NaN, not a huge number);
interest coverage undefined when interest expense<=0; operating/FCF margin undefined when revenue<=0.
FCF yield keeps its sign (negative FCF = cash burn, informative).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data.types import COL_CLOSE_RAW, COL_DATE, COL_TICKER
from .base import FeatureFamily, FeatureSpec, asof_values

ART_TAGS = ["roe", "roic", "roa", "grossmargin", "netmargin", "ebitdamargin",
            "opinc", "revenue", "ebit", "intexp", "fcf", "fcfps"]
ARQ_TAGS = ["de", "currentratio", "equity"]
HIST_WIN, HIST_MIN = 60, 24
FACTS_LOOKBACK_YEARS = 6

# (name, description, as_of, missing_rule, sector_relative?)
_DEFS = [
    ("roe", "return on equity (ART)", "Sharadar roe, datekey<=t", "NaN if equity<=0", True),
    ("roic", "return on invested capital (ART)", "Sharadar roic, datekey<=t", "NaN if undefined", True),
    ("roa", "return on assets (ART)", "Sharadar roa, datekey<=t", "NaN if undefined", True),
    ("gross_margin", "gross margin (ART)", "Sharadar grossmargin, datekey<=t", "NaN if undefined", True),
    ("op_margin", "operating margin (ART)", "opinc/revenue, datekey<=t", "NaN if revenue<=0", True),
    ("net_margin", "net margin (ART)", "Sharadar netmargin, datekey<=t", "NaN if undefined", True),
    ("ebitda_margin", "EBITDA margin (ART)", "Sharadar ebitdamargin, datekey<=t", "NaN if undefined", False),
    ("debt_to_equity", "debt / equity (ARQ)", "Sharadar de, datekey<=t", "NaN if equity<=0", True),
    ("current_ratio", "current ratio (ARQ)", "Sharadar currentratio, datekey<=t", "NaN if undefined", False),
    ("interest_coverage", "EBIT / interest expense (ART)", "ebit/intexp, datekey<=t", "NaN if intexp<=0", False),
    ("fcf_yield", "FCF yield (FCF per share / price)", "ART fcfps (datekey<=t) / close_raw(t)", "sign kept; NaN if price missing", True),
    ("fcf_margin", "FCF / revenue (ART)", "fcf/revenue, datekey<=t", "NaN if revenue<=0", True),
]


def _specs():
    specs = []
    for name, desc, asof, miss, sr in _DEFS:
        specs.append(FeatureSpec(name, desc, asof, miss))
        if sr:
            specs.append(FeatureSpec(f"{name}_sectrel", f"{desc}, minus as-of sector median",
                                     asof + "; sector from TICKERS (current classification)",
                                     "NaN if level or sector missing"))
    specs.append(FeatureSpec("net_margin_stability", "trailing 5y std of net margin (lower=steadier)",
                             "std over trailing 60m (min 24m) of net_margin (each datekey<=t)",
                             f"NaN until {HIST_MIN} prior monthly obs"))
    return specs


class QualityFamily(FeatureFamily):
    name = "quality"
    specs = _specs()

    def compute_raw(self, panel, rebalance_dates, *, providers, exchange="XNYS") -> pd.DataFrame:
        prov = providers["fundamentals"]
        tickers = sorted(panel[COL_TICKER].unique())
        dates = pd.DatetimeIndex(sorted(pd.to_datetime(panel[COL_DATE].unique())))
        start = (dates.min() - pd.DateOffset(years=FACTS_LOOKBACK_YEARS)).strftime("%Y-%m-%d")
        end = dates.max().strftime("%Y-%m-%d")
        facts = pd.concat([prov.get_facts(tickers, ART_TAGS, start, end, "ART"),
                           prov.get_facts(tickers, ARQ_TAGS, start, end, "ARQ")], ignore_index=True)
        asof = asof_values(facts, dates)
        if asof.empty:
            return pd.DataFrame(columns=[COL_DATE, COL_TICKER, *self.feature_names])
        df = asof.merge(panel[[COL_DATE, COL_TICKER, COL_CLOSE_RAW]], on=[COL_DATE, COL_TICKER], how="inner")
        for c in [*ART_TAGS, *ARQ_TAGS]:
            df[c] = df.get(c, np.nan)
        px = df[COL_CLOSE_RAW]
        eq_ok = df["equity"] > 0
        rev = df["revenue"]

        df["roe"] = np.where(eq_ok, df["roe"], np.nan)
        df["roic"] = df["roic"]
        df["roa"] = df["roa"]
        df["gross_margin"] = df["grossmargin"]
        df["op_margin"] = np.where(rev > 0, df["opinc"] / rev, np.nan)
        df["net_margin"] = df["netmargin"]
        df["ebitda_margin"] = df["ebitdamargin"]
        df["debt_to_equity"] = np.where(eq_ok, df["de"], np.nan)
        df["current_ratio"] = df["currentratio"]
        df["interest_coverage"] = np.where(df["intexp"] > 0, df["ebit"] / df["intexp"], np.nan)
        df["fcf_yield"] = df["fcfps"] / px
        df["fcf_margin"] = np.where(rev > 0, df["fcf"] / rev, np.nan)

        df["sector"] = df[COL_TICKER].map(prov.sectors(tickers))
        for name, *_ , sr in _DEFS:
            if sr:
                med = df.groupby([COL_DATE, "sector"])[name].transform("median")
                df[f"{name}_sectrel"] = df[name] - med

        df = df.sort_values([COL_TICKER, COL_DATE])
        nm = df.groupby(COL_TICKER)["net_margin"]
        df["net_margin_stability"] = nm.transform(lambda s: s.rolling(HIST_WIN, min_periods=HIST_MIN).std())

        return df[[COL_DATE, COL_TICKER, *self.feature_names]].reset_index(drop=True)
