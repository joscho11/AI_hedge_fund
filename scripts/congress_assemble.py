"""Phase A v2 Step 1 — assemble the FULL multi-year congressional history for free by fetching all
per-filer JSON files from kadoa-org/congress-trading-monitor (each carries a member's complete
history with filing_date). Cached to data_cache/congress/full_transactions.parquet (resumable).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data.cache import ParquetCache
from src.utils.config import load_config

API = "https://api.github.com/repos/kadoa-org/congress-trading-monitor/contents/public/data/filer"
RAW = "https://raw.githubusercontent.com/kadoa-org/congress-trading-monitor/main/public/data/filer/{name}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def main():
    cfg = load_config()
    out = ParquetCache(cfg.cache_path).root / "congress"
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "full_transactions.parquet"
    if dest.exists():
        df = pd.read_parquet(dest)
        print(f"[cached] {len(df):,} rows -> {dest}")
        return

    s = requests.Session(); s.headers.update({"User-Agent": UA})
    files = [it["name"] for it in s.get(API, timeout=60).json() if it["name"].endswith(".json")]
    print(f"filer files: {len(files)}")
    frames, fail = [], 0
    for i, name in enumerate(files):
        try:
            d = s.get(RAW.format(name=name), timeout=60).json()
            trades = d.get("trades", []) if isinstance(d, dict) else d
            if trades:
                g = pd.json_normalize(trades)
                fi = d.get("filer", {}) if isinstance(d, dict) else {}
                g["filer_name"] = fi.get("name")
                g["chamber"] = fi.get("chamber")
                g["party"] = fi.get("party")
                g["state"] = fi.get("state")
                frames.append(g)
        except Exception:
            fail += 1
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(files)} fetched ({sum(len(f) for f in frames):,} rows so far)")
            time.sleep(0.5)
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["id"]) if frames else pd.DataFrame()
    df.to_parquet(dest, index=False)
    print(f"\nassembled {len(df):,} rows from {len(files)-fail}/{len(files)} filers -> {dest}")
    for dc in ("transaction_date", "filing_date"):
        if dc in df.columns:
            sd = pd.to_datetime(df[dc], errors="coerce")
            print(f"  {dc}: {sd.min().date()} .. {sd.max().date()}")
    if "chamber" in df.columns:
        print("  chamber:", df["chamber"].value_counts().to_dict())


if __name__ == "__main__":
    main()
