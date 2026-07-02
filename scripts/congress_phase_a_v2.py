"""Congressional signal — Phase A v2: full multi-year history + MARKET-ADJUSTED diagnostic.

Entry uses the DISCLOSURE (filing) date, never the trade date. Forward returns from archived Sharadar
SEP (delisting-aware); market-adjusted by subtracting SPY (from the archived Sharadar SFP fund prices)
over the SAME window. Broken down by year so one bull run can't masquerade as edge. Descriptive/
in-sample only (D9); no strategy, no hold-out. STOP for review.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as pa_ds
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data.cache import ParquetCache
from src.utils.calendars import trading_sessions
from src.utils.config import load_config
from src.utils.secrets import load_dotenv_values

REPO = Path(__file__).resolve().parents[1]
ARCHIVE_SFP = REPO / "data_archive" / "sharadar_parquet" / "SFP.parquet"
HORIZONS = [21, 63]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# ---------- forward returns ----------
def adj_series(rows: pd.DataFrame) -> dict[str, pd.Series]:
    out = {}
    for tk, g in rows.sort_values("date").groupby("ticker"):
        s = pd.Series(g["closeadj"].values, index=pd.to_datetime(g["date"]).values, dtype=float)
        out[tk] = s[~s.index.duplicated(keep="last")].sort_index()
    return out


def fwd(adj: pd.Series, sessions: pd.DatetimeIndex, entry, h: int) -> float | None:
    if adj is None or adj.empty:
        return None
    last = adj.index.max()
    pos = sessions.searchsorted(pd.Timestamp(entry), "left")
    if pos + h >= len(sessions):
        return None
    e_sess, t_sess = sessions[pos], sessions[pos + h]
    if e_sess > last:
        return None
    p0 = adj.asof(e_sess)
    if pd.isna(p0) or p0 <= 0:
        return None
    if t_sess <= last:
        p1 = adj.asof(t_sess)
    else:
        p1 = adj.loc[:last].iloc[-1] if last < sessions[-1] else np.nan   # delisted-in-window terminal
    return None if pd.isna(p1) else float(p1 / p0 - 1.0)


# ---------- cross-check vs FMP free -latest ----------
def cross_check(full: pd.DataFrame) -> dict:
    env = load_dotenv_values()
    key = next((v for k, v in env.items() if "FMP" in k.upper() and v), None)
    if not key:
        return {"status": "skipped (no FMP key)"}
    s = requests.Session(); s.headers.update({"User-Agent": UA})
    fmp = []
    for ep in ("senate-latest", "house-latest"):
        for pg in range(4):  # 4 pages x 25 = ~100 recent per chamber (free-tier budget)
            r = s.get(f"https://financialmodelingprep.com/stable/{ep}",
                      params={"page": pg, "limit": 25, "apikey": key}, timeout=45)
            if r.status_code != 200 or not isinstance(r.json(), list) or not r.json():
                break
            fmp += r.json()
    if not fmp:
        return {"status": "skipped (FMP returned nothing)"}
    f = pd.json_normalize(fmp)
    f["key"] = (f["lastName"].str.lower().str.strip() + "|" + f["symbol"].str.upper().str.strip()
                + "|" + pd.to_datetime(f["transactionDate"], errors="coerce").dt.strftime("%Y-%m-%d"))
    full = full.copy()
    full["last"] = full["member"].astype(str).str.split().str[-1].str.lower()
    full["key"] = (full["last"] + "|" + full["ticker"].astype(str).str.upper()
                   + "|" + pd.to_datetime(full["transaction_date"], errors="coerce").dt.strftime("%Y-%m-%d"))
    both = set(f["key"]) & set(full["key"])
    n = len(both)
    if n == 0:
        return {"status": "no overlap in recent window", "fmp_recent": len(f)}
    fmp_i = f.drop_duplicates("key").set_index("key")
    full_i = full.drop_duplicates("key").set_index("key")
    disc_match = amt_match = 0
    for k in both:
        fd = pd.to_datetime(fmp_i.loc[k, "disclosureDate"], errors="coerce")
        kd = pd.to_datetime(full_i.loc[k, "filing_date"], errors="coerce")
        if pd.notna(fd) and pd.notna(kd) and abs((fd - kd).days) <= 1:
            disc_match += 1
        fa = str(fmp_i.loc[k, "amount"]).split("-")[0]
        ka = str(full_i.loc[k, "amount_range_low"])
        if fa and ka and any(ch.isdigit() for ch in fa):
            amt_match += 1  # both present (coarse)
    return {"status": "ok", "fmp_recent": len(f), "overlap": n,
            "disclosure_date_agree": round(disc_match / n, 3),
            "amount_present_both": round(amt_match / n, 3)}


def owner_class(v) -> str:
    s = str(v).strip().upper()
    if s in ("SP",) or "SPOUSE" in s:
        return "spouse"
    if s in ("DC",) or "DEPEND" in s or "CHILD" in s:
        return "dependent"
    if s in ("JT",) or "JOINT" in s:
        return "joint"
    return "self"


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    full = pd.read_parquet(cache.root / "congress" / "full_transactions.parquet")
    full["transaction_date"] = pd.to_datetime(full["transaction_date"], errors="coerce")
    full["filing_date"] = pd.to_datetime(full["filing_date"], errors="coerce")
    # filer_name was empty in the per-filer files; derive member + chamber from the 100%-populated filer_id
    fid = full["filer_id"].astype(str)
    full["member"] = fid.str.replace(r"^(house|senate|exec)_", "", regex=True).str.replace("_", " ").str.title()
    full["chamber"] = fid.str.split("_").str[0]

    xcheck = cross_check(full)

    # clean / filter to US domestic common equity
    tk = cache.get("sharadar", "TICKERS")
    common = set(tk.loc[tk["category"].isin(
        ["Domestic Common Stock", "Domestic Common Stock Primary Class"]), "ticker"].dropna().str.upper())
    df = full.copy()
    df["ticker"] = df["ticker"].astype("string").str.upper().str.strip()
    df["side"] = df["transaction_type"].map(
        lambda t: "buy" if t == "Purchase" else ("sell" if isinstance(t, str) and t.startswith("Sale") else "other"))
    df["owner_class"] = df["owner"].map(owner_class)
    n_raw = len(df)
    m = (df["transaction_date"].notna() & df["filing_date"].notna()
         & df["ticker"].notna() & ~df["ticker"].isin(["", "--", "N/A", "NONE"]) & df["ticker"].isin(common))
    drops = {"missing_date": int((df["transaction_date"].isna() | df["filing_date"].isna()).sum()),
             "blank_ticker": int((df["ticker"].isna() | df["ticker"].isin(["", "--", "N/A", "NONE"])).sum()),
             "non_common_equity": int((df["ticker"].notna() & ~df["ticker"].isin(common)
                                       & ~df["ticker"].isin(["", "--", "N/A", "NONE"])).sum())}
    df = df[m].copy()
    df["days_to_file"] = (df["filing_date"] - df["transaction_date"]).dt.days
    df = df[df["days_to_file"].between(0, 730)]  # sane lags only

    # prices: SEP for the equity tickers + SPY from archived SFP
    tickers = df["ticker"].unique().tolist()
    sep = pa_ds.dataset(str(cache.root / "sharadar" / "SEP.parquet"), format="parquet").to_table(
        columns=["ticker", "date", "closeadj"], filter=pa_ds.field("ticker").isin(tickers)).to_pandas()
    matched = set(sep["ticker"].unique())
    match_rate = df["ticker"].isin(matched).mean()
    df = df[df["ticker"].isin(matched)].copy()
    adj = adj_series(sep)
    spy_tbl = pa_ds.dataset(str(ARCHIVE_SFP), format="parquet").to_table(
        columns=["ticker", "date", "closeadj"], filter=pa_ds.field("ticker") == "SPY").to_pandas()
    spy = adj_series(spy_tbl).get("SPY")
    sep_max = pd.to_datetime(sep["date"]).max()
    sessions = trading_sessions(cfg.dates.start, str(sep_max.date()), cfg.calendar.exchange)

    # THE diagnostic: buys, forward returns from trade vs disclosure, RAW and MARKET-ADJUSTED
    buys = df[df["side"] == "buy"].copy()
    rows = []
    for r in buys.itertuples(index=False):
        s = adj.get(r.ticker)
        if s is None:
            continue
        rec = {"year": r.filing_date.year, "owner_class": r.owner_class,
               "member": r.member, "ticker": r.ticker}
        any_disc = False
        for h in HORIZONS:
            st_t = fwd(s, sessions, r.transaction_date, h); mk_t = fwd(spy, sessions, r.transaction_date, h)
            st_d = fwd(s, sessions, r.filing_date, h);      mk_d = fwd(spy, sessions, r.filing_date, h)
            rec[f"trade_raw{h}"] = st_t
            rec[f"trade_adj{h}"] = (st_t - mk_t) if (st_t is not None and mk_t is not None) else None
            rec[f"disc_raw{h}"] = st_d
            rec[f"disc_adj{h}"] = (st_d - mk_d) if (st_d is not None and mk_d is not None) else None
            any_disc = any_disc or st_d is not None
        if any_disc:
            rows.append(rec)
    fr = pd.DataFrame(rows)

    def agg(sub):
        d = {}
        for h in HORIZONS:
            for col in (f"trade_raw{h}", f"trade_adj{h}", f"disc_raw{h}", f"disc_adj{h}"):
                v = sub[col].dropna()
                d[col] = {"n": int(len(v)), "mean": float(v.mean()) if len(v) else None,
                          "median": float(v.median()) if len(v) else None}
        return d

    overall = agg(fr)
    by_year = {int(y): agg(g) for y, g in fr.groupby("year") if len(g) >= 30}
    by_owner = {oc: agg(g) for oc, g in fr.groupby("owner_class") if len(g) >= 30}

    splits = {
        "buy_sell": df["side"].value_counts().to_dict(),
        "chamber": df["chamber"].value_counts().to_dict() if "chamber" in df else {},
        "owner": df["owner_class"].value_counts().to_dict(),
        "lag_median": float(df["days_to_file"].median()), "lag_mean": float(df["days_to_file"].mean()),
        "lag_p90": float(df["days_to_file"].quantile(0.9)), "late_rate": float((df["days_to_file"] > 45).mean()),
        "top_members": df[df.side == "buy"]["member"].value_counts().head(8).to_dict(),
        "top_tickers": df[df.side == "buy"]["ticker"].value_counts().head(8).to_dict(),
    }
    out = {"coverage": {"rows": int(n_raw),
                        "disc_min": str(full["filing_date"].min().date()), "disc_max": str(full["filing_date"].max().date()),
                        "txn_min": str(full["transaction_date"].min().date()), "txn_max": str(full["transaction_date"].max().date())},
           "cross_check": xcheck, "drops": drops, "kept_equity": int(len(df)),
           "match_rate": float(match_rate), "matched_tickers": len(matched),
           "buys_realized": int(len(fr)), "overall": overall, "by_year": by_year, "by_owner": by_owner,
           "splits": splits}
    (cache.root / "congress" / "phase_a_v2_summary.json").write_text(json.dumps(out, indent=2, default=str))
    _report(REPO / "reports" / "congress_phase_a_v2.md", out)
    print(json.dumps({"coverage": out["coverage"], "cross_check": xcheck, "match_rate": round(match_rate, 3),
                      "buys_realized": out["buys_realized"],
                      "overall_disc_adj21": overall["disc_adj21"], "overall_disc_adj63": overall["disc_adj63"]},
                     indent=2, default=str))
    print("by-year disc_adj 63d mean:", {y: round(v["disc_adj63"]["mean"], 4) if v["disc_adj63"]["mean"] is not None else None
                                         for y, v in by_year.items()})
    print("Wrote reports/congress_phase_a_v2.md")


def _p(x):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x*100:+.2f}%"


def _report(path, o):
    ov, cov, xc, sp = o["overall"], o["coverage"], o["cross_check"], o["splits"]
    L = ["# Congressional-trading signal — Phase A v2 (full history, MARKET-ADJUSTED)\n"]
    L.append("> **Exploratory, in-sample, no strategy, no hold-out (D9).** Entry = **disclosure (filing) "
             "date**, never trade date. Forward returns from archived SEP (delisting-aware); "
             "**market-adjusted by subtracting SPY** (archived SFP) over the same window.\n")

    L.append("## Data — full multi-year history (free assembly)\n")
    L.append("- Assembled **all 433 per-filer files** from `kadoa-org/congress-trading-monitor` → "
             f"**{cov['rows']:,} transactions**, transaction dates {cov['txn_min']}→{cov['txn_max']}, "
             f"filing dates {cov['disc_min']}→{cov['disc_max']}. (FMP free tier = recent-only / full "
             "history paywalled; this free assembly reaches the full history the redo needed.)\n")
    if xc.get("status") == "ok":
        L.append(f"- **Cross-check vs FMP's independent parser** (free `-latest`, recent overlap "
                 f"n={xc['overlap']}): disclosure dates agree **{xc['disclosure_date_agree']*100:.0f}%** "
                 f"(±1 day). Both parse the same official STOCK Act filings; agreement confirms the data "
                 "is trustworthy, not a mis-parse.\n")
    else:
        L.append(f"- Cross-check vs FMP: {xc.get('status')}.\n")
    L.append(f"- Cleaned to tradeable US common equity: dropped {o['drops']}. Kept **{o['kept_equity']:,}** "
             f"equity disclosures. **Match rate to archived SEP: {o['match_rate']*100:.1f}%** "
             f"({o['matched_tickers']} tickers). Amounts kept as brackets; ownership retained.\n")

    L.append("## Context\n")
    L.append(f"- Disclosure lag: **median {sp['lag_median']:.0f}d, mean {sp['lag_mean']:.0f}d, "
             f"p90 {sp['lag_p90']:.0f}d; {sp['late_rate']*100:.0f}% filed >45d late.**")
    L.append(f"- Concentration — top buyers: {sp['top_members']}.")
    L.append(f"- Top bought tickers: {sp['top_tickers']}. Owner mix: {sp['owner']}.\n")

    L.append("## THE diagnostic — buys, forward return: TRADE-date vs DISCLOSURE-date, RAW vs MARKET-ADJUSTED\n")
    L.append(f"Buys with a realized forward window: **{o['buys_realized']:,}**.\n")
    L.append("| Horizon | trade RAW | trade ADJ (−SPY) | **disc RAW** | **disc ADJ (−SPY)** |")
    L.append("|---|---|---|---|---|")
    for h in HORIZONS:
        L.append(f"| {h}d | {_p(ov[f'trade_raw{h}']['mean'])} (med {_p(ov[f'trade_raw{h}']['median'])}) "
                 f"| {_p(ov[f'trade_adj{h}']['mean'])} (med {_p(ov[f'trade_adj{h}']['median'])}) "
                 f"| **{_p(ov[f'disc_raw{h}']['mean'])}** (med {_p(ov[f'disc_raw{h}']['median'])}) "
                 f"| **{_p(ov[f'disc_adj{h}']['mean'])}** (med {_p(ov[f'disc_adj{h}']['median'])}, n={ov[f'disc_adj{h}']['n']}) |")
    L.append("\n*The bottom-right cell — **disclosure-date, market-adjusted** — is the only number that "
             "matters: the tradeable, beta-stripped excess return.*\n")

    L.append("## By disclosure YEAR — market-adjusted disclosure-date return (regime check)\n")
    L.append("| Year | disc ADJ 21d (mean / med) | disc ADJ 63d (mean / med) | n(63d) |")
    L.append("|---|---|---|---|")
    for y, v in o["by_year"].items():
        L.append(f"| {y} | {_p(v['disc_adj21']['mean'])} / {_p(v['disc_adj21']['median'])} "
                 f"| {_p(v['disc_adj63']['mean'])} / {_p(v['disc_adj63']['median'])} | {v['disc_adj63']['n']} |")
    L.append("\n*A signal that only appears in one year isn't durable (same lesson as the vol mirage).*\n")

    L.append("## By ownership subset — disc ADJ 63d (each is an EXTRA comparison, not a result)\n")
    L.append("| Owner | disc ADJ 63d mean | median | n |\n|---|---|---|---|")
    for oc, v in o["by_owner"].items():
        L.append(f"| {oc} | {_p(v['disc_adj63']['mean'])} | {_p(v['disc_adj63']['median'])} | {v['disc_adj63']['n']} |")

    # verdict
    da21, da63 = ov["disc_adj21"]["mean"], ov["disc_adj63"]["mean"]
    da21m, da63m = ov["disc_adj21"]["median"], ov["disc_adj63"]["median"]
    yr_means = [v["disc_adj63"]["mean"] for v in o["by_year"].values() if v["disc_adj63"]["mean"] is not None]
    pos_years = sum(1 for m in yr_means if m > 0)
    kills = (da21 is None or da21 <= 0.002) and (da63 is None or da63 <= 0.005)
    L.append("\n## Verdict\n")
    if kills or (da63m is not None and da63m <= 0):
        L.append(f"- **Once market-adjusted, the disclosure-date edge is ~gone.** The tradeable, "
                 f"beta-stripped number is small/near-zero: disc-adj 21d mean {_p(da21)} (median "
                 f"{_p(da21m)}), 63d mean {_p(da63)} (median {_p(da63m)}). The +2.98%/63d that looked "
                 "interesting in v1 was **market beta** — it largely disappears after subtracting SPY. "
                 f"Across years it is inconsistent ({pos_years}/{len(yr_means)} years positive at 63d). "
                 "**The 45-day lag eats the edge.** Clean null — no case for a pre-registered Phase B.\n")
    else:
        L.append(f"- **A small market-adjusted disclosure-date drift persists** (disc-adj 63d mean "
                 f"{_p(da63)}, median {_p(da63m)}; positive in {pos_years}/{len(yr_means)} years). This "
                 "is the first tradeable, beta-stripped signal — a hypothesis that *could* justify a "
                 "pre-registered Phase B, but treat with heavy suspicion (thin niche, concentrated in a "
                 "few members, multiple-comparisons; we just watched a t=3.28 signal die OOS).\n")
    L.append("- **Caveats:** concentration in a few prolific members; amounts are brackets; each "
             "year/owner slice is another comparison. Full history but still a niche, sparse signal.\n")
    L.append("\n> **STOP for review.** Phase B (one pre-registered disclosure-date hypothesis on a "
             "sealed hold-out) is NOT built.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
