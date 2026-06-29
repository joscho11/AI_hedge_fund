"""Shared helpers for the research dashboard: cached read-only artifact loaders, the persistent
honesty layer, and small formatting utilities.

Read-only contract: every loader reads a file from data_cache/ or a repo markdown doc. Nothing here
recomputes results or calls a live API. The only transform done in-app is cumulative-product of
already-stored period returns to draw equity curves (display, not recomputation).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Make `import common` work from pages/ regardless of how Streamlit set sys.path.
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

REPO = APP_DIR.parent
RESULTS = REPO / "data_cache" / "results"
PANEL_DIR = REPO / "data_cache" / "panel"

STRATEGY_ORDER = ["SPY (buy & hold)", "Equal-weight universe", "12-1 Momentum (top decile)"]

BANNER = (
    "**Research project — not investment advice.** All figures are *backtested* and currently "
    "**survivorship-flattered** (built on the current-membership S&P 500 over a free data stack). "
    "Past backtested performance does **not** imply future results. Nothing here is a recommendation "
    "to buy or sell any security."
)
DATA_STATUS = (
    "Data status: current-membership universe + free stack (yfinance / SEC EDGAR / FRED) — "
    "survivorship and current-fundamentals caveats apply. The honest point-in-time re-run "
    "(Sharadar SEP+SF1) is still pending."
)


def init_page(title: str, icon: str = "📊") -> None:
    st.set_page_config(page_title=f"equity-alpha · {title}", page_icon=icon, layout="wide")


def honesty_layer() -> None:
    """The standing banner + data-status line. Call at the top of every page."""
    st.warning(BANNER)
    st.caption("⚠️ " + DATA_STATUS)


# ------------------------------------------------------------------ cached loaders
@st.cache_data(show_spinner=False)
def load_meta() -> dict:
    return json.loads((RESULTS / "meta.json").read_text())


@st.cache_data(show_spinner=False)
def load_perf() -> dict:
    return json.loads((RESULTS / "baseline_perf.json").read_text())


@st.cache_data(show_spinner=False)
def load_ic() -> dict:
    return json.loads((RESULTS / "momentum_ic.json").read_text())


@st.cache_data(show_spinner=False)
def load_quantiles() -> dict:
    return json.loads((RESULTS / "momentum_quantiles.json").read_text())


@st.cache_data(show_spinner=False)
def load_returns() -> pd.DataFrame:
    df = pd.read_parquet(RESULTS / "baseline_returns.parquet")
    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(show_spinner=False)
def load_ic_series() -> pd.DataFrame:
    return pd.read_parquet(RESULTS / "momentum_ic_series.parquet")


@st.cache_data(show_spinner=False)
def load_panel() -> pd.DataFrame:
    newest = max(PANEL_DIR.glob("panel_*.parquet"), key=lambda p: p.stat().st_mtime)
    df = pd.read_parquet(newest)
    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(show_spinner=False)
def load_doc(name: str) -> str:
    p = REPO / name
    return p.read_text(encoding="utf-8") if p.exists() else f"_{name} not found._"


@st.cache_data(show_spinner=False)
def experiment_count() -> int:
    """Count logged experiment rows in EXPERIMENTS.md (table rows whose first cell is a number)."""
    doc = load_doc("EXPERIMENTS.md")
    return sum(1 for line in doc.splitlines() if re.match(r"^\|\s*\d", line))


# ------------------------------------------------------------------ display transforms
def equity_curves(returns: pd.DataFrame, col: str = "net_ret",
                  start: str | None = None) -> pd.DataFrame:
    """Cumulative growth of $1 from stored per-rebalance returns (display only)."""
    df = returns
    if start is not None:
        df = df[df["date"] >= pd.Timestamp(start)]
    piv = df.pivot(index="date", columns="strategy", values=col).sort_index()
    piv = piv[[c for c in STRATEGY_ORDER if c in piv.columns]]
    return (1.0 + piv).cumprod()


def fmt_pct(x, nd=1):
    return "—" if x is None or pd.isna(x) else f"{x*100:+.{nd}f}%"


def fmt_num(x, nd=3):
    return "—" if x is None or pd.isna(x) else f"{x:.{nd}f}"
