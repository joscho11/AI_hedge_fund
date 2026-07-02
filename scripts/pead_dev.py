"""PEAD (post-earnings-announcement drift) — small-cap dev diagnostic. Pre-registered D22.
SUE from first-reported ARQ eps (seasonal random walk), entry = SF1 datekey (PIT-clean), 60-day drift,
market-adjusted (−SPY), delisting-aware, net of the {25,30,50,100} bps round-trip cost sweep (≥50bps
bar). Development only (datekey ≤ 2024-12-31); 2025+ hold-out SEALED. Descriptive/in-sample; STOP.
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
from src.utils.calendars import month_end_rebalance_dates, trading_sessions
from src.utils.config import load_config

REPO = Path(__file__).resolve().parents[1]
ARCHIVE_SFP = REPO / "data_archive" / "sharadar_parquet" / "SFP.parquet"
DEV_END = "2024-12-31"
WINDOW = 63          # ~60 trading-day drift window (quarter)
STD_WIN, STD_MIN = 8, 6
COSTS = [25.0, 30.0, 50.0, 100.0]


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
    q = sf1[(sf1["dimension"] == "ARQ") & sf1["eps"].notna()][
        ["ticker", "calendardate", "datekey", "eps"]].copy()
    q["calendardate"] = pd.to_datetime(q["calendardate"]); q["datekey"] = pd.to_datetime(q["datekey"])
    # first-reported eps per (ticker, period): earliest datekey
    q = q.sort_values(["ticker", "calendardate", "datekey"]).drop_duplicates(["ticker", "calendardate"], keep="first")
    out = []
    for tk, g in q.groupby("ticker"):
        g = g.sort_values("calendardate")
        if len(g) < STD_MIN + 4:
            continue
        deps = g["eps"].values - np.concatenate([[np.nan] * 4, g["eps"].values[:-4]])
        dser = pd.Series(deps, index=g.index)
        sd = dser.rolling(STD_WIN, min_periods=STD_MIN).std()
        sue = dser / sd
        gg = g.copy(); gg["sue"] = sue.values
        out.append(gg[["ticker", "calendardate", "datekey", "eps", "sue"]])
    return pd.concat(out, ignore_index=True).dropna(subset=["sue"])


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)

    sue = build_sue(cache)
    sue = sue[sue["datekey"] <= pd.Timestamp(DEV_END)]        # DEV ONLY
    print(f"SUE firm-quarters (dev): {len(sue):,}")

    # small-cap universe membership at the rebalance on/before entry datekey
    mem = cache.get("universe", "smallcap_membership")
    mem["date"] = pd.to_datetime(mem["date"])
    reb = pd.DatetimeIndex(sorted(mem["date"].unique()))
    memset = {d: set(g["ticker"]) for d, g in mem.groupby("date")}

    def in_universe(tk, dk):
        pos = reb.searchsorted(pd.Timestamp(dk), "right") - 1
        return pos >= 0 and tk in memset.get(reb[pos], set())

    sue = sue[[in_universe(r.ticker, r.datekey) for r in sue.itertuples(index=False)]].copy()
    print(f"SUE events in small-cap universe (dev): {len(sue):,}")

    # prices
    tickers = sue["ticker"].unique().tolist()
    sep = pa_ds.dataset(str(cache.root / "sharadar" / "SEP.parquet"), format="parquet").to_table(
        columns=["ticker", "date", "closeadj"], filter=pa_ds.field("ticker").isin(tickers)).to_pandas()
    sue = sue[sue["ticker"].isin(set(sep["ticker"].unique()))].copy()
    adj = adj_series(sep)
    spy = adj_series(pa_ds.dataset(str(ARCHIVE_SFP), format="parquet").to_table(
        columns=["ticker", "date", "closeadj"], filter=pa_ds.field("ticker") == "SPY").to_pandas()).get("SPY")
    sessions = trading_sessions(cfg.dates.start, str(pd.to_datetime(sep["date"]).max().date()), cfg.calendar.exchange)

    # forward market-adjusted returns from entry (datekey)
    recs = []
    for r in sue.itertuples(index=False):
        st = fwd(adj.get(r.ticker), sessions, r.datekey, WINDOW)
        if st is None:
            continue
        mk = fwd(spy, sessions, r.datekey, WINDOW)
        recs.append({"ticker": r.ticker, "datekey": r.datekey, "year": r.datekey.year,
                     "cohort": r.datekey.to_period("M").strftime("%Y-%m"), "sue": r.sue,
                     "raw": st, "adj": (st - mk) if mk is not None else None})
    ev = pd.DataFrame(recs).dropna(subset=["adj"])
    ev["cohort_rank"] = ev.groupby("cohort")["sue"].rank(pct=True)
    print(f"events with realized 63d return: {len(ev):,}")

    # ---- IC (per monthly cohort) ----
    ic = {}
    for c, g in ev.groupby("cohort"):
        s = g[["sue", "adj"]].dropna()
        if len(s) >= 10 and s["sue"].nunique() > 1:
            ic[c] = stats.spearmanr(s["sue"], s["adj"]).correlation
    ics = pd.Series(ic).dropna()
    ic_by_year = ev.assign(m=ev["cohort"]).groupby("year").apply(
        lambda g: stats.spearmanr(g["sue"], g["adj"]).correlation if len(g) >= 20 and g["sue"].nunique() > 1 else np.nan)

    # ---- deciles (per cohort) ----
    def decile(g):
        g = g.dropna(subset=["sue", "adj"])
        if len(g) < 10:
            return None
        q = pd.qcut(g["sue"].rank(method="first"), 10, labels=False, duplicates="drop")
        return g.assign(dec=q).groupby("dec")["adj"].mean()
    dec = pd.concat([d for _, grp in ev.groupby("cohort") if (d := decile(grp)) is not None], axis=1)
    dec_mean = dec.mean(axis=1)  # avg market-adjusted 63d return per decile (gross)
    topd, botd = float(dec_mean.iloc[-1]), float(dec_mean.iloc[0])

    # ---- cost sweep (round-trip) ----
    def net(x, c):
        return x - 2 * (c / 1e4)
    top = ev[ev["cohort_rank"] >= 0.9]["adj"]
    ls_gross = topd - botd
    sweep = {f"{c}": {"top_decile_net_mean": net(float(top.mean()), c),
                      "long_short_net": net(ls_gross, c)} for c in COSTS}

    # by year: top-decile net at 50bps
    by_year = {}
    for y, g in ev.groupby("year"):
        t = g[g.groupby("cohort")["sue"].rank(pct=True) >= 0.9]["adj"]
        if len(t) >= 20:
            by_year[int(y)] = {"n": int(len(t)), "top_net50": net(float(t.mean()), 50.0),
                               "top_gross": float(t.mean())}

    n = len(ics)
    out = {
        "sue_events_dev": int(len(sue)), "events_realized": int(len(ev)),
        "ic": {"n_cohorts": int(n), "mean": float(ics.mean()), "std": float(ics.std(ddof=1)),
               "ic_ir": float(ics.mean() / ics.std(ddof=1)) if n > 1 else None,
               "t": float(ics.mean() / (ics.std(ddof=1) / np.sqrt(n))) if n > 1 else None,
               "pct_pos": float((ics > 0).mean())},
        "ic_by_year": {int(y): (float(v) if pd.notna(v) else None) for y, v in ic_by_year.items()},
        "decile_gross_adj": {int(k): float(v) for k, v in dec_mean.items()},
        "top_gross": topd, "bottom_gross": botd, "long_short_gross": ls_gross,
        "cost_sweep": sweep, "by_year": by_year,
        "turnover_note": "PEAD holds ~63d per event → ~1 round-trip per position (near-full turnover); "
                         "round-trip cost = 2× one-way is charged.",
    }
    (cache.root / "congress" / "pead_dev_summary.json").parent.mkdir(parents=True, exist_ok=True)
    (cache.root / "pead_dev_summary.json").write_text(json.dumps(out, indent=2, default=str))
    _report(REPO / "reports" / "pead_dev.md", out)
    print("IC:", {k: round(v, 4) if isinstance(v, float) else v for k, v in out["ic"].items()})
    print("top-decile net mean by cost:", {c: round(v["top_decile_net_mean"], 4) for c, v in sweep.items()})
    print("Wrote reports/pead_dev.md")


def _p(x):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x*100:+.2f}%"


def _n(x, nd=3):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:.{nd}f}"


def _report(path, o):
    ic = o["ic"]
    L = ["# PEAD (small-cap) — development diagnostic (market-adjusted, cost-swept)\n"]
    L.append("> **Exploratory, in-sample, DEV ≤2024; 2025+ hold-out SEALED (D22).** SUE = seasonal-"
             "random-walk (no estimates); entry = SF1 datekey (PIT-clean; misses the initial post-8-K "
             "reaction, so a HARD test); 63-day drift; market-adjusted (−SPY); costs charged ROUND-TRIP; "
             "**≥50 bps bar.** Arena #4 — multiple-comparisons caution.\n")
    L.append(f"- **Event count:** {o['sue_events_dev']:,} small-cap SUE firm-quarters in dev; "
             f"**{o['events_realized']:,}** with a realized 63d return. {o['turnover_note']}\n")

    L.append("## IC — does SUE rank predict forward market-adjusted return?\n")
    L.append(f"- Mean IC **{_n(ic['mean'],4)}**, IC-IR (monthly) {_n(ic['ic_ir'])}, t {_n(ic['t'],2)}, "
             f"**% positive months {_p(ic['pct_pos'])}** (n={ic['n_cohorts']} cohorts). "
             "(D17: weight %-positive, don't be fooled by IC-IR.)\n")
    yrs = o["ic_by_year"]
    pos_y = sum(1 for v in yrs.values() if v and v > 0)
    L.append(f"- IC by year positive in **{pos_y}/{len([v for v in yrs.values() if v is not None])}** years. "
             "By year: " + ", ".join(f"{y}:{_n(v,3)}" for y, v in yrs.items() if v is not None) + ".\n")

    L.append("## Decile spread — market-adjusted 63d return by SUE decile (gross)\n")
    dm = o["decile_gross_adj"]
    L.append("  " + " ".join(f"D{k}:{_p(v)}" for k, v in sorted(dm.items())))
    L.append(f"\n- Top−bottom (gross, market-adj): **{_p(o['long_short_gross'])}**; top decile "
             f"{_p(o['top_gross'])}, bottom {_p(o['bottom_gross'])}.\n")

    L.append("## Cost sweep (round-trip) — does the edge survive ≥50 bps?\n")
    L.append("| One-way cost | Top-decile net (market-adj 63d) | Long-short net |")
    L.append("|---|---|---|")
    for c in ("25.0", "30.0", "50.0", "100.0"):
        s = o["cost_sweep"][c]
        L.append(f"| {c} bps | {_p(s['top_decile_net_mean'])} | {_p(s['long_short_net'])} |")
    L.append("\n*The **50 bps** row is the bar. Round-trip cost at 50 bps one-way = 100 bps ≈ "
             "1.0% subtracted per event.*\n")

    L.append("## By year — top-decile net @50 bps (regime check)\n")
    L.append("| Year | top-decile gross (adj) | net @50bps | n |\n|---|---|---|---|")
    for y, v in o["by_year"].items():
        L.append(f"| {y} | {_p(v['top_gross'])} | {_p(v['top_net50'])} | {v['n']} |")

    # verdict
    net50 = o["cost_sweep"]["50.0"]["top_decile_net_mean"]
    ls50 = o["cost_sweep"]["50.0"]["long_short_net"]
    ic_ok = ic["mean"] > 0.02 and (ic["t"] or 0) >= 2 and ic["pct_pos"] >= 0.6
    survives = net50 is not None and net50 > 0.003 and ic_ok
    L.append("\n## Verdict\n")
    if survives:
        L.append(f"- **PEAD appears to survive ≥50 bps in dev:** SUE IC {_n(ic['mean'],4)} "
                 f"(t {_n(ic['t'],2)}, {_p(ic['pct_pos'])} months +), top-decile net @50bps "
                 f"{_p(net50)} (>0). A hypothesis worth the sealed hold-out — with multiple-comparisons "
                 "suspicion (arena #4).\n")
    else:
        L.append(f"- **PEAD does NOT clear the ≥50 bps bar in dev.** SUE IC is "
                 f"{_n(ic['mean'],4)} (t {_n(ic['t'],2)}, {_p(ic['pct_pos'])} months positive); after "
                 f"round-trip costs the top decile is **{_p(net50)} net @50bps** (long-short {_p(ls50)}). "
                 "Even where a gross drift exists, high earnings-season turnover + honest small-cap costs "
                 "eat it — the same force that killed momentum (Phase 5). Also, datekey entry misses the "
                 "early post-8-K reaction, so the residual drift is small by construction. **No case for "
                 "spending the sealed hold-out.**\n")
    L.append("- **Caveats:** entry at 10-Q datekey is conservative (misses initial reaction); SUE is one "
             "frozen definition; arena #4 with IC/decile/by-year slices — heavy multiple-comparisons.\n")
    L.append("\n> **STOP for review. 2025+ hold-out untouched.**\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
