"""Live-API smoke checks. Run with: pytest -m network
These hit yfinance/EDGAR/FRED and are excluded from the default offline suite.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.data.cache import ParquetCache
from src.data.interfaces import FundamentalsProvider
from src.data.providers.edgar_fundamentals import EdgarFundamentalsProvider
from src.data.providers.fred_macro import FredMacroProvider
from src.data.providers.yfinance_prices import YFinancePriceProvider
from src.data.types import COL_CLOSE_ADJ, COL_CLOSE_RAW, COL_FILED

pytestmark = pytest.mark.network

UA = "equity-alpha test joseph.schoenbaum@gmail.com"


def test_yfinance_prices_raw_and_adjusted(tmp_path):
    prov = YFinancePriceProvider(ParquetCache(tmp_path))
    df = prov.get_prices(["AAPL"], "2023-01-01", "2023-03-01")
    assert not df.empty
    assert (df[COL_CLOSE_RAW] > 0).all()
    assert (df[COL_CLOSE_ADJ] > 0).all()
    # Dividends/splits make adj != raw historically; at minimum both are populated.
    assert df[COL_CLOSE_ADJ].notna().all()


def test_edgar_facts_have_filed_dates(tmp_path):
    prov = EdgarFundamentalsProvider(ParquetCache(tmp_path), UA)
    facts = prov.get_facts(["AAPL"], ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
                           "2018-01-01", "2024-01-01")
    assert not facts.empty
    assert facts[COL_FILED].notna().all()
    # No filing dated in the future relative to the query window end.
    assert facts[COL_FILED].max() <= pd.Timestamp("2024-01-01")


def test_edgar_company_ref_has_sic(tmp_path):
    prov = EdgarFundamentalsProvider(ParquetCache(tmp_path), UA)
    refs = prov.company_ref(["AAPL"])
    assert "AAPL" in refs
    assert refs["AAPL"].cik == 320193
    assert refs["AAPL"].sic is not None


def test_fred_realtime_series(tmp_path):
    prov = FredMacroProvider(ParquetCache(tmp_path), realtime_only=True)
    df = prov.get_series(["DGS10", "GDP"], "2023-01-01", "2023-06-01")
    # GDP is revised -> excluded by realtime_only; DGS10 is kept.
    assert set(df["series_id"].unique()) == {"DGS10"}
