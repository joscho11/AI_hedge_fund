"""Sharadar point-in-time leakage tests (synthetic SF1 — no API/key needed).

Fundamentals raise the stakes vs momentum: a value restated LATER (a newer datekey) must not change
any feature at an earlier t, and the restatement-backfilled MR* dimensions must be impossible to
query at all.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.data.cache import ParquetCache
from src.data.interfaces import FundamentalsProvider
from src.data.providers.sharadar import SharadarProvider
from src.data.types import COL_FILED, COL_TAG, COL_VALUE


def _sf1():
    # ACME FY2020 EPS, as-reported quarterly (ARQ):
    #   original  filed (datekey) 2021-02-15, eps = 4.00
    #   restated  filed (datekey) 2021-08-01, eps = 3.10   (same fiscal period, later datekey)
    # Plus an MRQ row that backfills the restatement onto the original period — must be unreachable.
    return pd.DataFrame([
        {"ticker": "ACME", "dimension": "ARQ", "datekey": "2021-02-15",
         "calendardate": "2020-12-31", "eps": 4.00, "sps": 20.0},
        {"ticker": "ACME", "dimension": "ARQ", "datekey": "2021-08-01",
         "calendardate": "2020-12-31", "eps": 3.10, "sps": 19.0},
        {"ticker": "ACME", "dimension": "MRQ", "datekey": "2021-02-15",
         "calendardate": "2020-12-31", "eps": 3.10, "sps": 19.0},
    ])


def _provider(tmp_path) -> SharadarProvider:
    cache = ParquetCache(tmp_path)
    cache.put("sharadar", "SF1", _sf1())
    return SharadarProvider(cache)


def test_mr_dimensions_are_refused(tmp_path):
    prov = _provider(tmp_path)
    with pytest.raises(ValueError, match="as-reported"):
        prov.get_facts(["ACME"], ["eps"], "2000-01-01", "2030-01-01", dimension="MRQ")


def test_get_facts_only_returns_requested_ar_dimension(tmp_path):
    prov = _provider(tmp_path)
    facts = prov.get_facts(["ACME"], ["eps", "sps"], "2000-01-01", "2030-01-01", dimension="ARQ")
    # Two ARQ vintages of eps (original + restatement); the MRQ row is never included.
    assert set(facts[COL_TAG]) == {"eps", "sps"}
    assert (facts[COL_FILED] <= pd.Timestamp("2021-08-01")).all()
    eps = facts[facts[COL_TAG] == "eps"]
    assert sorted(eps[COL_VALUE]) == [3.10, 4.00]


def test_restatement_does_not_change_earlier_t(tmp_path):
    prov = _provider(tmp_path)
    facts = prov.get_facts(["ACME"], ["eps"], "2000-01-01", "2030-01-01", dimension="ARQ")
    # Before the restatement was filed, the value KNOWN at t is the original 4.00 — never 3.10.
    got = FundamentalsProvider.as_of(facts, pd.Timestamp("2021-05-01"), lag_trading_days=0)
    assert got["eps"] == 4.00
    # After the restatement's datekey, the latest-known value is the restated 3.10.
    got_after = FundamentalsProvider.as_of(facts, pd.Timestamp("2021-09-01"), lag_trading_days=0)
    assert got_after["eps"] == 3.10


def test_as_of_excludes_future_datekey(tmp_path):
    prov = _provider(tmp_path)
    facts = prov.get_facts(["ACME"], ["eps"], "2000-01-01", "2030-01-01", dimension="ARQ")
    # As of a date before ANY datekey, nothing is visible.
    assert FundamentalsProvider.as_of(facts, pd.Timestamp("2021-01-01"), lag_trading_days=0) == {}
