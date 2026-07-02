"""Insider cluster buying (SF2) — small-cap dev diagnostic. Pre-registered D24.
Open-market purchases only (code P), cluster = >=2 distinct insiders / 30 filing days / >=$50k, entry =
completing filing T+1 (lookahead-guarded), 126d hold (63d ctx), market-adjusted (-SPY), delisting-aware,
net of {25,30,50,100} bps round-trip sweep (>=50 bps bar). DEV filingdate<=2024; 2025+ SEALED. STOP.
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
WIN_PRIMARY, WIN_CTX = 126, 63
CLUSTER_N, CLUSTER_DAYS, MIN_VALUE = 2, 30, 50_000
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


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)

    sf2 = pd.read_parquet(ARCH / "SF2.parquet",
                          columns=["ticker", "filingdate", "transactiondate", "ownername",
                                   "transactioncode", "transactionvalue", "isofficer", "isdirector"])
    comp = sf2["transactioncode"].value_counts().head(8).to_dict()
    p = sf2[sf2["transactioncode"] == "P"].copy()
    p["ticker"] = p["ticker"].astype("string").str.upper().str.strip()
    p["filingdate"] = pd.to_datetime(p["filingdate"], errors="coerce")
    p["transactiondate"] = pd.to_datetime(p["transactiondate"], errors="coerce")
    p["transactionvalue"] = pd.to_numeric(p["transactionvalue"], errors="coerce").abs()
    p = p.dropna(subset=["filingdate", "ticker", "ownername"])
    p = p[p["filingdate"] <= pd.Timestamp(DEV_END)]
    lag = (p["filingdate"] - p["transactiondate"]).dt.days
    lag = lag[lag.between(0, 60)]

    # small-cap universe filter at filing
    mem = cache.get("universe", "smallcap_membership"); mem["date"] = pd.to_datetime(mem["date"])
    reb = pd.DatetimeIndex(sorted(mem["date"].unique()))
    memset = {d: set(g["ticker"]) for d, g in mem.groupby("date")}
    def in_uni(tk, dk):
        pos = reb.searchsorted(pd.Timestamp(dk), "right") - 1
        return pos >= 0 and tk in memset.get(reb[pos], set())
    p = p[[in_uni(r.ticker, r.filingdate) for r in p.itertuples(index=False)]].copy()
    print(f"code-P small-cap buys (dev): {len(p):,}; distinct tickers {p['ticker'].nunique()}")

    # cluster detection (by filing date): >=N distinct owners within CLUSTER_DAYS and aggregate value>=MIN
    events, in_cluster_idx = [], set()
    for tk, g in p.sort_values("filingdate").groupby("ticker"):
        g = g.reset_index()
        win, fired = [], False
        for row in g.itertuples(index=False):
            t = row.filingdate
            win = [w for w in win if (t - w[0]).days <= CLUSTER_DAYS]
            win.append((t, row.ownername, row.transactionvalue, row.Index if hasattr(row, "Index") else None))
            distinct = len({w[1] for w in win})
            aggval = float(np.nansum([w[2] for w in win]))
            if distinct >= CLUSTER_N and aggval >= MIN_VALUE and not fired:
                events.append({"ticker": tk, "complete_filing": t, "n_insiders": distinct, "agg_value": aggval,
                               "any_officer": bool(g["isofficer"].astype(str).str.upper().isin(["Y", "TRUE", "1"]).any())})
                fired = True
            elif distinct < CLUSTER_N:
                fired = False
    ev = pd.DataFrame(events)
    print(f"CLUSTER EVENTS: {len(ev):,}")

    # prices
    tickers = p["ticker"].unique().tolist()
    sep = pa_ds.dataset(str(cache.root / "sharadar" / "SEP.parquet"), format="parquet").to_table(
        columns=["ticker", "date", "closeadj"], filter=pa_ds.field("ticker").isin(tickers)).to_pandas()
    adj = adj_series(sep)
    spy = adj_series(pa_ds.dataset(str(ARCH / "SFP.parquet"), format="parquet").to_table(
        columns=["ticker", "date", "closeadj"], filter=pa_ds.field("ticker") == "SPY").to_pandas()).get("SPY")
    sessions = trading_sessions(cfg.dates.start, str(pd.to_datetime(sep["date"]).max().date()), cfg.calendar.exchange)

    def ret_from(entry_date, ticker, h):
        e = offset_trading_days(entry_date, 1, cfg.calendar.exchange)   # T+1
        st = fwd(adj.get(ticker), sessions, e, h)
        if st is None:
            return None
        mk = fwd(spy, sessions, e, h)
        return (st - mk) if mk is not None else None

    # cluster-event returns (entry = completing filing T+1)
    cl = []
    for e in ev.itertuples(index=False):
        r126 = ret_from(e.complete_filing, e.ticker, WIN_PRIMARY)
        r63 = ret_from(e.complete_filing, e.ticker, WIN_CTX)
        if r126 is not None:
            cl.append({"ticker": e.ticker, "year": pd.Timestamp(e.complete_filing).year,
                       "any_officer": e.any_officer, "adj126": r126, "adj63": r63})
    cle = pd.DataFrame(cl)

    # single (lone) code-P buys: not part of any cluster window -> proxy: all P buys' returns as the
    # lone-buy baseline (each entered at its own filing T+1)
    ln = []
    for r in p.itertuples(index=False):
        r126 = ret_from(r.filingdate, r.ticker, WIN_PRIMARY)
        if r126 is not None:
            ln.append({"year": r.filingdate.year, "adj126": r126})
    lone = pd.DataFrame(ln)

    def stat(s):
        s = pd.Series(s).dropna()
        return {"n": int(len(s)), "mean": float(s.mean()) if len(s) else None,
                "median": float(s.median()) if len(s) else None,
                "t": float(stats.ttest_1samp(s, 0).statistic) if len(s) > 2 else None}

    def net(x, c):
        return None if x is None else x - 2 * (c / 1e4)

    cl126 = stat(cle["adj126"]) if len(cle) else {}
    sweep = {f"{c}": {"cluster_net126": net(cl126.get("mean"), c)} for c in COSTS}
    by_year = {}
    for y, g in (cle.groupby("year") if len(cle) else []):
        if len(g) >= 10:
            by_year[int(y)] = {"n": int(len(g)), "gross": float(g["adj126"].mean()),
                               "net50": net(float(g["adj126"].mean()), 50.0)}
    officer_split = {}
    if len(cle) and "any_officer" in cle:
        for k, g in cle.groupby("any_officer"):
            officer_split["officer" if k else "director_only"] = stat(g["adj126"])

    out = {
        "sf2_code_composition": {str(k): int(v) for k, v in comp.items()},
        "code_p_smallcap_dev": int(len(p)),
        "filing_lag": {"median": float(lag.median()), "mean": float(lag.mean()),
                       "p90": float(lag.quantile(.9)), "within_2d": float((lag <= 2).mean())},
        "cluster_events": int(len(ev)), "cluster_realized": int(len(cle)),
        "turnover_note": f"Hold {WIN_PRIMARY}td (~6 months) => ~2 round-trips/yr per name (LOW turnover); "
                         "round-trip cost 2x one-way charged once per event.",
        "cluster_adj126": cl126, "cluster_adj63": stat(cle["adj63"]) if len(cle) else {},
        "lone_adj126": stat(lone["adj126"]) if len(lone) else {},
        "cost_sweep": sweep, "by_year": by_year, "officer_split": officer_split,
    }
    (cache.root / "insider_cluster_dev_summary.json").write_text(json.dumps(out, indent=2, default=str))
    _report(REPO / "reports" / "insider_cluster_dev.md", out)
    print("filing lag median/within2d:", round(lag.median(), 1), round((lag <= 2).mean(), 2))
    print("cluster126:", cl126, "| lone126 mean:", out["lone_adj126"].get("mean"))
    print("cluster net126 by cost:", {c: (round(v["cluster_net126"], 4) if v["cluster_net126"] is not None else None) for c, v in sweep.items()})
    print("by-year net@50 positive:", sum(1 for v in by_year.values() if v["net50"] and v["net50"] > 0), "/", len(by_year))
    print("Wrote reports/insider_cluster_dev.md")


def _p(x):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x*100:+.2f}%"


def _n(x, nd=2):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:.{nd}f}"


def _report(path, o):
    cl, lo = o["cluster_adj126"], o["lone_adj126"]
    L = ["# Insider cluster buying (SF2, code P) — small-cap dev diagnostic\n"]
    L.append("> **Exploratory, in-sample, DEV ≤2024; 2025+ SEALED (D24).** Open-market purchases only "
             "(code P); cluster = ≥2 distinct insiders / 30 filing-days / ≥$50k; entry = completing "
             "filing **T+1** (lookahead-guarded); 126d hold; market-adjusted (−SPY); round-trip cost "
             "sweep, **≥50 bps bar**. **Arena #5 — discount any positive.**\n")
    L.append(f"- SF2 code composition (top): {o['sf2_code_composition']}. **Code-P is the pivot** (grants/"
             "exercises/tax/sales are comp mechanics, excluded).")
    L.append(f"- Code-P small-cap buys (dev): **{o['code_p_smallcap_dev']:,}**. Filing lag median "
             f"**{o['filing_lag']['median']:.0f}d**, {o['filing_lag']['within_2d']*100:.0f}% within 2 days "
             "(short, unlike Congress — the structural advantage).")
    L.append(f"- **CLUSTER EVENTS: {o['cluster_events']:,}** ({o['cluster_realized']:,} with a realized "
             f"126d return). {o['turnover_note']}")
    if o["cluster_events"] < 100:
        L.append("  - **⚠ Underpowered — too few cluster events for a confident read; that is itself part "
                 "of the finding.**")
    L.append("")

    L.append("## Does clustering add value? (market-adjusted 126d)\n")
    L.append("| Group | mean (median, t) | n |\n|---|---|---|")
    L.append(f"| **Cluster** (≥2 insiders, entry=completing filing) | {_p(cl.get('mean'))} "
             f"({_p(cl.get('median'))}, t {_n(cl.get('t'))}) | {cl.get('n')} |")
    L.append(f"| Lone code-P buys (baseline) | {_p(lo.get('mean'))} ({_p(lo.get('median'))}, t {_n(lo.get('t'))}) | {lo.get('n')} |")
    prem = (cl.get("mean") or 0) - (lo.get("mean") or 0)
    L.append(f"\n- Cluster − lone premium (126d adj): **{_p(prem)}** (market baseline is ~0 by construction).\n")

    L.append("## Cost sweep (round-trip) — cluster net @ each cost\n")
    L.append("| One-way cost | Cluster net (adj 126d) |\n|---|---|")
    for c in ("25.0", "30.0", "50.0", "100.0"):
        L.append(f"| {c} bps | {_p(o['cost_sweep'][c]['cluster_net126'])} |")
    L.append("\n*Low turnover (6-month hold): the 100 bps round-trip at 50 bps is spread over ~6 months, "
             "not monthly — the reason this could clear the bar where momentum/PEAD didn't.*\n")

    L.append("## By year — cluster net @50bps (consistency required)\n")
    L.append("| Year | gross (adj 126d) | net @50bps | n |\n|---|---|---|---|")
    posyr = 0
    for y, v in o["by_year"].items():
        posyr += 1 if (v["net50"] and v["net50"] > 0) else 0
        L.append(f"| {y} | {_p(v['gross'])} | {_p(v['net50'])} | {v['n']} |")
    nyr = len(o["by_year"])
    if o["officer_split"]:
        L.append("\n## Officer-involved vs director-only clusters (EXTRA comparison, not a result)\n")
        for k, v in o["officer_split"].items():
            L.append(f"- {k}: 126d adj mean {_p(v.get('mean'))} (t {_n(v.get('t'))}, n {v.get('n')}).")

    # verdict
    net50 = o["cost_sweep"]["50.0"]["cluster_net126"]
    t = cl.get("t")
    consistent = nyr and (posyr / nyr) >= 0.6
    survives = net50 is not None and net50 > 0.005 and (t or 0) >= 2 and prem > 0.005 and consistent
    L.append("\n## Verdict\n")
    if o["cluster_events"] < 100:
        L.append(f"- **Underpowered:** only {o['cluster_events']} cluster events in dev — too few to "
                 "conclude. Numbers are noise-dominated; not a basis for the hold-out.\n")
    elif survives:
        L.append(f"- **Insider cluster buying clears ≥50 bps AND holds across regimes in dev:** cluster "
                 f"126d net @50bps **{_p(net50)}** (>0), t {_n(t)}, cluster−lone premium {_p(prem)}, "
                 f"{posyr}/{nyr} years net-positive. Low turnover (6-month hold) is why costs don't eat "
                 "it. **Strongest tradeable dev result of the program — a candidate for the sealed 2025+ "
                 "hold-out, discounted for arena #5.**\n")
    else:
        why = []
        if not (net50 is not None and net50 > 0.005):
            why.append(f"cluster net @50bps is {_p(net50)}")
        if (t or 0) < 2:
            why.append(f"cluster IC/return not significant (t {_n(t)})")
        if not (prem > 0.005):
            why.append(f"clustering adds little over lone buys (premium {_p(prem)})")
        if not consistent:
            why.append(f"inconsistent by year ({posyr}/{nyr} positive)")
        L.append("- **Does NOT clear the bar (or not convincingly): " + "; ".join(why) + ".** "
                 "Even with the low-turnover advantage, the market-adjusted cluster drift is not a "
                 "reliable, cost-surviving, regime-robust edge in development. **No case for the sealed "
                 "hold-out.**\n")
    L.append("- **Arena-#5 discount:** 5th arena of the program; a nominal dev positive is a weak prior; "
             "only the sealed 2025+ hold-out could settle it.\n")
    L.append("\n> **STOP for review. 2025+ hold-out untouched.**\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
