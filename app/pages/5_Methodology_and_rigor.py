"""Page 5 — Methodology & rigor. Surfaces the project's honesty documents in-app so a sophisticated
viewer can audit the leak-free argument, the design decisions, and how many things we've tried.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from common import experiment_count, honesty_layer, init_page, load_doc

init_page("Methodology & rigor")
honesty_layer()

st.title("Methodology & rigor")
st.markdown(
    "What makes this project credible is not a backtest number — it is the discipline around it: a "
    "defensible leak-free argument, design decisions logged with rationale, and an honest count of "
    "everything we have tried (so a lucky result can be judged against the number of attempts)."
)

c1, c2 = st.columns(2)
c1.metric("Experiments logged", experiment_count(),
          help="Rows in EXPERIMENTS.md — the multiple-comparisons ledger.")
c2.metric("Final hold-out", "untouched",
          help="Reserved for a single evaluation at the very end (Phase 5).")

st.info(
    "**Multiple-comparisons honesty:** every signal/model variant we evaluate is logged. With few "
    "attempts, a weak result is not 'p-hacked' into looking real — and the failures (e.g., 12-1 "
    "momentum) are recorded right alongside, not quietly dropped."
)

tab_audit, tab_decisions, tab_experiments = st.tabs(
    ["🔍 Leakage audit", "🧭 Decisions", "🧪 Experiments"]
)
with tab_audit:
    st.markdown("The per-source as-of timing audit and the survivorship-bias quantification.")
    st.markdown(load_doc("LEAKAGE_AUDIT.md"))
with tab_decisions:
    st.markdown("Design choices and their rationale — including **D9**, the guardrail that no "
                "strategy is accepted on portfolio performance alone without IC support + "
                "out-of-sample confirmation.")
    st.markdown(load_doc("DECISIONS.md"))
with tab_experiments:
    st.markdown("Every feature/model variant tried, with its IC and verdict.")
    st.markdown(load_doc("EXPERIMENTS.md"))
