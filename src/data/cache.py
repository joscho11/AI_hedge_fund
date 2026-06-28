"""Local parquet cache so we never re-hit rate-limited APIs unnecessarily.

Keyed by (namespace, key). Each entry is one parquet file under data_cache/<namespace>/<key>.parquet.
This is a pure storage layer — it does not know about as-of semantics; that lives in the providers.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_key(key: str) -> str:
    cleaned = _SAFE.sub("_", key).strip("_")
    if len(cleaned) > 100:
        # Keep it readable but bounded; disambiguate with a short hash.
        digest = hashlib.sha1(key.encode()).hexdigest()[:8]
        cleaned = f"{cleaned[:80]}_{digest}"
    return cleaned or "default"


class ParquetCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, namespace: str, key: str) -> Path:
        return self.root / namespace / f"{_safe_key(key)}.parquet"

    def has(self, namespace: str, key: str) -> bool:
        return self._path(namespace, key).exists()

    def get(self, namespace: str, key: str) -> pd.DataFrame | None:
        path = self._path(namespace, key)
        if not path.exists():
            return None
        return pd.read_parquet(path)

    def put(self, namespace: str, key: str, df: pd.DataFrame) -> Path:
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        return path
