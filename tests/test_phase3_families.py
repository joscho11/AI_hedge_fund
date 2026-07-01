"""Quality / fundamental-momentum / context families: PIT + restatement leakage + missing-data +
date-level conditioning, against a synthetic Sharadar provider (no API)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.cache import ParquetCache
from src.data.providers.sharadar import SharadarProvider
from src.data.types import COL_CLOSE_RAW, COL_DATE, COL_TICKER
from src.features.fundamental_momentum import FundamentalMomentumFamily
from src.features.quality import QualityFamily


def _provider(tmp_path, sf1):
    cache = ParquetCache(tmp_path)
    cache.put("sharadar", "SF1", sf1)
    cache.put("sharadar", "TICKERS", pd.DataFrame([
        {"table": "SF1", "ticker": "AAA", "sector": "Tech", "siccode": 1.0, "name": "AAA"},
        {"table": "SF1", "ticker": "BBB", "sector": "Tech", "siccode": 2.0, "name": "BBB"},
    ]))
    return SharadarProvider(cache)


def _panel(tickers, dates, price=100.0):
    rows = [{COL_DATE: pd.Timestamp(d), COL_TICKER: t, COL_CLOSE_RAW: price}
            for d in dates for t in tickers]
    return pd.DataFrame(rows)


# ---------------- quality: negative equity -> ROE undefined, not a huge number ----------------
def test_quality_negative_equity_roe_is_nan(tmp_path):
    base = {k: np.nan for k in ["roe", "roic", "roa", "grossmargin", "netmargin", "ebitdamargin",
                                "opinc", "revenue", "ebit", "intexp", "fcf", "fcfps",
                                "de", "currentratio", "equity"]}
    sf1 = pd.DataFrame([
        {**base, "ticker": "AAA", "dimension": "ART", "datekey": "2021-02-15",
         "calendardate": "2020-12-31", "roe": 5.0, "netmargin": 0.1, "revenue": 100, "opinc": 10},
        {**base, "ticker": "AAA", "dimension": "ARQ", "datekey": "2021-02-15",
         "calendardate": "2020-12-31", "equity": -50.0, "de": 3.0, "currentratio": 1.2},
    ])
    prov = _provider(tmp_path, sf1)
    panel = _panel(["AAA"], ["2021-06-30"])
    raw = QualityFamily().compute_raw(panel, pd.DatetimeIndex(panel[COL_DATE].unique()),
                                      providers={"fundamentals": prov})
    row = raw.iloc[0]
    assert pd.isna(row["roe"])            # equity<=0 -> undefined
    assert pd.isna(row["debt_to_equity"])  # equity<=0 -> undefined


# ---------------- fundamental momentum: two-point PIT + restatement leakage ----------------
def _fundmom_sf1():
    base = {k: np.nan for k in ["revenue", "epsusd", "gp", "fcf", "netmargin", "grossmargin"]}
    rows = []

    def art(datekey, calendardate, revenue):
        rows.append({**base, "ticker": "AAA", "dimension": "ART", "datekey": datekey,
                     "calendardate": calendardate, "revenue": revenue, "epsusd": 1.0,
                     "gp": revenue * 0.4, "fcf": revenue * 0.1, "netmargin": 0.1, "grossmargin": 0.4})

    # Year-ago revenue 100 (filed 2019-02-15); current 120 (filed 2020-02-15) -> +20% YoY.
    art("2019-02-15", "2018-12-31", 100.0)
    art("2020-02-15", "2019-12-31", 120.0)
    # A later RESTATEMENT of the current figure to 150 (filed 2020-09-01) must NOT affect t<2020-09.
    art("2020-09-01", "2019-12-31", 150.0)
    return pd.DataFrame(rows)


def test_fundmom_yoy_and_restatement_leakage(tmp_path):
    prov = _provider(tmp_path, _fundmom_sf1())
    # Rebalance ~1 year after the current filing so t-252td lands on/after the year-ago filing.
    panel = _panel(["AAA"], ["2020-06-30"])
    fam = FundamentalMomentumFamily()
    raw = fam.compute_raw(panel, pd.DatetimeIndex(panel[COL_DATE].unique()),
                          providers={"fundamentals": prov})
    rev_yoy = raw.iloc[0]["rev_yoy"]
    # As of 2020-06-30 the known current revenue is 120 (NOT the future 150 restatement) and
    # the year-ago is 100 -> +20%.
    assert np.isclose(rev_yoy, 0.20), rev_yoy


def test_fundmom_yoy_negative_base_is_nan(tmp_path):
    base = {k: np.nan for k in ["revenue", "epsusd", "gp", "fcf", "netmargin", "grossmargin"]}
    rows = [
        {**base, "ticker": "AAA", "dimension": "ART", "datekey": "2019-02-15",
         "calendardate": "2018-12-31", "epsusd": -2.0, "revenue": 100, "gp": 40, "fcf": 10},
        {**base, "ticker": "AAA", "dimension": "ART", "datekey": "2020-02-15",
         "calendardate": "2019-12-31", "epsusd": 3.0, "revenue": 120, "gp": 48, "fcf": 12},
    ]
    prov = _provider(tmp_path, pd.DataFrame(rows))
    panel = _panel(["AAA"], ["2020-06-30"])
    raw = FundamentalMomentumFamily().compute_raw(
        panel, pd.DatetimeIndex(panel[COL_DATE].unique()), providers={"fundamentals": prov})
    assert pd.isna(raw.iloc[0]["eps_yoy"])  # year-ago EPS <= 0 -> growth undefined


# ---------------- context: macro is date-level (constant across names), not normalized ----------
def test_context_macro_constant_across_names(tmp_path):
    from src.features.context import ContextFamily

    prov = _provider(tmp_path, pd.DataFrame([
        {"ticker": "AAA", "dimension": "ARQ", "datekey": "2020-01-01", "calendardate": "2019-12-31"},
    ]))

    class _Macro:
        def get_series(self, ids, start, end):
            d = pd.bdate_range("2020-12-01", "2021-07-01")
            out = []
            for sid, val in zip(ids, [1.5, 4.0, 20.0]):
                out.append(pd.DataFrame({"series_id": sid, "date": d, "value": val}))
            return pd.concat(out, ignore_index=True)

    dates = pd.bdate_range("2021-01-29", periods=4, freq="BME")
    spy = pd.DataFrame({COL_TICKER: "SPY", COL_DATE: pd.bdate_range("2020-06-01", periods=400),
                        "close_adj": np.linspace(100, 200, 400)})
    panel = _panel(["AAA", "BBB"], dates)
    ctx = ContextFamily()
    feats = ctx.build(panel, dates, providers={"fundamentals": prov, "macro": _Macro(), "spy": spy})
    # On any date, the macro values are identical for AAA and BBB (date-level conditioning).
    one_date = feats[feats[COL_DATE] == dates[1]]
    assert one_date["term_spread"].nunique() == 1
    assert one_date["vix"].nunique() == 1
    # build() must NOT add normalized _z/_rank columns for conditioning inputs.
    assert "term_spread_z" not in feats.columns
