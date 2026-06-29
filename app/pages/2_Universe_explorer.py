"""Page 2 — Universe explorer. Reads the full labeled panel + baseline returns (for the drift)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from common import (
    equity_curves,
    fmt_pct,
    honesty_layer,
    init_page,
    load_meta,
    load_perf,
    load_panel,
    load_returns,
)

init_page("Universe explorer")
honesty_layer()

st.title("Universe explorer")
st.markdown(
    "The tradeable universe each month: current-membership S&P 500 names that pass the as-of-`t` "
    "liquidity screen (min price + 20-day median dollar volume) **and** have a realized 63-day "
    "forward-return label. Eligibility uses only information available at `t` — see "
    "**Methodology & rigor** for the leak-free argument."
)

panel = load_panel()
meta = load_meta()

# ---- breadth + coverage metrics ----
per_date = panel.groupby("date").size()
c1, c2, c3 = st.columns(3)
c1.metric("Distinct names (ever in panel)", panel["ticker"].nunique())
c2.metric("Median names / rebalance", int(per_date.median()))
c3.metric("Sector coverage", fmt_pct(panel["sector"].notna().mean(), 0))

st.subheader("Names per rebalance date")
st.caption("Post-eligibility count. Early-period dips reflect names lacking enough history for the "
           "liquidity window or a realized forward label.")
st.line_chart(per_date.rename("eligible names"))

st.subheader("Sector composition")
sec = (panel.groupby("sector")["ticker"].nunique().sort_values(ascending=False)
       .rename("distinct names"))
st.bar_chart(sec)

# ---- survivorship drift, shown honestly ----
st.subheader("The survivorship drift — a measured bias, not a result")
st.markdown(
    "Equal-weighting the *current* S&P 500 over history beats buying SPY — **not because the strategy "
    "is good, but because today's index members are disproportionately the names that survived and "
    "won.** This gap is *the cost of using survivors-only free data.* It is shown here so it can be "
    "measured and subtracted, never celebrated."
)
eq = equity_curves(load_returns(), "net_ret", start=meta["common_window"][0])
drift_cols = [c for c in ["SPY (buy & hold)", "Equal-weight universe"] if c in eq.columns]
st.line_chart(eq[drift_cols])

perf = load_perf()
spy_cagr = perf["SPY (buy & hold)"]["net"]["cagr"]
ew_cagr = perf["Equal-weight universe"]["net"]["cagr"]
st.metric("Survivorship drift (equal-weight − SPY, CAGR)", fmt_pct(ew_cagr - spy_cagr),
          help="Reference per-period drift: raw forward return averages ~+4.3%/63d.")
st.info(
    "**Expected to shrink toward zero on point-in-time data.** On a survivorship-free dataset "
    "(Sharadar SEP+SF1, which includes delisted names and historical index membership), the "
    "equal-weight universe should no longer systematically out-earn the market by this margin. "
    "Re-running here is a pending milestone; until then, treat every absolute return as upward-biased."
)
