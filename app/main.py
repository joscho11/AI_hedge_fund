"""equity-alpha research dashboard — Page 1: Overview ("what this is and isn't").

Run with:  streamlit run app/main.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from common import experiment_count, honesty_layer, init_page, load_ic, load_meta

init_page("Overview")
honesty_layer()

st.title("equity-alpha — research & explainability dashboard")
st.markdown(
    "A research platform that **ranks US stocks each month by expected *relative* forward return**, "
    "backtests simple trading policies on those rankings, and reports performance honestly against "
    "baselines. The goal is not a high backtest number — it is a *correct, well-validated* system and "
    "an honest read on **where edge does and does not exist**."
)

st.info(
    "**Up front: the baselines tested so far have NOT shown a real edge — and that is the point.** "
    "A research process that only ever 'finds' winning signals is usually fooling itself. Honestly "
    "reporting that 12-1 momentum has no ranking power on this universe is the system working as "
    "intended, not a failure. This dashboard is built to show you *how to tell a real signal from a "
    "flashy-but-empty one.*"
)

meta = load_meta()
ic_mean = load_ic()["fwd_ret_raw"]["mean_ic"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Universe", f"{meta['universe_size']} names", help="Current-membership S&P 500 (free stack).")
c2.metric("Monthly rebalances", meta["common_window"][2])
c3.metric("Backtest window", f"{meta['common_window'][0][:4]}–{meta['common_window'][1][:4]}")
c4.metric("Experiments logged", experiment_count(), help="Multiple-comparisons honesty (EXPERIMENTS.md).")

st.subheader("What this is")
st.markdown(
    "- **Cross-sectional ranking**, not single-stock prediction. Each month we score every eligible "
    "name and rank them; we evaluate the *ranking*, not a buy/sell call.\n"
    "- **Relative** forward return (vs the universe / sector median) — we are trying to learn "
    "outperformance, not market direction.\n"
    "- **Cost- and bias-aware**: every performance number is shown gross *and* net of trading costs, "
    "and stamped with the survivorship caveat."
)

st.subheader("What this is **not**")
st.markdown(
    "- ❌ Not an execution tool — no buy buttons, no broker, no orders.\n"
    "- ❌ Not personalized advice — no 'you should buy X', no position sizing for you.\n"
    "- ❌ Not a directive — any future model ranking is shown strictly *for research inspection*, "
    "wrapped in the caveats above."
)

st.subheader("Project status")
st.markdown(
    "| Phase | Status | What was validated |\n"
    "|---|---|---|\n"
    "| 0 — Data layer | ✅ | Point-in-time provider interfaces, parquet cache, leakage audit. |\n"
    "| 1 — Universe + labels | ✅ | Leak-free labeled panel (forward returns; 3 targets). |\n"
    "| 2 — Baselines + harness | ✅ | Backtest engine, IC / quantile / performance metrics, baselines. |\n"
    "| 3 — Features | ⏳ | Not started (incl. the deferred value baseline). |\n"
    "| 4 — Model + walk-forward CV | ⏳ | Not started. |\n"
    "| 5 — Strategy backtest + exits | ⏳ | Not started. |"
)

st.markdown(
    f"> **Honest headline (full {meta['universe_size']}-name universe):** the equal-weight universe "
    f"beats SPY by ~3.5pp/yr — but that gap is *measured survivorship bias*, not skill. 12-1 momentum "
    f"has a mean information coefficient of **{ic_mean:+.4f}** (a coin flip). "
    "See **Performance / baselines** for the full read."
)

st.caption("Use the sidebar to navigate. Every page repeats the honesty layer above.")
