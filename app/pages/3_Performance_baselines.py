"""Page 3 — Performance / baselines. The heart of the dashboard: equity curves, gross-vs-net
metrics, momentum IC + decile spread, and the plain-English 'real signal vs flashy artifact' read.
Reads baseline_returns / baseline_perf / momentum_ic(+series) / momentum_quantiles.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from common import (
    STRATEGY_ORDER,
    equity_curves,
    fmt_num,
    fmt_pct,
    honesty_layer,
    init_page,
    load_ic,
    load_ic_series,
    load_meta,
    load_perf,
    load_quantiles,
    load_returns,
)

init_page("Performance / baselines")
honesty_layer()

st.title("Performance / baselines")
meta = load_meta()
st.caption(
    f"Full universe: {meta['universe_size']} names · common window "
    f"{meta['common_window'][0]} → {meta['common_window'][1]} "
    f"({meta['common_window'][2]} monthly rebalances) · one-way cost {meta['one_way_cost_bps']:.0f} bps. "
    "Equity curves are cumulative products of stored per-rebalance returns (display only)."
)

# ---------------------------------------------------------------- equity curves
st.subheader("Equity curves (net of costs)")
eq = equity_curves(load_returns(), "net_ret", start=meta["common_window"][0])
st.line_chart(eq)

# ---------------------------------------------------------------- metrics table
st.subheader("Metrics — gross vs net of costs")
perf = load_perf()
rows = []
for name in STRATEGY_ORDER:
    if name not in perf:
        continue
    n, g = perf[name]["net"], perf[name]["gross"]
    rows.append({
        "Strategy": name,
        "CAGR (net)": fmt_pct(n["cagr"]),
        "CAGR (gross)": fmt_pct(g["cagr"]),
        "Ann. vol": fmt_pct(n["ann_vol"]),
        "Sharpe (net)": fmt_num(n["sharpe"], 2),
        "Sortino (net)": fmt_num(n["sortino"], 2),
        "Max DD": fmt_pct(n["max_drawdown"]),
        "Hit rate": fmt_pct(n["hit_rate"]),
        "Turn/reb": fmt_pct(n["avg_turnover"]),
        "Cost drag (cum)": fmt_pct(n["total_cost_drag"]),
    })
st.dataframe(pd.DataFrame(rows).set_index("Strategy"), use_container_width=True)
st.caption("Equal-weight vs SPY = the survivorship drift. Momentum must beat the best of these "
           "**after costs and with signal support** to count as real.")

# ---------------------------------------------------------------- momentum IC
st.subheader("12-1 Momentum — Information Coefficient (the real test)")
ic = load_ic()
ic_rows = [{
    "Target": t,
    "N dates": s["n_dates"],
    "Mean IC": fmt_num(s["mean_ic"], 4),
    "IC IR": fmt_num(s["ic_ir"]),
    "t-stat": fmt_num(s["t_stat"], 2),
    "% positive": fmt_pct(s["frac_positive"]),
} for t, s in ic.items()]
st.dataframe(pd.DataFrame(ic_rows).set_index("Target"), use_container_width=True)
st.caption("IC = per-date Spearman rank correlation between the signal and realized forward return. "
           "A *stable* mean IC of ~0.03–0.05 is a genuine signal; |t| ≥ 2 is the significance bar. "
           "Note: `fwd_ret_raw` and `fwd_ret_excess_median` share an IC because subtracting a per-date "
           "constant does not change ranks (Spearman is rank-based).")

target = st.selectbox("Per-date IC series (pick target)", list(ic.keys()), index=0)
ics = load_ic_series()
if target in ics.columns:
    st.line_chart(ics[[target]].rename(columns={target: f"per-date IC ({target})"}))
    st.caption(f"Mean IC {ic[target]['mean_ic']:+.4f}. The series straddling zero with no drift is "
               "what 'no signal' looks like.")

# ---------------------------------------------------------------- decile spread
st.subheader("12-1 Momentum — decile spread")
quants = load_quantiles()
qtarget = st.selectbox("Decile target", list(quants.keys()), index=0, key="qt")
q = quants[qtarget]
mbq = q["mean_by_quantile"]
ser = pd.Series({f"D{int(k)}": v for k, v in sorted(mbq.items(), key=lambda kv: int(kv[0]))},
                name="mean forward return")
st.bar_chart(ser)
st.caption(
    f"Top−bottom decile spread = {q['top_minus_bottom']:+.4f}; monotonicity ρ = {fmt_num(q['monotonicity'])}. "
    "A real ranking signal makes these bars climb left→right (ρ near +1). Here they do not."
)

# ---------------------------------------------------------------- honest read
st.subheader("Honest read — real signal vs flashy artifact")
ic_raw = ic["fwd_ret_raw"]
mom = perf["12-1 Momentum (top decile)"]["net"]
ew = perf["Equal-weight universe"]["net"]
spy = perf["SPY (buy & hold)"]["net"]
mono = quants["fwd_ret_raw"]["monotonicity"]

st.markdown(
    f"- **Survivorship drift is real and measured:** equal-weight {fmt_pct(ew['cagr'])} vs SPY "
    f"{fmt_pct(spy['cagr'])} CAGR — a ~{(ew['cagr']-spy['cagr'])*100:.1f}pp/yr gap from holding "
    "today's survivors. A *bias*, not alpha.\n"
    f"- **Momentum has no ranking power here:** mean IC **{ic_raw['mean_ic']:+.4f}** "
    f"(t = {ic_raw['t_stat']:+.2f}, {fmt_pct(ic_raw['frac_positive'])} of months positive — a coin "
    f"flip), and the deciles are **non-monotonic** (ρ = {fmt_num(mono)}). This is statistically "
    "indistinguishable from noise."
)
st.error(
    f"**The trap to learn from:** momentum's *top-decile portfolio* posts a higher Sharpe "
    f"({fmt_num(mom['sharpe'],2)}) than equal-weight ({fmt_num(ew['sharpe'],2)}) — but with **no "
    "significant IC beneath it.** Per **DECISIONS D9**, a portfolio Sharpe edge without IC support "
    "is treated as a *fragile, period-specific artifact*, not a discovered signal. This is exactly "
    "how a flashy backtest number fools you: the headline looks great while the underlying signal is "
    "a coin flip. We do **not** trust it."
)

st.subheader("Cost sensitivity (momentum net CAGR)")
cs = meta.get("cost_sensitivity_net_cagr", {})
if cs:
    st.dataframe(
        pd.DataFrame({"One-way cost (bps)": [float(k) for k in cs],
                      "Net CAGR": [fmt_pct(v) for v in cs.values()]}).set_index("One-way cost (bps)"),
        use_container_width=True,
    )
    st.caption("Net CAGR barely moves 5→20 bps: costs are not what holds momentum back — the weak "
               "signal is.")
