"""Page 4 — Model rankings. STUB placeholder for Phase 4/5. No model exists yet, so this page shows
the spec + data contract and nothing else. Wiring it later should be trivial: drop a parquet at the
documented path and replace the placeholder block.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st

from common import honesty_layer, init_page

init_page("Model rankings")
honesty_layer()

st.title("Model rankings")
st.info("🚧 **Placeholder — no model exists yet.** This page is intentionally empty until Phase 4/5 "
        "trains and validates a model under purged, embargoed walk-forward cross-validation. Nothing "
        "to inspect here today.")

st.subheader("What this page will show (when populated)")
st.markdown(
    "- The model's **current top-decile names** with their scores, framed strictly as "
    "*\"what the model currently ranks highest, for research inspection\"* — **never** as a "
    "directive to buy.\n"
    "- **Per-name explainability:** which feature *families* (momentum, fundamental quality, "
    "fundamental momentum, valuation, sector/macro) drove each name's score.\n"
    "- The full honesty layer above, plus a reminder that a ranking is only trustworthy once its "
    "**IC is significant and confirmed out-of-sample** (DECISIONS D9)."
)

st.warning(
    "**Non-goals restated:** even when populated, this page will have no buy buttons, no order "
    "placement, no position sizing, and no personalized advice. A high model score is a research "
    "observation, not a recommendation."
)

st.subheader("Data contract (for trivial later wiring)")
st.markdown(
    "When the model is ready, Phase 4/5 will write a single artifact and this page will read it "
    "read-only — no other change needed:"
)
st.code(
    "data_cache/results/model_rankings.parquet\n"
    "  columns:\n"
    "    date           datetime64   # rebalance date (latest = current ranking)\n"
    "    ticker         str\n"
    "    score          float        # model's predicted relative forward return / rank score\n"
    "    rank           int          # 1 = highest score on that date\n"
    "    decile         int          # 0..9 (9 = top decile)\n"
    "    contrib_momentum        float   # per-feature-family contribution to the score\n"
    "    contrib_fundamental_quality   float\n"
    "    contrib_fundamental_momentum  float\n"
    "    contrib_valuation             float\n"
    "    contrib_sector_macro          float\n"
    "  sidecar: data_cache/results/model_meta.json  # model id, CV scheme, OOS IC + t-stat, train span",
    language="text",
)
st.caption("TODO(Phase 4/5): populate the artifact above, then replace the placeholder block with a "
           "table of the latest date's top decile + a per-name feature-contribution breakdown.")
