"""Valuation family leakage + missing-data tests (synthetic Sharadar, no API).

The fundamentals-spirit leakage check: a value restated at a LATER datekey must not change an
earlier-t feature (the numerator is price-at-t, the denominator is the fundamental known at t)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.cache import ParquetCache
from src.data.providers.sharadar import SharadarProvider
from src.data.types import COL_CLOSE_RAW, COL_DATE, COL_TICKER
from src.features.valuation import ValuationFamily

FAM = ValuationFamily()


def _sf1():
    cols = dict(eps=np.nan, sps=np.nan, ebitda=np.nan,
                bvps=np.nan, sharesbas=np.nan, debt=np.nan, cashneq=np.nan)
    rows = []

    def art(tk, datekey, eps, sps=20.0, ebitda=1e9):
        rows.append({**cols, "ticker": tk, "dimension": "ART", "datekey": datekey,
                     "calendardate": "2020-12-31", "eps": eps, "sps": sps, "ebitda": ebitda})

    def arq(tk, datekey, bvps=10.0, shares=1e8, debt=2e8, cash=1e8):
        rows.append({**cols, "ticker": tk, "dimension": "ARQ", "datekey": datekey,
                     "calendardate": "2020-12-31", "bvps": bvps, "sharesbas": shares,
                     "debt": debt, "cashneq": cash})

    # AAA: FY2020 eps originally 5.0 (filed 2021-02-15), RESTATED down to 4.0 (filed 2021-08-01).
    art("AAA", "2021-02-15", 5.0)
    art("AAA", "2021-08-01", 4.0)
    arq("AAA", "2021-02-15")
    # BBB: negative earnings -> earnings_yield must be undefined (NaN), not zero.
    art("BBB", "2021-02-15", -2.0)
    arq("BBB", "2021-02-15")
    return pd.DataFrame(rows)


def _tickers():
    return pd.DataFrame([
        {"table": "SF1", "ticker": "AAA", "sector": "Tech", "siccode": 3571.0, "name": "AAA"},
        {"table": "SF1", "ticker": "BBB", "sector": "Tech", "siccode": 3572.0, "name": "BBB"},
    ])


def _provider(tmp_path):
    cache = ParquetCache(tmp_path)
    cache.put("sharadar", "SF1", _sf1())
    cache.put("sharadar", "TICKERS", _tickers())
    return SharadarProvider(cache)


def _panel():
    # AAA priced at 100 on two dates straddling the restatement; BBB at 50.
    rows = []
    for d in ["2021-05-31", "2021-09-30"]:
        rows.append({COL_DATE: pd.Timestamp(d), COL_TICKER: "AAA", COL_CLOSE_RAW: 100.0})
        rows.append({COL_DATE: pd.Timestamp(d), COL_TICKER: "BBB", COL_CLOSE_RAW: 50.0})
    return pd.DataFrame(rows)


def test_restatement_does_not_change_earlier_t_earnings_yield(tmp_path):
    prov = _provider(tmp_path)
    panel = _panel()
    raw = FAM.compute_raw(panel, pd.DatetimeIndex(panel[COL_DATE].unique()),
                          providers={"fundamentals": prov})
    aaa = raw[raw[COL_TICKER] == "AAA"].set_index(COL_DATE)["earnings_yield"]
    # Before restatement (2021-05-31): original eps 5.0 / price 100 = 0.05 (NOT the future 4.0).
    assert np.isclose(aaa.loc[pd.Timestamp("2021-05-31")], 0.05)
    # After restatement (2021-09-30): latest-known eps 4.0 / 100 = 0.04.
    assert np.isclose(aaa.loc[pd.Timestamp("2021-09-30")], 0.04)


def test_negative_earnings_is_missing_not_zero(tmp_path):
    prov = _provider(tmp_path)
    panel = _panel()
    raw = FAM.compute_raw(panel, pd.DatetimeIndex(panel[COL_DATE].unique()),
                          providers={"fundamentals": prov})
    bbb = raw[raw[COL_TICKER] == "BBB"]["earnings_yield"]
    assert bbb.isna().all()  # undefined, never 0.0


def test_feature_set_and_build_emit_normalized_columns(tmp_path):
    prov = _provider(tmp_path)
    panel = _panel()
    feats = FAM.build(panel, pd.DatetimeIndex(panel[COL_DATE].unique()),
                      providers={"fundamentals": prov})
    assert len(FAM.feature_names) == 12
    for f in ["earnings_yield", "earnings_yield_sectrel", "earnings_yield_hist"]:
        assert f in feats and f"{f}_z" in feats and f"{f}_rank" in feats
