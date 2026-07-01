"""Bulk-ingest Sharadar tables from Nasdaq Data Link to the local parquet cache (resumable), then
write reports/sharadar_ingest.md.

Pulls full history once (we're on a cancellable personal subscription):
  SF1     — fundamentals (point-in-time via datekey; we keep all dimensions but only AR* are ever
            queried — see SharadarProvider)
  TICKERS — reference / sector / SIC / delisted flags
  SP500   — historical index constituents (cached now; unlocks the survivorship-free re-run later)
  SEP     — daily prices incl. delisted; OPTIONAL (multi-GB) via --with-sep; only needed for the
            survivorship re-run, not for valuation. Skipped by default.

Auth: reads the API key from NASDAQ_DATA_LINK_API_KEY. On Windows the value set via `setx` lives in
the user registry; we read it explicitly so a stale parent-process environment can't hide it.

    .venv/Scripts/python.exe scripts/ingest_sharadar.py [--with-sep] [--force]
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.cache import ParquetCache
from src.utils.config import load_config
from src.utils.secrets import get_ndl_api_key, mask

REPO = Path(__file__).resolve().parents[1]
CACHE_NS = "sharadar"
TABLES = {  # cache key -> Nasdaq Data Link table code
    "SF1": "SHARADAR/SF1",
    "TICKERS": "SHARADAR/TICKERS",
    "SP500": "SHARADAR/SP500",
    "ACTIONS": "SHARADAR/ACTIONS",   # corporate actions incl. delisting/bankruptcy/mergers
}
SEP_TABLE = ("SEP", "SHARADAR/SEP")


def _api_key() -> str:
    key = get_ndl_api_key()
    if not key:
        sys.exit("No Nasdaq Data Link key found in environment or .env. Aborting — no data pulled.")
    return key


def _fetch_full(table_code: str, key: str, workdir: Path) -> pd.DataFrame:
    """Bulk-pull a full Sharadar table. Prefer export_table (server-side bulk zip); fall back to
    paginated get_table if export isn't available for this table/plan."""
    import nasdaqdatalink as ndl
    ndl.ApiConfig.api_key = key
    workdir.mkdir(parents=True, exist_ok=True)
    short = table_code.split("/")[-1]
    zip_path = workdir / f"{short}.zip"
    try:
        ndl.export_table(table_code, filename=str(zip_path))
        if not zip_path.exists():  # some client versions ignore filename; find the newest zip
            zips = sorted(workdir.glob("*.zip"), key=lambda p: p.stat().st_mtime)
            zip_path = zips[-1] if zips else zip_path
        with zipfile.ZipFile(zip_path) as z:
            with z.open(z.namelist()[0]) as f:
                return pd.read_csv(f, low_memory=False)
    except Exception as e:  # noqa: BLE001
        print(f"  export_table failed ({type(e).__name__}: {e}); falling back to paginated get_table")
        return ndl.get_table(table_code, paginate=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-sep", action="store_true", help="also pull SEP (multi-GB; delisted prices)")
    ap.add_argument("--force", action="store_true", help="re-download even if cached")
    args = ap.parse_args()

    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    key = _api_key()
    print(f"API key: {mask(key)}")
    workdir = REPO / "data_cache" / "_sharadar_dl"

    tables = dict(TABLES)
    if args.with_sep:
        tables[SEP_TABLE[0]] = SEP_TABLE[1]

    stats = {}
    for name, code in tables.items():
        if cache.has(CACHE_NS, name) and not args.force:
            df = cache.get(CACHE_NS, name)
            print(f"[cached] {name}: {len(df):,} rows (use --force to refresh)")
        else:
            print(f"[pull]   {name} <- {code} ...")
            df = _fetch_full(code, key, workdir)
            cache.put(CACHE_NS, name, df)
            print(f"         {name}: {len(df):,} rows cached")
        stats[name] = df

    _write_report(REPO / "reports" / "sharadar_ingest.md", stats)
    print("\nWrote reports/sharadar_ingest.md")


def _coverage(df: pd.DataFrame, date_col: str):
    if date_col not in df.columns:
        return None
    d = pd.to_datetime(df[date_col], errors="coerce").dropna()
    return (str(d.min().date()), str(d.max().date())) if len(d) else None


def _write_report(path: Path, stats: dict):
    L = ["# Sharadar ingest report\n"]
    L.append(f"_Pulled {datetime.now(timezone.utc).isoformat(timespec='seconds')} · "
             "Nasdaq Data Link / Sharadar (personal, non-professional license)._\n")

    L.append("## Point-in-time keying rule (plain English)\n")
    L.append("Every fundamental figure is tagged with its **`datekey`** — the date it actually became "
             "public. A feature built for rebalance date `t` may use only rows with `datekey <= t`, so "
             "we never see a number before it was filed. We use only the **as-reported** dimensions "
             "(**ARQ / ART / ARY**); the most-recent dimensions (MRQ/MRT/MRY) retroactively rewrite "
             "past periods with later restatements and are **never used** — that would be lookahead.\n")

    L.append("## Tables pulled\n")
    L.append("| Table | Rows | Date coverage | Notes |")
    L.append("|---|---|---|---|")
    if "SF1" in stats:
        sf1 = stats["SF1"]
        cov = _coverage(sf1, "datekey")
        dims = ", ".join(sorted(sf1["dimension"].unique())) if "dimension" in sf1 else "—"
        L.append(f"| SF1 | {len(sf1):,} | {cov[0]}–{cov[1]} (datekey) | dimensions: {dims} |")
    if "TICKERS" in stats:
        tk = stats["TICKERS"]
        delisted = int((tk["isdelisted"] == "Y").sum()) if "isdelisted" in tk else "?"
        L.append(f"| TICKERS | {len(tk):,} | — | delisted names: {delisted} |")
    if "SP500" in stats:
        sp = stats["SP500"]
        cov = _coverage(sp, "date")
        L.append(f"| SP500 | {len(sp):,} | {cov[0]}–{cov[1] if cov else '—'} | historical constituents "
                 "(cached for the survivorship-free re-run) |")
    if "SEP" in stats:
        sep = stats["SEP"]
        cov = _coverage(sep, "date")
        L.append(f"| SEP | {len(sep):,} | {cov[0]}–{cov[1]} | daily prices incl. delisted |")
    else:
        L.append("| SEP | _not pulled_ | — | multi-GB; only needed for the survivorship re-run "
                 "(`--with-sep`) |")

    if "SF1" in stats and "dimension" in stats["SF1"]:
        sf1 = stats["SF1"]
        ar = sf1[sf1["dimension"].isin(["ARQ", "ART", "ARY"])]
        L.append(f"\n**SF1 as-reported rows (the only ones we query): {len(ar):,}** of {len(sf1):,} "
                 f"total ({len(ar)/len(sf1)*100:.0f}%). Distinct tickers: {sf1['ticker'].nunique():,}.")

    L.append("\n## Leakage guard (tested)\n")
    L.append("`tests/test_sharadar_pit.py`: `SharadarProvider.get_facts` refuses MR* dimensions, and "
             "a restated value (a newer `datekey`) does not change any feature at an earlier `t` — "
             "the as-of selector returns the value known *then*, not the restatement.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
