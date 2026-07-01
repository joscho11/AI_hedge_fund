"""Phase A Step 1 — acquire the free Senate + House stock-watcher disclosure datasets and report
coverage/freshness/schema. Raw JSON cached under data_cache/congress/ (gitignored).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data.cache import ParquetCache
from src.utils.config import load_config

SOURCES = {
    "senate": "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json",
    "house": "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json",
}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def main():
    cfg = load_config()
    out = ParquetCache(cfg.cache_path).root / "congress"
    out.mkdir(parents=True, exist_ok=True)
    sess = requests.Session(); sess.headers.update({"User-Agent": UA})

    for name, url in SOURCES.items():
        raw = out / f"{name}_raw.json"
        if raw.exists():
            print(f"[cached] {name}: {raw.stat().st_size/1e6:.1f} MB")
        else:
            print(f"[pull] {name} <- {url}")
            r = sess.get(url, timeout=120); r.raise_for_status()
            raw.write_bytes(r.content)
            print(f"        {name}: {raw.stat().st_size/1e6:.1f} MB")
        df = pd.read_json(raw)
        print(f"  rows: {len(df):,}  columns: {list(df.columns)}")
        for dc in ("transaction_date", "disclosure_date"):
            if dc in df.columns:
                d = pd.to_datetime(df[dc], errors="coerce")
                print(f"  {dc}: {d.min()} .. {d.max()}  ({d.notna().mean()*100:.0f}% parseable)")
        print("  sample row:")
        print(df.iloc[len(df) // 2].to_dict())
        print()


if __name__ == "__main__":
    main()
