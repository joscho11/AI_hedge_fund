"""yfinance price provider (PROTOTYPE ONLY).

Known limitations baked into how we use it:
  * Survivorship: yfinance only serves tickers that still resolve; delisted/acquired names return
    empty. The universe will therefore be survivors-biased — quantified in LEAKAGE_AUDIT.md.
  * Adj Close is re-adjusted to today (see corporate_actions.py). We keep raw + adjusted separately.
  * Scraped, rate-limited, occasionally gappy; ToS disallows commercial use.
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf

from ..cache import ParquetCache
from ..interfaces import PriceProvider
from ..types import (
    COL_CLOSE_ADJ,
    COL_CLOSE_RAW,
    COL_DATE,
    COL_DIVIDEND,
    COL_HIGH_RAW,
    COL_LOW_RAW,
    COL_OPEN_RAW,
    COL_SPLIT_RATIO,
    COL_TICKER,
    COL_VOLUME,
    PRICE_COLUMNS,
)


class YFinancePriceProvider(PriceProvider):
    def __init__(self, cache: ParquetCache):
        self.cache = cache

    def _fetch_one(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        # auto_adjust=False keeps BOTH raw OHLC and a separate "Adj Close".
        # actions=True attaches Dividends and Stock Splits columns.
        df = yf.Ticker(ticker).history(
            start=start, end=end, auto_adjust=False, actions=True, raise_errors=False
        )
        if df is None or df.empty:
            return pd.DataFrame(columns=PRICE_COLUMNS)
        df = df.reset_index().rename(columns={"Date": COL_DATE})
        df[COL_DATE] = pd.to_datetime(df[COL_DATE]).dt.tz_localize(None).dt.normalize()
        out = pd.DataFrame(
            {
                COL_TICKER: ticker,
                COL_DATE: df[COL_DATE],
                COL_OPEN_RAW: df["Open"],
                COL_HIGH_RAW: df["High"],
                COL_LOW_RAW: df["Low"],
                COL_CLOSE_RAW: df["Close"],
                COL_CLOSE_ADJ: df["Adj Close"] if "Adj Close" in df else df["Close"],
                COL_VOLUME: df["Volume"],
            }
        )
        return out[PRICE_COLUMNS]

    def get_prices(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        frames = []
        for t in tickers:
            key = f"{t}_{start}_{end}"
            cached = self.cache.get("prices", key)
            if cached is None:
                cached = self._fetch_one(t, start, end)
                self.cache.put("prices", key, cached)
            frames.append(cached)
        # Drop empty frames (delisted / no-data tickers) so their all-object columns don't poison
        # the concatenated dtypes, then guarantee a datetime64 date column.
        frames = [f for f in frames if not f.empty]
        if not frames:
            return pd.DataFrame(columns=PRICE_COLUMNS)
        out = pd.concat(frames, ignore_index=True)
        out[COL_DATE] = pd.to_datetime(out[COL_DATE])
        return out.sort_values([COL_TICKER, COL_DATE])

    def _actions_one(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        tk = yf.Ticker(ticker)
        splits = tk.splits
        divs = tk.dividends
        rows = []
        if splits is not None and len(splits):
            for dt, ratio in splits.items():
                rows.append((ticker, pd.Timestamp(dt).tz_localize(None).normalize(),
                             float(ratio), float("nan")))
        if divs is not None and len(divs):
            for dt, amt in divs.items():
                rows.append((ticker, pd.Timestamp(dt).tz_localize(None).normalize(),
                             float("nan"), float(amt)))
        cols = [COL_TICKER, COL_DATE, COL_SPLIT_RATIO, COL_DIVIDEND]
        df = pd.DataFrame(rows, columns=cols)
        if df.empty:
            return df
        mask = (df[COL_DATE] >= pd.Timestamp(start)) & (df[COL_DATE] <= pd.Timestamp(end))
        return df[mask].sort_values(COL_DATE)

    def get_corporate_actions(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        frames = []
        for t in tickers:
            key = f"{t}_{start}_{end}"
            cached = self.cache.get("actions", key)
            if cached is None:
                cached = self._actions_one(t, start, end)
                self.cache.put("actions", key, cached)
            frames.append(cached)
        cols = [COL_TICKER, COL_DATE, COL_SPLIT_RATIO, COL_DIVIDEND]
        frames = [f for f in frames if not f.empty]
        if not frames:
            return pd.DataFrame(columns=cols)
        out = pd.concat(frames, ignore_index=True)
        out[COL_DATE] = pd.to_datetime(out[COL_DATE])
        return out.sort_values([COL_TICKER, COL_DATE])
