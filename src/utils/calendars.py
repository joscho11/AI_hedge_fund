"""Trading-calendar helpers. Never approximate trading days with pandas 'B' frequency —
US market holidays make that wrong. Use the real exchange calendar."""
from __future__ import annotations

import functools

import pandas as pd
import exchange_calendars as xcals


@functools.lru_cache(maxsize=8)
def _calendar(exchange: str):
    return xcals.get_calendar(exchange)


@functools.lru_cache(maxsize=8)
def _all_sessions(exchange: str) -> pd.DatetimeIndex:
    """Full session index for the exchange (tz-naive, normalized). Cached once per exchange so
    trading-day offsets are a simple searchsorted with no fragile window math."""
    return pd.DatetimeIndex(_calendar(exchange).sessions).tz_localize(None).normalize()


def trading_sessions(start: str, end: str, exchange: str = "XNYS") -> pd.DatetimeIndex:
    """Tz-naive DatetimeIndex of trading sessions in [start, end]."""
    sess = _all_sessions(exchange)
    lo = sess.searchsorted(pd.Timestamp(start).normalize(), side="left")
    hi = sess.searchsorted(pd.Timestamp(end).normalize(), side="right")
    return sess[lo:hi]


def offset_trading_days(date, n: int, exchange: str = "XNYS") -> pd.Timestamp:
    """Return the session n trading days after `date` (n may be negative).

    `date` is snapped to the next valid session if it is not itself a session (so position is the
    first session >= date, matching how rebalance dates align to month-end sessions).
    """
    sess = _all_sessions(exchange)
    date = pd.Timestamp(date).normalize()
    pos = int(sess.searchsorted(date, side="left"))
    target = pos + n
    if target < 0 or target >= len(sess):
        raise ValueError(
            f"offset {n} from {date.date()} fell outside the {exchange} calendar "
            f"({sess[0].date()}..{sess[-1].date()})"
        )
    return sess[target]


def month_end_rebalance_dates(start: str, end: str, exchange: str = "XNYS") -> pd.DatetimeIndex:
    """Last trading session of each month in [start, end]."""
    sess = trading_sessions(start, end, exchange)
    s = pd.Series(sess, index=sess)
    last = s.groupby([sess.year, sess.month]).max()
    return pd.DatetimeIndex(sorted(last.values))
