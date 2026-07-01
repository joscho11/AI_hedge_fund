"""One-time PERMANENT archive of the entire Sharadar Core US Equities Bundle to local disk, so the
project can run forever after the Nasdaq Data Link subscription is cancelled.

For each entitled table: bulk-export the RAW zip (source of truth) to data_archive/sharadar_raw/<T>/,
convert to parquet at data_archive/sharadar_parquet/<T>.parquet (DuckDB streams the giant CSVs), and
write a provenance sidecar. Resumable: skips any table whose parquet already exists and parses.

    .venv/Scripts/python.exe scripts/archive_sharadar.py [--force TABLE ...]

The archive base is data_archive/ inside the project (local, non-cloud) — overridable via
EQUITY_ALPHA_ARCHIVE_DIR. NEVER committed (see .gitignore).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.cache import ParquetCache
from src.utils.config import load_config
from src.utils.secrets import get_ndl_api_key

REPO = Path(__file__).resolve().parents[1]
ARCHIVE = Path(os.environ.get("EQUITY_ALPHA_ARCHIVE_DIR", REPO / "data_archive"))
RAW_ROOT = ARCHIVE / "sharadar_raw"
PQ_ROOT = ARCHIVE / "sharadar_parquet"

# (short, datatable code, mode). mode: "pull" = bulk export raw+parquet; "copy" = reuse existing
# data_cache parquet (large already-cached table; raw re-pull skipped per directive).
PLAN = [
    ("SF1", "SHARADAR/SF1", "copy"),
    ("SEP", "SHARADAR/SEP", "copy"),
    ("INDICATORS", "SHARADAR/INDICATORS", "pull"),
    ("SP500", "SHARADAR/SP500", "pull"),
    ("TICKERS", "SHARADAR/TICKERS", "pull"),
    ("ACTIONS", "SHARADAR/ACTIONS", "pull"),
    ("SF3A", "SHARADAR/SF3A", "pull"),
    ("EVENTS", "SHARADAR/EVENTS", "pull"),
    ("SFP", "SHARADAR/SFP", "pull"),
    ("SF2", "SHARADAR/SF2", "pull"),
    ("DAILY", "SHARADAR/DAILY", "pull"),
    ("SF3B", "SHARADAR/SF3B", "pull"),
    ("SF3", "SHARADAR/SF3", "pull"),
]
# tables small enough to fall back to paginated get_table if bulk export isn't supported
SMALL_OK = {"INDICATORS", "SP500", "TICKERS", "ACTIONS", "SF3A", "EVENTS"}


def _ndl():
    import nasdaqdatalink as ndl
    ndl.ApiConfig.api_key = get_ndl_api_key()
    return ndl


def _ndl_version():
    try:
        from importlib.metadata import version
        return version("nasdaq-data-link")
    except Exception:
        return "unknown"


def _parquet_ok(path: Path) -> int | None:
    try:
        return pq.ParquetFile(path).metadata.num_rows if path.exists() else None
    except Exception:
        return None


def _csv_to_parquet(csv_path: Path, out: Path):
    con = duckdb.connect()
    src, dst = csv_path.as_posix(), out.as_posix()
    try:
        con.execute(f"COPY (SELECT * FROM read_csv_auto('{src}', sample_size=400000)) "
                    f"TO '{dst}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    except Exception as e:  # noqa: BLE001 — fall back to lossless all-VARCHAR (raw zip is truth)
        print(f"    typed convert failed ({type(e).__name__}); retrying all_varchar")
        con.execute(f"COPY (SELECT * FROM read_csv_auto('{src}', all_varchar=true)) "
                    f"TO '{dst}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    finally:
        con.close()


def _export_raw(ndl, code: str, raw_dir: Path) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path = raw_dir / f"{code.split('/')[-1]}.zip"
    ndl.export_table(code, filename=str(zip_path))
    if not zip_path.exists():
        zips = sorted(raw_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime)
        if zips:
            zip_path = zips[-1]
    return zip_path


def _pull(ndl, short: str, code: str) -> dict:
    raw_dir = RAW_ROOT / short
    pq_path = PQ_ROOT / f"{short}.parquet"
    source = "export_table(bulk)"
    try:
        zip_path = _export_raw(ndl, code, raw_dir)
        with zipfile.ZipFile(zip_path) as z:
            name = z.namelist()[0]
            z.extract(name, raw_dir)
            csv_path = raw_dir / name
        _csv_to_parquet(csv_path, pq_path)
        csv_path.unlink(missing_ok=True)  # keep the zip (source of truth), drop the extracted CSV
        raw_ref = zip_path
    except Exception as e:  # noqa: BLE001
        if short in SMALL_OK:
            print(f"    bulk export failed ({type(e).__name__}); paginated fallback")
            df = ndl.get_table(code, paginate=True)
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_ref = raw_dir / f"{short}.csv.gz"
            df.to_csv(raw_ref, index=False, compression="gzip")
            df.to_parquet(pq_path, index=False)
            source = "get_table(paginated)"
        else:
            raise
    rows = _parquet_ok(pq_path)
    return {"source": source, "raw_path": str(raw_ref), "parquet_path": str(pq_path),
            "rows": rows, "raw_bytes": raw_ref.stat().st_size,
            "parquet_bytes": pq_path.stat().st_size}


def _copy_existing(short: str, cache_root: Path) -> dict:
    import shutil
    src = cache_root / "sharadar" / f"{short}.parquet"
    pq_path = PQ_ROOT / f"{short}.parquet"
    PQ_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, pq_path)
    return {"source": "existing cache parquet (raw re-pull skipped per directive)",
            "raw_path": None, "parquet_path": str(pq_path), "rows": _parquet_ok(pq_path),
            "raw_bytes": 0, "parquet_bytes": pq_path.stat().st_size}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", nargs="*", default=[])
    args = ap.parse_args()
    force = set(args.force)

    cfg = load_config()
    cache_root = ParquetCache(cfg.cache_path).root
    ndl = _ndl()
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    PQ_ROOT.mkdir(parents=True, exist_ok=True)
    status_path = ARCHIVE / "archive_status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {}

    for short, code, mode in PLAN:
        pq_path = PQ_ROOT / f"{short}.parquet"
        existing_rows = _parquet_ok(pq_path)
        if existing_rows and short not in force:
            print(f"[skip] {short}: parquet present ({existing_rows:,} rows)")
            status.setdefault(short, {})
            continue
        print(f"[{mode}] {short} <- {code} ...")
        try:
            rec = _copy_existing(short, cache_root) if mode == "copy" else _pull(ndl, short, code)
            rec.update(table=short, code=code, endpoint="Nasdaq Data Link datatables bulk export",
                       downloaded_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       ndl_version=_ndl_version(), status="complete" if rec["rows"] else "empty")
            (PQ_ROOT / f"{short}.provenance.json").write_text(json.dumps(rec, indent=2))
            status[short] = rec
            print(f"    {short}: {rec['rows']:,} rows, "
                  f"parquet {rec['parquet_bytes']/1e9:.2f} GB, raw {rec['raw_bytes']/1e9:.2f} GB")
        except Exception as e:  # noqa: BLE001
            status[short] = {"table": short, "code": code, "status": f"FAILED: {type(e).__name__}: {e}"}
            print(f"    FAILED {short}: {type(e).__name__}: {e}")
        status_path.write_text(json.dumps(status, indent=2, default=str))

    print("\nArchive pass done. status ->", status_path)


if __name__ == "__main__":
    main()
