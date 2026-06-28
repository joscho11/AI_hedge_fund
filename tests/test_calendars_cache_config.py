from __future__ import annotations

import pandas as pd

from src.data.cache import ParquetCache
from src.utils.calendars import (
    month_end_rebalance_dates,
    offset_trading_days,
    trading_sessions,
)
from src.utils.config import load_config


def test_config_loads_and_validates():
    cfg = load_config()
    assert cfg.label.horizon_days == 63
    assert cfg.universe.name == "sp500"
    assert set(cfg.label.targets) == {
        "fwd_ret_raw", "fwd_ret_excess_median", "fwd_ret_excess_sector"
    }
    # embargo must be >= horizon to prevent overlap leakage in walk-forward CV
    assert cfg.validation.embargo_days >= cfg.label.horizon_days


def test_trading_sessions_skip_holidays():
    sess = trading_sessions("2021-12-23", "2021-12-28")
    # 2021-12-25 (Christmas, observed 24th) and the weekend are excluded.
    assert pd.Timestamp("2021-12-24") not in sess
    assert pd.Timestamp("2021-12-23") in sess
    assert pd.Timestamp("2021-12-27") in sess


def test_offset_trading_days_skips_weekend():
    # 2021-01-04 is a Monday; +5 trading days lands on the next Monday (2021-01-11).
    got = offset_trading_days("2021-01-04", 5)
    assert got == pd.Timestamp("2021-01-11")
    # negative offset goes backward
    assert offset_trading_days("2021-01-11", -5) == pd.Timestamp("2021-01-04")


def test_month_end_rebalance_dates_are_last_sessions():
    reb = month_end_rebalance_dates("2021-01-01", "2021-03-31")
    assert list(reb) == [
        pd.Timestamp("2021-01-29"),
        pd.Timestamp("2021-02-26"),
        pd.Timestamp("2021-03-31"),
    ]


def test_cache_roundtrip(tmp_path):
    cache = ParquetCache(tmp_path)
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    assert cache.get("ns", "key") is None
    cache.put("ns", "key", df)
    assert cache.has("ns", "key")
    pd.testing.assert_frame_equal(cache.get("ns", "key"), df)
