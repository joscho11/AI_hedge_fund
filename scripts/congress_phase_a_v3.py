"""Congress Phase A v3 — clustering feature (Test 1) + individual-member persistence (Test 2).
Pre-registered in DECISIONS D21. Market-adjusted, disclosure-date entry, DEV (<=2022) only; 2023+
hold-out SEALED. Descriptive/in-sample; STOP for review.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as pa_ds
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data.cache import ParquetCache
from src.utils.calendars import trading_sessions
from src.utils.config import load_config

REPO = Path(__file__).resolve().parents[1]
ARCHIVE_SFP = REPO / "data_archive" / "sharadar_parquet" / "SFP.parquet"
DEV_END = "2022-12-31"
CLUSTER_N, CLUSTER_WIN = 3, 30       # >=3 distinct members within 30 disclosure days
MIN_BUYS_TOTAL, MIN_PER_PERIOD = 25, 10
P1 = (2014, 2018)
P2 = (2019, 2022)


def adj_series(rows):
    out = {}
    for tk, g in rows.sort_values("date").groupby("ticker"):
        s = pd.Series(g["closeadj"].values, index=pd.to_datetime(g["date"]).values, dtype=float)
        out[tk] = s[~s.index.duplicated(keep="last")].sort_index()
    return out


def fwd(adj, sessions, entry, h):
    if adj is None or adj.empty:
        return None
    last = adj.index.max()
    pos = sessions.searchsorted(pd.Timestamp(entry), "left")
    if pos + h >= len(sessions):
        return None
    if sessions[pos] > last:
        return None
    p0 = adj.asof(sessions[pos])
    if pd.isna(p0) or p0 <= 0:
        return None
    t = sessions[pos + h]
    p1 = adj.asof(t) if t <= last else (adj.loc[:last].iloc[-1] if last < sessions[-1] else np.nan)
    return None if pd.isna(p1) else float(p1 / p0 - 1.0)


def build_buys(cache, cfg):
    full = pd.read_parquet(cache.root / "congress" / "full_transactions.parquet")
    full["transaction_date"] = pd.to_datetime(full["transaction_date"], errors="coerce")
    full["filing_date"] = pd.to_datetime(full["filing_date"], errors="coerce")
    fid = full["filer_id"].astype(str)
    full["member"] = fid.str.replace(r"^(house|senate|exec)_", "", regex=True).str.replace("_", " ").str.title()
    full["ticker"] = full["ticker"].astype("string").str.upper().str.strip()
    tk = cache.get("sharadar", "TICKERS")
    common = set(tk.loc[tk["category"].isin(
        ["Domestic Common Stock", "Domestic Common Stock Primary Class"]), "ticker"].dropna().str.upper())
    buys = full[(full["transaction_type"] == "Purchase") & full["transaction_date"].notna()
                & full["filing_date"].notna() & full["ticker"].isin(common)].copy()
    buys = buys[buys["filing_date"] <= pd.Timestamp(DEV_END)]        # DEV ONLY

    tickers = buys["ticker"].unique().tolist()
    sep = pa_ds.dataset(str(cache.root / "sharadar" / "SEP.parquet"), format="parquet").to_table(
        columns=["ticker", "date", "closeadj"], filter=pa_ds.field("ticker").isin(tickers)).to_pandas()
    buys = buys[buys["ticker"].isin(set(sep["ticker"].unique()))].copy()
    adj = adj_series(sep)
    spy = adj_series(pa_ds.dataset(str(ARCHIVE_SFP), format="parquet").to_table(
        columns=["ticker", "date", "closeadj"], filter=pa_ds.field("ticker") == "SPY").to_pandas()).get("SPY")
    sessions = trading_sessions(cfg.dates.start, str(pd.to_datetime(sep["date"]).max().date()), cfg.calendar.exchange)

    # per-buy market-adjusted disclosure-date returns
    recs = []
    for r in buys.itertuples(index=False):
        s = adj.get(r.ticker)
        rec = {"member": r.member, "ticker": r.ticker, "disclosure_date": r.filing_date,
               "year": r.filing_date.year}
        keep = False
        for h in (21, 63):
            st = fwd(s, sessions, r.filing_date, h); mk = fwd(spy, sessions, r.filing_date, h)
            rec[f"adj{h}"] = (st - mk) if (st is not None and mk is not None) else None
            keep = keep or rec[f"adj{h}"] is not None
        if keep:
            recs.append(rec)
    return pd.DataFrame(recs), adj, spy, sessions


def detect_clusters(buys):
    """One event per clustering episode: fires when trailing-30d distinct-member count first hits N,
    re-arms after it drops below N. Entry = completing disclosure date (lookahead-safe)."""
    events, cluster_keys = [], set()
    for tk, g in buys.sort_values("disclosure_date").groupby("ticker"):
        win, fired = [], False
        for row in g.itertuples(index=False):
            t = row.disclosure_date
            win = [(d, m) for (d, m) in win if (t - d).days <= CLUSTER_WIN]
            win.append((t, row.member))
            distinct = len({m for _, m in win})
            if distinct >= CLUSTER_N and not fired:
                events.append({"ticker": tk, "complete_date": t, "n_members": distinct})
                fired = True
            elif distinct < CLUSTER_N:
                fired = False
            if fired:  # tag buys occurring while a cluster is active as cluster-associated
                cluster_keys.add((tk, t, row.member))
    return pd.DataFrame(events), cluster_keys


def _stat(v):
    v = pd.Series(v).dropna()
    return {"n": int(len(v)), "mean": float(v.mean()) if len(v) else None,
            "median": float(v.median()) if len(v) else None,
            "t": float(stats.ttest_1samp(v, 0).statistic) if len(v) > 2 else None}


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    buys, adj, spy, sessions = build_buys(cache, cfg)
    print(f"dev equity buys with realized fwd: {len(buys):,} "
          f"({buys['disclosure_date'].min().date()}..{buys['disclosure_date'].max().date()})")

    # ---- TEST 1: clustering ----
    events, cluster_keys = detect_clusters(buys)
    ev_rows = []
    for e in events.itertuples(index=False):
        s = adj.get(e.ticker)
        rec = {"ticker": e.ticker, "date": e.complete_date, "year": pd.Timestamp(e.complete_date).year}
        for h in (21, 63):
            st = fwd(s, sessions, e.complete_date, h); mk = fwd(spy, sessions, e.complete_date, h)
            rec[f"adj{h}"] = (st - mk) if (st is not None and mk is not None) else None
        ev_rows.append(rec)
    ev = pd.DataFrame(ev_rows)
    buys["is_cluster"] = [(r.ticker, r.disclosure_date, r.member) in cluster_keys
                          for r in buys.itertuples(index=False)]
    isolated = buys[~buys["is_cluster"]]

    def period(y):
        return "P1" if P1[0] <= y <= P1[1] else ("P2" if P2[0] <= y <= P2[1] else "other")
    test1 = {"cluster_event_count": int(len(ev)),
             "cluster_entry_adj21": _stat(ev["adj21"]) if len(ev) else {},
             "cluster_entry_adj63": _stat(ev["adj63"]) if len(ev) else {},
             "isolated_adj21": _stat(isolated["adj21"]), "isolated_adj63": _stat(isolated["adj63"]),
             "by_period": {}}
    if len(ev):
        ev["period"] = ev["year"].map(period)
        for p in ("P1", "P2"):
            sub = ev[ev["period"] == p]
            test1["by_period"][p] = {"n": int(len(sub)), "adj63": _stat(sub["adj63"]) if len(sub) else {}}

    # ---- TEST 2: member persistence ----
    buys["period"] = buys["year"].map(period)
    tot = buys.groupby("member").size()
    p1c = buys[buys.period == "P1"].groupby("member").size()
    p2c = buys[buys.period == "P2"].groupby("member").size()
    qualified = [m for m in tot.index if tot[m] >= MIN_BUYS_TOTAL
                 and p1c.get(m, 0) >= MIN_PER_PERIOD and p2c.get(m, 0) >= MIN_PER_PERIOD]
    perf = []
    for m in qualified:
        p1v = buys[(buys.member == m) & (buys.period == "P1")]["adj63"].dropna()
        p2v = buys[(buys.member == m) & (buys.period == "P2")]["adj63"].dropna()
        if len(p1v) >= MIN_PER_PERIOD and len(p2v) >= MIN_PER_PERIOD:
            perf.append({"member": m, "p1": float(p1v.mean()), "p2": float(p2v.mean()),
                         "n1": int(len(p1v)), "n2": int(len(p2v))})
    pf = pd.DataFrame(perf)
    test2 = {"n_qualified": int(len(pf))}
    if len(pf) >= 5:
        rho, pval = stats.spearmanr(pf["p1"], pf["p2"])
        q = pf["p1"].quantile(0.8)
        top = pf[pf["p1"] >= q]; rest = pf[pf["p1"] < q]
        test2.update(rank_corr_p1_p2=float(rho), rank_corr_pval=float(pval),
                     top_quintile_p2_mean=float(top["p2"].mean()), rest_p2_mean=float(rest["p2"].mean()),
                     top_quintile_p2_minus_rest=float(top["p2"].mean() - rest["p2"].mean()),
                     n_top=int(len(top)))

    out = {"dev_buys": int(len(buys)), "test1": test1, "test2": test2}
    (cache.root / "congress" / "phase_a_v3_summary.json").write_text(json.dumps(out, indent=2, default=str))
    _report(REPO / "reports" / "congress_phase_a_v3.md", out)
    print("TEST1 clusters:", test1["cluster_event_count"],
          "cluster63:", test1.get("cluster_entry_adj63"), "isolated63:", test1["isolated_adj63"])
    print("TEST2:", test2)
    print("Wrote reports/congress_phase_a_v3.md")


def _p(x):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x*100:+.2f}%"


def _n(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:.{nd}f}"


def _report(path, o):
    t1, t2 = o["test1"], o["test2"]
    L = ["# Congress Phase A v3 — clustering + member persistence (market-adjusted, dev only)\n"]
    L.append("> **Exploratory, in-sample, DEV ≤2022; 2023+ hold-out SEALED (D9/D21).** Entry = disclosure "
             "date; buys; market-adjusted (−SPY). **Arena #3 + multiple sub-tests — heavy multiple-"
             "comparisons risk; nothing here is a result without OOS.**\n")
    L.append(f"Dev equity buys with realized forward returns: **{o['dev_buys']:,}**.\n")

    L.append("## TEST 1 — Clustering (≥3 distinct members, same ticker, 30-day window; entry = completing disclosure)\n")
    L.append(f"- **Cluster-event count: {t1['cluster_event_count']}.** "
             + ("**Too few to be statistically meaningful — this test is underpowered, which is itself the "
                "finding.** Numbers below are noise-dominated.\n" if t1["cluster_event_count"] < 50
                else "Enough events for a descriptive read.\n"))
    if t1["cluster_event_count"]:
        c21, c63 = t1["cluster_entry_adj21"], t1["cluster_entry_adj63"]
        i21, i63 = t1["isolated_adj21"], t1["isolated_adj63"]
        L.append("| Group | adj 21d mean (med) | adj 63d mean (med, t) | n(63d) |")
        L.append("|---|---|---|---|")
        L.append(f"| **Cluster** (entry=completing) | {_p(c21.get('mean'))} ({_p(c21.get('median'))}) "
                 f"| {_p(c63.get('mean'))} ({_p(c63.get('median'))}, t {_n(c63.get('t'))}) | {c63.get('n')} |")
        L.append(f"| Isolated buys | {_p(i21['mean'])} ({_p(i21['median'])}) "
                 f"| {_p(i63['mean'])} ({_p(i63['median'])}, t {_n(i63['t'])}) | {i63['n']} |")
        prem = (c63.get("mean") or 0) - (i63["mean"] or 0)
        L.append(f"\n- Cluster premium (63d adj, cluster − isolated): **{_p(prem)}**.")
        L.append("- By sub-period (cluster 63d adj): " + ", ".join(
            f"{p}: {_p(v['adj63'].get('mean'))} (n={v['n']})" for p, v in t1["by_period"].items()) + ".\n")

    L.append("## TEST 2 — Member persistence (P1 2014-18 → P2 2019-22; NOT a leaderboard)\n")
    L.append(f"- **Members clearing ≥{MIN_BUYS_TOTAL} buys + ≥{MIN_PER_PERIOD}/period: {t2['n_qualified']}** "
             "(the effective sample).")
    if "rank_corr_p1_p2" in t2:
        L.append(f"- **P1↔P2 rank correlation of per-member market-adjusted 63d return: "
                 f"{_n(t2['rank_corr_p1_p2'])}** (p={_n(t2['rank_corr_pval'])}). "
                 "≈0 ⇒ a member's P1 performance does NOT predict P2 — selection noise.")
        L.append(f"- **P1 top-quintile members' P2 return: {_p(t2['top_quintile_p2_mean'])}** vs rest "
                 f"{_p(t2['rest_p2_mean'])} (diff {_p(t2['top_quintile_p2_minus_rest'])}, n_top={t2['n_top']}). "
                 "If the top-P1 members don't beat the rest in P2, following them is not a real edge.\n")
    else:
        L.append(f"- Too few qualifying members ({t2['n_qualified']}) for a persistence test — "
                 "**underpowered; that is the finding.**\n")

    # verdict
    L.append("## Verdict\n")
    c63m = t1.get("cluster_entry_adj63", {}).get("mean")
    c63t = t1.get("cluster_entry_adj63", {}).get("t")
    cluster_real = (t1["cluster_event_count"] >= 50 and c63m is not None and c63m > 0.005
                    and c63t is not None and abs(c63t) >= 2)
    corr = t2.get("rank_corr_p1_p2")
    topdiff = t2.get("top_quintile_p2_minus_rest")
    persist_real = (corr is not None and corr > 0.3 and t2.get("rank_corr_pval", 1) < 0.05
                    and topdiff is not None and topdiff > 0.005)
    if not cluster_real:
        L.append("- **Test 1 (clustering): no usable cluster edge.** "
                 + (f"Only {t1['cluster_event_count']} cluster events (underpowered)." if t1["cluster_event_count"] < 50
                    else f"Cluster 63d market-adjusted return {_p(c63m)} (t {_n(c63t)}) is not a significant, "
                    "material premium over isolated buys.") + " No case for a hold-out test.\n")
    else:
        L.append(f"- **Test 1: a cluster premium appears in dev** ({_p(c63m)}/63d, t {_n(c63t)}, "
                 f"{t1['cluster_event_count']} events). Hypothesis for the sealed hold-out — with heavy "
                 "multiple-comparisons suspicion.\n")
    if not persist_real:
        L.append("- **Test 2 (member persistence): does NOT persist.** "
                 + (f"Only {t2['n_qualified']} qualifying members (underpowered)." if "rank_corr_p1_p2" not in t2
                    else f"P1↔P2 rank corr {_n(corr)}, top-P1 minus rest in P2 {_p(topdiff)} — a member's past "
                    "market-adjusted performance does not predict the future. **Individual-member 'edge' is "
                    "selection noise; no one worth following.**") + "\n")
    else:
        L.append(f"- **Test 2: member performance persists** (rank corr {_n(corr)}, top-P1 beat rest by "
                 f"{_p(topdiff)} in P2). Only now would a 'follow top-N-from-dev' rule get one sealed-"
                 "hold-out test (with approval).\n")
    L.append("\n- **Multiple-comparisons frame:** arena #3, and within it clustering + persistence + "
             "sub-period + owner slices. Even a nominally significant dev result here is a weak prior "
             "given how many things have been tried across the program.\n")
    L.append("\n> **STOP for review. 2023+ hold-out untouched.** A sealed-hold-out test happens only if a "
             "dev result genuinely warrants it and you approve.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
