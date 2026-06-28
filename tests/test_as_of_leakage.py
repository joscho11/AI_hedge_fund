"""The most important test in Phase 0: prove the fundamentals as-of selector never returns a value
that was filed after the query date, and that it honors the filing lag and amendment vintages.
"""
from __future__ import annotations

import pandas as pd

from src.data.interfaces import FundamentalsProvider
from src.data.types import (
    COL_CIK,
    COL_FILED,
    COL_FORM,
    COL_FP,
    COL_FY,
    COL_PERIOD_END,
    COL_TAG,
    COL_TICKER,
    COL_UNIT,
    COL_VALUE,
    FACT_COLUMNS,
)


def _facts() -> pd.DataFrame:
    # Two vintages of FY2020 revenue for the same period:
    #  - original 10-K filed 2021-02-15 with value 100
    #  - amended 10-K/A filed 2021-08-01 restating it to 110
    # Plus a later Q1-2021 revenue filed 2021-11-01 (a NEW disclosure, not a restatement).
    # as_of returns the most-recently-FILED value for the concept; period-type disambiguation
    # (annual vs quarterly) is a feature-layer concern, not the selector's job.
    rows = [
        ("ACME", 1, "Revenues", 100.0, "2020-12-31", "2021-02-15", "10-K", 2020, "FY", "USD"),
        ("ACME", 1, "Revenues", 110.0, "2020-12-31", "2021-08-01", "10-K/A", 2020, "FY", "USD"),
        ("ACME", 1, "Revenues", 30.0, "2021-03-31", "2021-11-01", "10-Q", 2021, "Q1", "USD"),
    ]
    return pd.DataFrame(rows, columns=FACT_COLUMNS).assign(
        **{COL_FILED: lambda d: pd.to_datetime(d[COL_FILED]),
           COL_PERIOD_END: lambda d: pd.to_datetime(d[COL_PERIOD_END])}
    )


def test_as_of_excludes_future_filings():
    facts = _facts()
    # As of 2021-03-01, only the original FY2020 10-K (filed 2021-02-15) is visible.
    got = FundamentalsProvider.as_of(facts, pd.Timestamp("2021-03-01"), lag_trading_days=0)
    assert got["Revenues"] == 100.0


def test_as_of_picks_latest_vintage_known_then_not_restated():
    facts = _facts()
    # Before the amendment is filed, we must still see the ORIGINAL 100, never the future 110.
    got = FundamentalsProvider.as_of(facts, pd.Timestamp("2021-07-01"), lag_trading_days=0)
    assert got["Revenues"] == 100.0
    # After the amendment is filed, the latest-known vintage is the restated 110.
    got2 = FundamentalsProvider.as_of(facts, pd.Timestamp("2021-09-01"), lag_trading_days=0)
    assert got2["Revenues"] == 110.0


def test_as_of_returns_most_recent_period_value():
    facts = _facts()
    # As of 2021-12-01 the most recently filed Revenues row is the Q1-2021 (filed 2021-11-01).
    got = FundamentalsProvider.as_of(facts, pd.Timestamp("2021-12-01"), lag_trading_days=0)
    assert got["Revenues"] == 30.0


def test_as_of_filing_lag_blocks_same_day():
    facts = _facts()
    # Query exactly on the original filing date with a 1-trading-day lag: not yet visible.
    got = FundamentalsProvider.as_of(facts, pd.Timestamp("2021-02-15"), lag_trading_days=1)
    assert "Revenues" not in got
    # One trading day later it becomes visible.
    got2 = FundamentalsProvider.as_of(facts, pd.Timestamp("2021-02-17"), lag_trading_days=1)
    assert got2["Revenues"] == 100.0


def test_as_of_empty():
    empty = pd.DataFrame(columns=FACT_COLUMNS)
    assert FundamentalsProvider.as_of(empty, pd.Timestamp("2021-01-01")) == {}
