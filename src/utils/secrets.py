"""Tiny, dependency-free secret loader. Resolves an API key from the process environment first, then
a `.env` file at the repo root (or any parent). Never logs the value.

Tolerant of the common name variants (incl. the 'NASQAD' typo) so a misnamed var doesn't silently
break ingest.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

NDL_KEY_CANDIDATES = (
    "NASDAQ_DATA_LINK_API_KEY",
    "NASQAD_DATA_LINK_API_KEY",   # tolerate the typo in the user's .env
    "QUANDL_API_KEY",
)


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _find_dotenv(start: Path = REPO_ROOT) -> Path | None:
    for d in [start, *start.parents]:
        p = d / ".env"
        if p.exists():
            return p
    return None


def load_dotenv_values() -> dict[str, str]:
    p = _find_dotenv()
    return _parse_env_file(p) if p else {}


def get_ndl_api_key() -> str | None:
    """Return the Nasdaq Data Link key from env or .env, or None. Matches known names plus any var
    whose name looks like a data-link API key (so the 'NASQAD' typo still works)."""
    env = {**load_dotenv_values(), **os.environ}  # os.environ wins if both set
    for name in NDL_KEY_CANDIDATES:
        if env.get(name):
            return env[name]
    for name, val in env.items():
        up = name.upper()
        if val and "API_KEY" in up and ("NAS" in up or "QUANDL" in up or "DATA_LINK" in up):
            return val
    return None


def mask(secret: str | None) -> str:
    if not secret:
        return "<none>"
    return f"len={len(secret)}, …{secret[-4:]}"
