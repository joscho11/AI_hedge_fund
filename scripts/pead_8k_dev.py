"""PEAD entry refinement (D23): entry = T+1 after the 8-K earnings announcement (EVENTS code 22),
excluding the un-tradeable announcement-day jump. Everything else carried from D22. Dev only; 2025+
sealed. Reports announcement coverage + announcement→datekey gap, and the 8-K vs 10-Q diagnostic
side by side across the cost sweep with net-by-year consistency. STOP for review.
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
from src.utils.calendars import offset_trading_days, trading_sessions
from src.utils.config import load_config

REPO = Path(__file__).resolve().parents[1]
ARCH = REPO / "data_archive" / "sharadar_parquet"
DEV_END = "2024-12-31"
WINDOW, STD_WIN, STD_MIN = 63, 8, 6
COSTS = [25.0, 30.0, 50.0, 100.0]
MATCH_BUFFER = 7   # days: announcement in (calendardate, datekey + 7d]


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
    if pos + h >= len(sessions) or sessions[pos] > last:
        return None
    p0 = adj.asof(sessions[pos])
    if pd.isna(p0) or p0 <= 0:
        return None
    t = sessions[pos + h]
    p1 = adj.asof(t) if t <= last else (adj.loc[:last].iloc[-1] if last < sessions[-1] else np.nan)
    return None if pd.isna(p1) else float(p1 / p0 - 1.0)


def build_sue(cache):
    sf1 = cache.get("sharadar", "SF1")
    q = sf1[(sf1["dimension"] == "ARQ") & sf1["eps"].notna()][["ticker", "calendardate", "datekey", "eps"]].copy()
    q["calendardate"] = pd.to_datetime(q["calendardate"]); q["datekey"] = pd.to_datetime(q["datekey"])
    q = q.sort_values(["ticker", "calendardate", "datekey"]).drop_duplicates(["ticker", "calendardate"], keep="first")
    out = []
    for tk, g in q.groupby("ticker"):
        g = g.sort_values("calendardate")
        if len(g) < STD_MIN + 4:
            continue
        deps = g["eps"].values - np.concatenate([[np.nan] * 4, g["eps"].values[:-4]])
        dser = pd.Series(deps, index=g.index)
        sue = dser / dser.rolling(STD_WIN, min_periods=STD_MIN).std()
        out.append(g.assign(sue=sue.values)[["ticker", "calendardate", "datekey", "eps", "sue"]])
    return pd.concat(out, ignore_index=True).dropna(subset=["sue"])


def announcement_dates(cache):
    ev = pd.read_parquet(ARCH / "EVENTS.parquet")
    ev = ev[ev["eventcodes"].astype(str).str.split("|").apply(lambda xs: "22" in xs)]
    ev["date"] = pd.to_datetime(ev["date"])
    return {tk: np.array(sorted(g["date"].values)) for tk, g in ev.groupby("ticker")}


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    prior = json.loads((cache.root / "pead_dev_summary.json").read_text())  # D22 (10-Q) results

    sue = build_sue(cache)
    sue = sue[sue["datekey"] <= pd.Timestamp(DEV_END)]

    # small-cap universe filter (member at prior rebalance)
    mem = cache.get("universe", "smallcap_membership"); mem["date"] = pd.to_datetime(mem["date"])
    reb = pd.DatetimeIndex(sorted(mem["date"].unique()))
    memset = {d: set(g["ticker"]) for d, g in mem.groupby("date")}
    def in_uni(tk, dk):
        pos = reb.searchsorted(pd.Timestamp(dk), "right") - 1
        return pos >= 0 and tk in memset.get(reb[pos], set())
    sue = sue[[in_uni(r.ticker, r.datekey) for r in sue.itertuples(index=False)]].copy()
    n_universe = len(sue)

    # match to 8-K announcement: earliest code-22 date in (calendardate, datekey + buffer]
    ann = announcement_dates(cache)
    ann_dates, gaps = [], []
    for r in sue.itertuples(index=False):
        arr = ann.get(r.ticker)
        a = None
        if arr is not None and len(arr):
            lo = np.datetime64(r.calendardate); hi = np.datetime64(r.datekey + pd.Timedelta(days=MATCH_BUFFER))
            cand = arr[(arr > lo) & (arr <= hi)]
            if len(cand):
                a = pd.Timestamp(cand.min())
        ann_dates.append(a)
        gaps.append((r.datekey - a).days if a is not None else None)
    sue["ann_date"] = ann_dates
    sue["gap"] = gaps
    matched = sue.dropna(subset=["ann_date"]).copy()
    coverage = len(matched) / n_universe
    gap_s = pd.Series([g for g in gaps if g is not None])
    print(f"universe SUE events {n_universe:,}; matched to 8-K {len(matched):,} ({coverage*100:.0f}%)")
    print(f"announcement->datekey gap days: median {gap_s.median():.0f}, mean {gap_s.mean():.1f}, "
          f"p10 {gap_s.quantile(.1):.0f}, p90 {gap_s.quantile(.9):.0f}, %ann<datekey {(gap_s>0).mean()*100:.0f}")

    # prices
    tickers = matched["ticker"].unique().tolist()
    sep = pa_ds.dataset(str(cache.root / "sharadar" / "SEP.parquet"), format="parquet").to_table(
        columns=["ticker", "date", "closeadj"], filter=pa_ds.field("ticker").isin(tickers)).to_pandas()
    matched = matched[matched["ticker"].isin(set(sep["ticker"].unique()))].copy()
    adj = adj_series(sep)
    spy = adj_series(pa_ds.dataset(str(ARCH / "SFP.parquet"), format="parquet").to_table(
        columns=["ticker", "date", "closeadj"], filter=pa_ds.field("ticker") == "SPY").to_pandas()).get("SPY")
    sessions = trading_sessions(cfg.dates.start, str(pd.to_datetime(sep["date"]).max().date()), cfg.calendar.exchange)

    # forward market-adjusted returns from T+1 after announcement (exclude the jump)
    recs = []
    for r in matched.itertuples(index=False):
        entry = offset_trading_days(r.ann_date, 1, cfg.calendar.exchange)   # T+1
        st = fwd(adj.get(r.ticker), sessions, entry, WINDOW)
        if st is None:
            continue
        mk = fwd(spy, sessions, entry, WINDOW)
        recs.append({"ticker": r.ticker, "year": pd.Timestamp(r.ann_date).year,
                     "cohort": pd.Timestamp(r.ann_date).to_period("M").strftime("%Y-%m"),
                     "sue": r.sue, "raw": st, "adj": (st - mk) if mk is not None else None})
    ev = pd.DataFrame(recs).dropna(subset=["adj"])
    ev["cr"] = ev.groupby("cohort")["sue"].rank(pct=True)

    # IC per monthly cohort
    ic = {}
    for c, g in ev.groupby("cohort"):
        s = g[["sue", "adj"]].dropna()
        if len(s) >= 10 and s["sue"].nunique() > 1:
            ic[c] = stats.spearmanr(s["sue"], s["adj"]).correlation
    ics = pd.Series(ic).dropna()

    # deciles (avg across cohorts)
    def dec(g):
        g = g.dropna(subset=["sue", "adj"])
        if len(g) < 10:
            return None
        return g.assign(d=pd.qcut(g["sue"].rank(method="first"), 10, labels=False, duplicates="drop")).groupby("d")["adj"].mean()
    D = pd.concat([d for _, grp in ev.groupby("cohort") if (d := dec(grp)) is not None], axis=1).mean(axis=1)
    topd, botd = float(D.iloc[-1]), float(D.iloc[0])

    def net(x, c):
        return x - 2 * (c / 1e4)
    top = ev[ev["cr"] >= 0.9]["adj"]
    sweep = {f"{c}": {"top_net": net(float(top.mean()), c), "ls_net": net(topd - botd, c)} for c in COSTS}
    by_year = {}
    for y, g in ev.groupby("year"):
        t = g[g.groupby("cohort")["sue"].rank(pct=True) >= 0.9]["adj"]
        if len(t) >= 20:
            by_year[int(y)] = {"n": int(len(t)), "gross": float(t.mean()), "net50": net(float(t.mean()), 50.0)}

    n = len(ics)
    out = {
        "coverage": coverage, "n_universe": int(n_universe), "n_matched": int(len(matched)),
        "gap": {"median": float(gap_s.median()), "mean": float(gap_s.mean()),
                "p10": float(gap_s.quantile(.1)), "p90": float(gap_s.quantile(.9)),
                "pct_ann_before_datekey": float((gap_s > 0).mean())},
        "events_realized": int(len(ev)),
        "ic": {"n": int(n), "mean": float(ics.mean()), "ic_ir": float(ics.mean()/ics.std(ddof=1)) if n > 1 else None,
               "t": float(ics.mean()/(ics.std(ddof=1)/np.sqrt(n))) if n > 1 else None, "pct_pos": float((ics > 0).mean())},
        "top_gross": topd, "bottom_gross": botd, "ls_gross": topd - botd,
        "cost_sweep": sweep, "by_year": by_year,
        "prior_10q": {"ic_mean": prior["ic"]["mean"], "ic_t": prior["ic"]["t"],
                      "top_gross": prior["top_gross"], "top_net50": prior["cost_sweep"]["50.0"]["top_decile_net_mean"],
                      "ls_gross": prior["long_short_gross"], "ls_net50": prior["cost_sweep"]["50.0"]["long_short_net"]},
    }
    (cache.root / "pead_8k_dev_summary.json").write_text(json.dumps(out, indent=2, default=str))
    _report(REPO / "reports" / "pead_8k_dev.md", out)
    print("8K IC:", {k: round(v, 4) if isinstance(v, float) else v for k, v in out["ic"].items()})
    print("8K top-decile net by cost:", {c: round(v["top_net"], 4) for c, v in sweep.items()})
    print("net-by-year @50 positive years:", sum(1 for v in by_year.values() if v["net50"] > 0), "/", len(by_year))
    print("Wrote reports/pead_8k_dev.md")


def _p(x):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x*100:+.2f}%"


def _n(x, nd=3):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:.{nd}f}"


def _report(path, o):
    ic, pr = o["ic"], o["prior_10q"]
    L = ["# PEAD — 8-K T+1 entry (dev), vs 10-Q entry (D23)\n"]
    L.append("> **Exploratory, in-sample, DEV ≤2024; 2025+ SEALED.** Entry = **next session after the 8-K "
             "earnings announcement (T+1)** — the announcement-day jump is EXCLUDED. Same SUE / 63d / "
             "small-cap universe / market-adjust / round-trip cost sweep + ≥50 bps bar as D22. **Arena #4, "
             "2nd entry swing → discount any positive.**\n")

    L.append("## Announcement coverage + announcement→10-Q gap\n")
    g = o["gap"]
    L.append(f"- **{o['n_matched']:,} of {o['n_universe']:,} ({o['coverage']*100:.0f}%)** small-cap SUE "
             "events have a clean EVENTS code-22 announcement date; unmatched events EXCLUDED (no fallback).")
    L.append(f"- Announcement→`datekey` gap: median **{g['median']:.0f}d**, mean {g['mean']:.1f}d "
             f"(p10 {g['p10']:.0f}, p90 {g['p90']:.0f}); **{g['pct_ann_before_datekey']*100:.0f}%** of "
             "announcements precede the 10-Q datekey (as expected — that gap is the drift D22 missed).\n")

    L.append("## Diagnostic — 8-K T+1 entry vs 10-Q datekey entry\n")
    L.append("| Metric | 10-Q entry (D22) | **8-K T+1 entry (D23)** |")
    L.append("|---|---|---|")
    L.append(f"| SUE IC mean (t) | {_n(pr['ic_mean'],4)} ({_n(pr['ic_t'],2)}) | **{_n(ic['mean'],4)}** ({_n(ic['t'],2)}) |")
    L.append(f"| IC % positive months | — | {_p(ic['pct_pos'])} |")
    L.append(f"| Top-decile GROSS (adj 63d) | {_p(pr['top_gross'])} | **{_p(o['top_gross'])}** |")
    L.append(f"| Top-decile NET @50bps | {_p(pr['top_net50'])} | **{_p(o['cost_sweep']['50.0']['top_net'])}** |")
    L.append(f"| Long-short GROSS | {_p(pr['ls_gross'])} | {_p(o['ls_gross'])} |")
    L.append(f"| Long-short NET @50bps | {_p(pr['ls_net50'])} | {_p(o['cost_sweep']['50.0']['ls_net'])} |")

    L.append("\n## Cost sweep (round-trip), 8-K T+1 entry\n")
    L.append("| One-way cost | Top-decile net | Long-short net |\n|---|---|---|")
    for c in ("25.0", "30.0", "50.0", "100.0"):
        s = o["cost_sweep"][c]
        L.append(f"| {c} bps | {_p(s['top_net'])} | {_p(s['ls_net'])} |")

    L.append("\n## Net-by-year @50bps (CONSISTENCY is required, not just magnitude)\n")
    L.append("| Year | top-decile gross | net @50bps | n |\n|---|---|---|---|")
    posyr = 0
    for y, v in o["by_year"].items():
        posyr += v["net50"] > 0
        L.append(f"| {y} | {_p(v['gross'])} | {_p(v['net50'])} | {v['n']} |")
    nyr = len(o["by_year"])

    # verdict
    net50 = o["cost_sweep"]["50.0"]["top_net"]
    lifted = o["top_gross"] - pr["top_gross"]
    consistent = nyr and (posyr / nyr) >= 0.6
    survives = net50 is not None and net50 > 0.003 and (ic["t"] or 0) >= 2 and ic["pct_pos"] >= 0.6 and consistent
    L.append("\n## Verdict\n")
    L.append(f"- Earlier (8-K T+1) entry {'RAISES' if lifted > 0 else 'does NOT raise'} the gross drift "
             f"(top-decile {_p(pr['top_gross'])} → {_p(o['top_gross'])}, Δ {_p(lifted)}).")
    if survives:
        L.append(f"- **PEAD now clears ≥50 bps AND holds across sub-periods** (top-decile net @50bps "
                 f"{_p(net50)}, IC t {_n(ic['t'],2)}, {_p(ic['pct_pos'])} months +, "
                 f"{posyr}/{nyr} years net-positive). The strongest dev result of the program — a "
                 "candidate worth the sealed 2025+ hold-out, **discounted for arena #4 / 2nd swing**.\n")
    else:
        why = []
        if not (net50 is not None and net50 > 0.003):
            why.append(f"top-decile net @50bps is {_p(net50)} (fails the bar)")
        if not consistent:
            why.append(f"net-by-year is inconsistent ({posyr}/{nyr} years positive)")
        if ic["pct_pos"] < 0.6 or (ic["t"] or 0) < 2:
            why.append(f"IC is weak (t {_n(ic['t'],2)}, {_p(ic['pct_pos'])} months +)")
        L.append("- **Still does NOT clear the bar (or not consistently): " + "; ".join(why) + ".** "
                 "Even entering right after the announcement (jump excluded), the tradeable residual drift "
                 "is too small / too regime-dependent to beat honest ≥50 bps small-cap costs. The anomaly is "
                 "real but not tradeable here. **No case for spending the sealed hold-out.**\n")
    L.append("- **Multiple-comparisons discount:** arena #4, 2nd entry-timing swing at PEAD — any nominal "
             "positive is a weak prior; only the sealed 2025+ hold-out could settle it.\n")
    L.append("\n> **STOP for review. 2025+ hold-out untouched.**\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
