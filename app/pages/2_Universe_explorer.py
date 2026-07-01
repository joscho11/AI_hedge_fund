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
    load_flattered_perf,
    load_flattered_returns,
    load_meta,
    load_perf,
    load_panel,
    load_returns,
    require_artifacts,
)

init_page("Universe explorer")
honesty_layer()
require_artifacts()

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

# ---- survivorship drift: honest (default) vs flattered ('before') ----
st.subheader("The survivorship drift — measured, then removed")
st.markdown(
    "Equal-weighting the universe vs buying SPY isolates survivorship bias. On the **flattered** "
    "(current-membership, survivors-only) universe, equal-weight beat SPY by a wide margin — not "
    "skill, just holding the names that *survived and won*. On the **honest** universe (point-in-time "
    "membership + delisted names, delisting-aware returns), that gap should largely disappear."
)
perf = load_perf()
spy_cagr = perf["SPY (buy & hold)"]["net"]["cagr"]
ew_cagr = perf["Equal-weight universe"]["net"]["cagr"]
honest_drift = ew_cagr - spy_cagr

fperf = load_flattered_perf()
c1, c2 = st.columns(2)
if fperf:
    fdrift = fperf["Equal-weight universe"]["net"]["cagr"] - fperf["SPY (buy & hold)"]["net"]["cagr"]
    c1.metric("Drift — flattered ('before')", fmt_pct(fdrift),
              help="Equal-weight − SPY CAGR on the survivors-only universe.")
    c2.metric("Drift — honest (now)", fmt_pct(honest_drift), delta=fmt_pct(honest_drift - fdrift),
              help="Equal-weight − SPY CAGR on the point-in-time, delisting-inclusive universe.")
else:
    c1.metric("Survivorship drift (equal-weight − SPY)", fmt_pct(honest_drift))

st.caption("Equity curves below are the **honest** universe (net of costs).")
eq = equity_curves(load_returns(), "net_ret", start=meta["common_window"][0])
drift_cols = [c for c in ["SPY (buy & hold)", "Equal-weight universe"] if c in eq.columns]
st.line_chart(eq[drift_cols])

fret = load_flattered_returns()
if fret is not None:
    with st.expander("Show the 'before' (flattered) equity curves for comparison"):
        feq = equity_curves(fret, "net_ret")
        fcols = [c for c in ["SPY (buy & hold)", "Equal-weight universe"] if c in feq.columns]
        st.line_chart(feq[fcols])
        st.caption("Survivors-only universe — the equal-weight line pulls away from SPY purely from "
                   "survivorship. Compare the gap to the honest chart above.")
