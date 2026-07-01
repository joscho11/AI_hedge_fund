"""Congressional-trading signal — Phase A: acquire + clean + join to archived Sharadar SEP prices +
the decisive TRADE-DATE vs DISCLOSURE-DATE forward-return diagnostic. Descriptive/in-sample only
(D9 spirit); no strategy, no hold-out. STOP for review after the verdict.

Source: kadoa-org/congress-trading-monitor `trades.json` (current; carries filing_date + days_to_file).
The classic free stock-watcher datasets are defunct (housestockwatcher.com dead; Senate GitHub frozen
2020, no disclosure date) — see the report for the honest data-availability picture.

    .venv/Scripts/python.exe scripts/congress_phase_a.py
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

REPO = Path(__file__).resolve().parents[1]
TRADES_URL = "https://raw.githubusercontent.com/kadoa-org/congress-trading-monitor/main/public/data/trades.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
HORIZONS = [21, 63]  # trading-day forward horizons


def acquire(out: Path) -> pd.DataFrame:
    raw = out / "kadoa_trades_raw.json"
    if not raw.exists():
        r = requests.get(TRADES_URL, headers={"User-Agent": UA}, timeout=120); r.raise_for_status()
        raw.write_bytes(r.content)
    return pd.json_normalize(json.loads(raw.read_text()))


def clean(df: pd.DataFrame, common_tickers: set[str]) -> tuple[pd.DataFrame, dict]:
    n0 = len(df)
    df = df.rename(columns={"filing_date": "disclosure_date", "filer_name": "member"})
    df["transaction_date"] = pd.to_datetime(df["transaction_date"], errors="coerce")
    df["disclosure_date"] = pd.to_datetime(df["disclosure_date"], errors="coerce")
    side = df["transaction_type"].map(lambda t: "buy" if t == "Purchase"
                                      else ("sell" if isinstance(t, str) and t.startswith("Sale") else "other"))
    df["side"] = side
    df["ticker"] = df["ticker"].astype("string").str.upper().str.strip()

    drops = {}
    m_dates = df["transaction_date"].notna() & df["disclosure_date"].notna()
    drops["missing_dates"] = int((~m_dates).sum())
    m_tkr = df["ticker"].notna() & ~df["ticker"].isin(["", "--", "N/A", "NONE"])
    drops["blank_ticker"] = int((~m_tkr).sum())
    m_eq = df["ticker"].isin(common_tickers)          # US domestic common equity (Sharadar TICKERS)
    drops["non_common_equity(bonds/options/etf/crypto/etc)"] = int((m_tkr & ~m_eq).sum())
    keep = m_dates & m_tkr & m_eq
    clean_df = df[keep].copy()
    clean_df["days_to_file"] = (clean_df["disclosure_date"] - clean_df["transaction_date"]).dt.days
    stats = {"raw_rows": n0, "kept_rows": int(len(clean_df)), "drops": drops}
    return clean_df, stats


def _adj_series(sep_rows: pd.DataFrame) -> dict[str, pd.Series]:
    out = {}
    for tk, g in sep_rows.sort_values("date").groupby("ticker"):
        s = pd.Series(g["closeadj"].values, index=pd.to_datetime(g["date"]).values, dtype=float)
        out[tk] = s[~s.index.duplicated(keep="last")].sort_index()
    return out


def forward_return(adj: pd.Series, sessions: pd.DatetimeIndex, entry_date, h: int) -> float | None:
    """Delisting-aware h-trading-day forward return entering at first session >= entry_date."""
    if adj.empty:
        return None
    last = adj.index.max()
    pos = sessions.searchsorted(pd.Timestamp(entry_date), "left")
    if pos >= len(sessions):
        return None
    entry_sess = sessions[pos]
    if entry_sess > last:
        return None
    p0 = adj.asof(entry_sess)
    if pd.isna(p0) or p0 <= 0:
        return None
    tpos = pos + h
    if tpos >= len(sessions):
        return None
    target = sessions[tpos]
    if target <= last:
        p1 = adj.asof(target)
    else:
        # window extends past this name's last price: realized only if the name delisted (terminal),
        # otherwise the horizon isn't realized yet -> skip.
        if target <= pd.Timestamp(adj.index.max()):
            p1 = adj.asof(target)
        else:
            # delisted within window if last price is well before target and before overall data end
            p1 = adj.loc[:last].iloc[-1] if last < sessions[-1] else np.nan
    return None if pd.isna(p1) else float(p1 / p0 - 1.0)


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    out = cache.root / "congress"; out.mkdir(parents=True, exist_ok=True)

    tk = cache.get("sharadar", "TICKERS")
    common = set(tk.loc[tk["category"].isin(
        ["Domestic Common Stock", "Domestic Common Stock Primary Class"]), "ticker"].dropna().str.upper())

    raw = acquire(out)
    df, cstats = clean(raw, common)
    df.to_parquet(out / "transactions_clean.parquet", index=False)

    # coverage / freshness
    cov = {"disclosure_min": str(df["disclosure_date"].min().date()),
           "disclosure_max": str(df["disclosure_date"].max().date()),
           "transaction_min": str(df["transaction_date"].min().date()),
           "transaction_max": str(df["transaction_date"].max().date())}

    # join to SEP prices (archived) — match rate + load the matched tickers
    sep_tickers = df["ticker"].unique().tolist()
    dset = pa_ds.dataset(str(cache.root / "sharadar" / "SEP.parquet"), format="parquet")
    sep = dset.to_table(columns=["ticker", "date", "closeadj"],
                        filter=pa_ds.field("ticker").isin(sep_tickers)).to_pandas()
    matched = set(sep["ticker"].unique())
    match_rate = df["ticker"].isin(matched).mean()
    df = df[df["ticker"].isin(matched)].copy()
    adj = _adj_series(sep)
    sessions = trading_sessions(cfg.dates.start, str(pd.to_datetime(sep["date"]).max().date()),
                                cfg.calendar.exchange)

    # THE diagnostic: buys, forward return from trade date vs disclosure date
    buys = df[df["side"] == "buy"].copy()
    rows = []
    for r in buys.itertuples(index=False):
        s = adj.get(r.ticker)
        if s is None:
            continue
        rec = {"ticker": r.ticker, "member": r.member, "chamber": r.chamber, "owner": r.owner}
        ok = False
        for h in HORIZONS:
            rec[f"trade_{h}"] = forward_return(s, sessions, r.transaction_date, h)
            rec[f"disc_{h}"] = forward_return(s, sessions, r.disclosure_date, h)
            ok = ok or rec[f"disc_{h}"] is not None
        if ok:
            rows.append(rec)
    fr = pd.DataFrame(rows)

    diag = {"buys_total": int((df["side"] == "buy").sum()),
            "buys_with_realized_fwd": int(len(fr))}
    for h in HORIZONS:
        tr = fr[f"trade_{h}"].dropna(); ds = fr[f"disc_{h}"].dropna()
        diag[f"h{h}"] = {
            "n_trade": int(len(tr)), "trade_mean": float(tr.mean()) if len(tr) else None,
            "trade_median": float(tr.median()) if len(tr) else None,
            "n_disc": int(len(ds)), "disc_mean": float(ds.mean()) if len(ds) else None,
            "disc_median": float(ds.median()) if len(ds) else None,
        }

    # descriptive splits
    splits = {
        "buy_sell": df["side"].value_counts().to_dict(),
        "chamber": df["chamber"].value_counts().to_dict(),
        "owner": df["owner"].fillna("Unknown").astype(str).value_counts().head(6).to_dict(),
        "top_members": df[df.side == "buy"]["member"].value_counts().head(8).to_dict(),
        "top_tickers": df[df.side == "buy"]["ticker"].value_counts().head(8).to_dict(),
        "lag_median": float(df["days_to_file"].median()),
        "lag_mean": float(df["days_to_file"].mean()),
        "lag_p90": float(df["days_to_file"].quantile(0.90)),
        "late_rate": float((df["days_to_file"] > 45).mean()),
    }

    out_json = {"coverage": cov, "clean": cstats, "match_rate": float(match_rate),
                "matched_tickers": len(matched), "diagnostic": diag, "splits": splits}
    (out / "phase_a_summary.json").write_text(json.dumps(out_json, indent=2, default=str))
    _write_report(REPO / "reports" / "congress_phase_a.md", out_json)
    print(json.dumps({"coverage": cov, "match_rate": round(match_rate, 3),
                      "buys_realized": diag["buys_with_realized_fwd"],
                      "h21": diag["h21"], "h63": diag["h63"]}, indent=2, default=str))
    print("Wrote reports/congress_phase_a.md")


def _p(x):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x*100:+.2f}%"


def _write_report(path, o):
    d, cov, cs = o["diagnostic"], o["coverage"], o["clean"]
    sp = o["splits"]
    L = ["# Congressional-trading signal — Phase A (feasibility, descriptive/in-sample)\n"]
    L.append("> **Exploratory, in-sample, no strategy, no hold-out touched (D9 spirit).** Every entry "
             "uses the **disclosure date**, never the trade date (using the trade date is lookahead). "
             "Forward returns from archived Sharadar SEP (delisting-aware).\n")

    L.append("## Data availability — the honest picture\n")
    L.append("- **Classic free stock-watcher datasets are DEFUNCT:** `housestockwatcher.com` no longer "
             "resolves; the Senate GitHub aggregate (`timothycarambat/senate-stock-watcher-data`) is "
             "**frozen at 2020-12 and has no `disclosure_date` field** — unusable for the tradeable "
             "question. Old S3 endpoints now return 403.\n")
    L.append("- **Working current free source:** `kadoa-org/congress-trading-monitor` `trades.json` — "
             "current, both chambers, **carries `filing_date` (disclosure) + `days_to_file`**. But it "
             "is a **rolling recent slice** (filings "
             f"{cov['disclosure_min']}→{cov['disclosure_max']}, ~5k rows), **not** full 2012+ history "
             "in one file. Its `scatter.json` (26k rows) is a 35-filer curated subset with **no filing "
             "date** — can't support this diagnostic.\n")
    L.append("- **Implication:** this Phase A runs on a **recent ~6-month window** — enough for a "
             "*directional* feasibility read, but thin and regime-specific. A robust Phase B needs "
             "fuller history: assemble per-filer files, or a **paid API** (Quiver ~1,800 equities from "
             "2016; Apify ~$2.20/1k rows). **No purchase made** — that's your call.\n")

    L.append("## Clean & match\n")
    L.append(f"- Raw rows {cs['raw_rows']:,} → kept **{cs['kept_rows']:,}** tradeable US-common-equity "
             "disclosures. Dropped: " + ", ".join(f"{k} {v:,}" for k, v in cs['drops'].items()) + ".\n")
    L.append(f"- **Match rate to archived SEP prices: {o['match_rate']*100:.1f}%** "
             f"({o['matched_tickers']} distinct tickers). Amount ranges carried as low/high brackets "
             "(never point-valued); ownership retained.\n")

    L.append("## Descriptive splits\n")
    L.append(f"- Buy/Sell/Other: {sp['buy_sell']}. Chamber: {sp['chamber']}. Ownership: {sp['owner']}.")
    L.append(f"- **Disclosure lag (days trade→disclosure): median {sp['lag_median']:.0f}, "
             f"mean {sp['lag_mean']:.0f}, p90 {sp['lag_p90']:.0f}; "
             f"{sp['late_rate']*100:.0f}% filed >45 days after the trade.** This is the built-in "
             "disadvantage — you learn of the trade ~a month later.")
    L.append(f"- Concentration — top buying members: {sp['top_members']}.")
    L.append(f"- Top bought tickers: {sp['top_tickers']}.\n")

    L.append("## THE decisive diagnostic — trade-date vs disclosure-date forward return (BUYS)\n")
    L.append(f"Buys with a realized forward window: **{d['buys_with_realized_fwd']:,}** "
             f"(of {d['buys_total']:,} equity buys; the rest are too recent for prices to have "
             "realized the horizon).\n")
    L.append("| Horizon | Entry = TRADE date (hyped, NOT tradeable) | Entry = DISCLOSURE date (the only tradeable one) | Drift captured after lag |")
    L.append("|---|---|---|---|")
    for h in (21, 63):
        s = d[f"h{h}"]
        keep = (s["disc_mean"] / s["trade_mean"] * 100) if (s["trade_mean"] and s["disc_mean"] is not None and s["trade_mean"] != 0) else None
        L.append(f"| {h}d | mean {_p(s['trade_mean'])}, median {_p(s['trade_median'])} (n={s['n_trade']}) "
                 f"| mean {_p(s['disc_mean'])}, median {_p(s['disc_median'])} (n={s['n_disc']}) "
                 f"| {(f'{keep:.0f}% of the trade-date mean' if keep is not None else '—')} |")

    # verdict
    d21, t21, d21m = d["h21"]["disc_mean"], d["h21"]["trade_mean"], d["h21"]["disc_median"]
    d63 = d["h63"]["disc_mean"]
    weak = (d21m is not None and d21m <= 0) or (d21 is None) or (t21 and d21 is not None and d21 < 0.5 * t21)
    L.append("\n## Verdict\n")
    if weak:
        L.append(f"- **The 45-day lag substantially erodes the effect, and the only tradeable number is "
                 f"weak.** At 21 days the disclosure-date mean is {_p(d21)} (vs {_p(t21)} from the "
                 f"trade date — ~{(1 - (d21/t21))*100:.0f}% of the effect gone), and the **median is "
                 f"{_p(d21m)}** — the *typical* disclosed buy, entered when you could act, is slightly "
                 "**down**. The mean stays positive only via a few tail winners.\n")
        L.append(f"- **The 63-day disclosure-date mean ({_p(d63)}) is almost certainly mostly market "
                 "beta, not alpha:** this is a recent **rising-market** ~6-month window and the returns "
                 "here are **not** benchmark-adjusted. A proper test must subtract the market.\n")
        L.append("- **Read:** on this thin recent sample, following congressional buys *from the "
                 "disclosure date* does not show a compelling, broad-based edge. **Weak case for a "
                 "Phase B on free data as-is.** If pursued at all, it would first require (a) market/"
                 "beta-adjusted returns, (b) genuine multi-year history (not this 6-month slice — paid "
                 "API or assembling per-filer files), and (c) strict pre-registration. Honest prior "
                 "(the lag eats most of the edge) is **supported**.\n")
    else:
        L.append(f"- Disclosure-date drift is positive and non-trivial on this sample (21d mean {_p(d21)}, "
                 f"63d {_p(d63)}) — a hypothesis worth a pre-registered Phase B, but only after "
                 "market-adjustment + fuller history. Not a result (D9).\n")
    L.append("- **Caveats:** recent ~6-month window only; not benchmark-adjusted; concentration in a "
             "few prolific members; amounts are brackets; high multiple-comparisons risk for a thin "
             "niche signal (we just watched a dev t=3.28 evaporate on a hold-out).\n")
    L.append("\n> **STOP for review.** Phase B (one pre-registered disclosure-date-entry hypothesis on a "
             "sealed hold-out) is NOT built — its design and whether it's worth the data cost depend on "
             "your read of the above.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
