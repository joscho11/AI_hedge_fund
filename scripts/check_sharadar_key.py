"""Confirm the Sharadar plan works BEFORE any bulk pull: resolve the API key (env/.env), then probe
each table with a tiny query and report access per table. Never prints the key value.

    .venv/Scripts/python.exe scripts/check_sharadar_key.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.secrets import get_ndl_api_key, mask

PROBES = [
    ("SF1 (fundamentals)", "SHARADAR/SF1", {"ticker": "AAPL", "dimension": "ARQ"}),
    ("TICKERS (reference)", "SHARADAR/TICKERS", {"ticker": "AAPL"}),
    ("SP500 (constituents)", "SHARADAR/SP500", {}),
    ("SEP (prices, optional)", "SHARADAR/SEP", {"ticker": "AAPL"}),
]


def main():
    key = get_ndl_api_key()
    print(f"API key resolved: {mask(key)}")
    if not key:
        sys.exit("No Nasdaq Data Link key found in environment or .env. Aborting.")

    import nasdaqdatalink as ndl
    ndl.ApiConfig.api_key = key

    print(f"\n{'Table':<26}{'Status':<14}Detail")
    print("-" * 70)
    accessible = []
    for label, code, filt in PROBES:
        try:
            df = ndl.get_table(code, paginate=False, **filt)
            cols = len(df.columns)
            print(f"{label:<26}{'OK':<14}{len(df)} row(s), {cols} cols")
            accessible.append(label)
        except Exception as e:  # noqa: BLE001 — classify any client/HTTP error for the report
            msg = str(e).splitlines()[0][:60]
            cls = type(e).__name__
            print(f"{label:<26}{'NO ACCESS':<14}{cls}: {msg}")

    print("-" * 70)
    need = {"SF1 (fundamentals)", "TICKERS (reference)"}
    have_need = need.issubset(set(accessible))
    print(f"\nValuation + value baseline need SF1 + TICKERS: "
          f"{'READY' if have_need else 'MISSING - cannot build valuation yet'}")
    if "SP500 (constituents)" in accessible:
        print("SP500 present -> survivorship-free re-run unlockable later.")
    if "SEP (prices, optional)" not in accessible:
        print("SEP not accessible/needed now (only for the survivorship re-run).")
    sys.exit(0 if have_need else 2)


if __name__ == "__main__":
    main()
