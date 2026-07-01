"""Shared helpers for the research dashboard: cached read-only artifact loaders, the persistent
honesty layer, and small formatting utilities.

Read-only contract: every loader reads a file from data_cache/ or a repo markdown doc. Nothing here
recomputes results or calls a live API. The only transform done in-app is cumulative-product of
already-stored period returns to draw equity curves (display, not recomputation).
"""
from __future__ import annotations

import json
import os
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


def results_dir() -> Path:
    """Results artifact directory. Overridable via EQUITY_ALPHA_RESULTS_DIR (used by tests and to
    point the dashboard at an alternate results set). Read per-call so overrides take effect."""
    override = os.environ.get("EQUITY_ALPHA_RESULTS_DIR")
    return Path(override) if override else REPO / "data_cache" / "results"


REQUIRED_ARTIFACTS = ["meta.json", "baseline_perf.json", "baseline_returns.parquet"]

STRATEGY_ORDER = ["SPY (buy & hold)", "Equal-weight universe", "12-1 Momentum (top decile)",
                  "Value (cheapest decile)"]

BANNER = (
    "**Research project — not investment advice.** All figures are *backtested* and **in-sample** "
    "(no out-of-sample validation yet). Survivorship bias is now addressed (point-in-time membership "
    "+ delisted names). Past backtested performance does **not** imply future results. Nothing here "
    "is a recommendation to buy or sell any security."
)
DATA_STATUS = (
    "Data status: **honest universe** — point-in-time S&P 500 membership + delisted names "
    "(Sharadar SF1/SEP), with delisting-aware returns. **Survivorship bias is now addressed.** "
    "Remaining caveats: results are **in-sample** (no out-of-sample / Phase-4 validation yet), "
    "sector/fundamental classification is current-snapshot, and coverage is limited to Sharadar."
)


def init_page(title: str, icon: str = "📊") -> None:
    st.set_page_config(page_title=f"equity-alpha · {title}", page_icon=icon, layout="wide")


def honesty_layer() -> None:
    """The standing banner + data-status line. Call at the top of every page."""
    st.warning(BANNER)
    st.caption("⚠️ " + DATA_STATUS)


def artifacts_available() -> bool:
    rd = results_dir()
    return all((rd / a).exists() for a in REQUIRED_ARTIFACTS)


def require_artifacts() -> None:
    """Friendly degradation: if results artifacts are missing, show guidance and halt the page
    rather than throwing a raw FileNotFoundError. Call right after honesty_layer() on every page."""
    if not artifacts_available():
        st.info(
            "**Results artifacts not found.** This is a read-only dashboard; it needs the backtest "
            "outputs in `data_cache/results/`. Generate them first (from the repo root, venv active):\n\n"
            "```\npython scripts/phase1_build_panel.py\npython scripts/phase2_baselines.py\n```\n\n"
            "Then reload this page."
        )
        st.stop()


# ------------------------------------------------------------------ cached loaders
@st.cache_data(show_spinner=False)
def load_meta() -> dict:
    return json.loads((results_dir() / "meta.json").read_text())


@st.cache_data(show_spinner=False)
def load_perf() -> dict:
    return json.loads((results_dir() / "baseline_perf.json").read_text())


@st.cache_data(show_spinner=False)
def load_ic() -> dict:
    return json.loads((results_dir() / "momentum_ic.json").read_text())


@st.cache_data(show_spinner=False)
def load_quantiles() -> dict:
    return json.loads((results_dir() / "momentum_quantiles.json").read_text())


@st.cache_data(show_spinner=False)
def load_returns() -> pd.DataFrame:
    df = pd.read_parquet(results_dir() / "baseline_returns.parquet")
    df["date"] = pd.to_datetime(df["date"])
    return df


def flattered_dir() -> Path:
    """The preserved 'before' (survivorship-flattered) results, for the honest-vs-flattered panels."""
    return REPO / "data_cache" / "results_flattered"


@st.cache_data(show_spinner=False)
def load_flattered_returns() -> pd.DataFrame | None:
    p = flattered_dir() / "baseline_returns.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df["date"] = pd.to_datetime(df["date"])
    return df


@st.cache_data(show_spinner=False)
def load_flattered_perf() -> dict | None:
    p = flattered_dir() / "baseline_perf.json"
    return json.loads(p.read_text()) if p.exists() else None


@st.cache_data(show_spinner=False)
def load_ic_series() -> pd.DataFrame:
    return pd.read_parquet(results_dir() / "momentum_ic_series.parquet")


def load_panel() -> pd.DataFrame:
    """Load the EXACT panel these results were computed from (provenance recorded in meta.json).
    Surfaces a clear warning instead of silently pairing mismatched universe/results."""
    meta = load_meta()
    panel_path = meta.get("panel_path")
    if not panel_path:
        st.warning("Panel provenance missing from meta.json — re-run `scripts/phase2_baselines.py` "
                   "to record which panel these results came from.")
        st.stop()
    path = (REPO / panel_path) if not Path(panel_path).is_absolute() else Path(panel_path)
    if not path.exists():
        st.warning(f"Recorded source panel `{panel_path}` not found — results and universe may be "
                   "out of sync. Re-run `scripts/phase2_baselines.py`.")
        st.stop()
    df = _read_panel(str(path))
    expected = meta.get("panel_rows")
    if expected is not None and len(df) != expected:
        st.warning(f"Panel row count ({len(df):,}) ≠ recorded provenance ({expected:,}); "
                   "results may be stale. Re-run `scripts/phase2_baselines.py`.")
    return df


@st.cache_data(show_spinner=False)
def _read_panel(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
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
