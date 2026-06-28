"""Abstract provider interfaces. Modeling code depends ONLY on these, so the prototype free stack
(yfinance/EDGAR/FRED) can be swapped for a paid one (Sharadar/Tiingo/Polygon) without touching
features or models.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from .types import CompanyRef


class PriceProvider(ABC):
    @abstractmethod
    def get_prices(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        """Long price frame with PRICE_COLUMNS. Returns BOTH raw and adjusted closes plus volume.

        Caller contract:
          - use `close_adj` for return computation (split+dividend adjusted),
          - use `close_raw` for price-level features as observed at t (P/E, 52wk-high, $-volume).
        """

    @abstractmethod
    def get_corporate_actions(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        """Long table of split and dividend events keyed by ex-date."""


class FundamentalsProvider(ABC):
    @abstractmethod
    def get_facts(
        self, tickers: list[str], tags: list[str], start: str, end: str
    ) -> pd.DataFrame:
        """Long fact frame with FACT_COLUMNS. Returns ALL vintages (incl. amendments) so the as-of
        selector can pick the value known at a given date. `filed` is the availability date."""

    @abstractmethod
    def company_ref(self, tickers: list[str]) -> dict[str, CompanyRef]:
        """Reference data incl. CIK and SIC (free sector proxy) per ticker."""

    @staticmethod
    def as_of(facts: pd.DataFrame, t, lag_trading_days: int = 1, exchange: str = "XNYS") -> dict:
        """Latest value per tag KNOWN AS OF date t (most-recently-disclosed value).

        Selects, per tag, the row with max(filed) <= t - lag_trading_days. This is the single
        choke point that enforces point-in-time correctness for fundamentals.

        NOTE on period semantics: a concept like "Revenues" carries both annual and quarterly
        facts. This selector returns the most recently *disclosed* value for the concept and does
        NOT disambiguate annual vs quarterly — that is a feature-layer concern (e.g., request a
        specific period type, or build TTM in features/). Keeping the selector dumb-but-correct
        keeps the point-in-time guarantee easy to reason about and test.
        """
        from ..utils.calendars import offset_trading_days
        from .types import COL_FILED, COL_TAG, COL_VALUE

        if facts.empty:
            return {}
        cutoff = offset_trading_days(t, -lag_trading_days, exchange) if lag_trading_days else pd.Timestamp(t)
        visible = facts[facts[COL_FILED] <= cutoff]
        if visible.empty:
            return {}
        # For each tag, take the most recently filed value as known at the cutoff.
        idx = visible.sort_values(COL_FILED).groupby(COL_TAG).tail(1)
        return dict(zip(idx[COL_TAG], idx[COL_VALUE]))


class MacroProvider(ABC):
    @abstractmethod
    def get_series(self, series_ids: list[str], start: str, end: str) -> pd.DataFrame:
        """Long macro frame. Each series flagged `is_realtime`; revised series (is_realtime=False)
        are not point-in-time without ALFRED vintages and must be used with care."""
