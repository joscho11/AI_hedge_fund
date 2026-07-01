"""Feature-family template. Every feature family (momentum now; fundamental quality / fundamental
momentum / valuation / sector-macro later) subclasses FeatureFamily and implements `compute_raw`.
Everything else — cross-sectional normalization, joining to the panel, the data-quality/leakage
report, and feature-store IO with provenance — is shared here so replicating the pattern for
fundamentals is mechanical.

Provider-agnostic by design: `compute_raw` receives a `providers` dict whose values are
family-specific (a prices DataFrame for momentum; a FundamentalsProvider for the fundamental
families). The family pattern therefore does NOT assume any particular data source — the
EDGAR-vs-Sharadar decision never touches it.

Leakage discipline baked into the template:
  * Normalization is ALWAYS per rebalance date (cross-sectional), never pooled across dates.
  * Missing values are never silently forward-filled; each feature declares its missing rule and the
    report surfaces the missing rate. A missing raw value stays NaN and is simply excluded from that
    date's cross-section.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.cache import ParquetCache
from ..data.types import COL_DATE, COL_FILED, COL_TAG, COL_TICKER, COL_VALUE
from ..eval.metrics import information_coefficient

WINSOR_LO, WINSOR_HI = 0.01, 0.99


def asof_values(facts: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """As-of-`t` fundamental values: pivot each ticker's long facts on filing date (`filed`=datekey),
    carry forward, and sample at `dates`. The result at date d uses only rows with filed <= d, so it
    is point-in-time by construction. Returns long [date, ticker, <tag cols>]."""
    dates = pd.DatetimeIndex(sorted(pd.DatetimeIndex(dates).unique()))
    out = []
    for tk, g in facts.groupby(COL_TICKER):
        wide = g.pivot_table(index=COL_FILED, columns=COL_TAG, values=COL_VALUE, aggfunc="last")
        wide = wide.sort_index()
        full = wide.reindex(wide.index.union(dates)).ffill().reindex(dates)
        full[COL_TICKER] = tk
        full[COL_DATE] = dates
        out.append(full.reset_index(drop=True))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


@dataclass(frozen=True)
class FeatureSpec:
    """Self-documenting metadata for one feature. `as_of` is the exact timing statement that the
    leakage report surfaces verbatim."""
    name: str
    description: str
    as_of: str           # e.g. "ratio of adj close at t to adj close 63 trading days before t"
    missing_rule: str    # e.g. "NaN until >=252 trailing sessions exist; never filled"


class FeatureFamily(ABC):
    name: str
    specs: list[FeatureSpec]

    @property
    def feature_names(self) -> list[str]:
        return [s.name for s in self.specs]

    # ---- families implement only this ----
    @abstractmethod
    def compute_raw(
        self, panel: pd.DataFrame, rebalance_dates: pd.DatetimeIndex, *,
        providers: dict, exchange: str = "XNYS",
    ) -> pd.DataFrame:
        """Long DataFrame [date, ticker, <raw feature cols>], strictly as-of-t. One row per
        (date, ticker) in the panel's universe; NaN where history is insufficient (never filled)."""

    # ---- shared machinery ----
    def normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """Per-date winsorize → z-score and percentile-rank each feature. Adds `<f>_z` and `<f>_rank`.
        Strictly cross-sectional: every statistic is computed within a single rebalance date."""
        out = df.copy()
        grp = out.groupby(COL_DATE)
        for f in self.feature_names:
            lo = grp[f].transform(lambda s: s.quantile(WINSOR_LO))
            hi = grp[f].transform(lambda s: s.quantile(WINSOR_HI))
            w = out[f].clip(lo, hi)
            mean = w.groupby(out[COL_DATE]).transform("mean")
            std = w.groupby(out[COL_DATE]).transform("std")
            z = (w - mean) / std
            z[(std == 0) & out[f].notna()] = 0.0           # no dispersion -> neutral
            z = z.replace([np.inf, -np.inf], np.nan)
            out[f + "_z"] = z
            out[f + "_rank"] = grp[f].rank(pct=True)         # NaN stays NaN (not filled)
        return out

    def build(
        self, panel: pd.DataFrame, rebalance_dates: pd.DatetimeIndex, *,
        providers: dict, exchange: str = "XNYS",
    ) -> pd.DataFrame:
        """Raw features joined to the panel's (date, ticker) keys, then normalized per date."""
        raw = self.compute_raw(panel, rebalance_dates, providers=providers, exchange=exchange)
        keys = panel[[COL_DATE, COL_TICKER]].drop_duplicates()
        merged = keys.merge(raw, on=[COL_DATE, COL_TICKER], how="left")
        return self.normalize(merged).sort_values([COL_DATE, COL_TICKER]).reset_index(drop=True)

    # ---- data-quality + leakage report ----
    def quality_report(
        self, features: pd.DataFrame, panel: pd.DataFrame, targets: list[str]
    ) -> dict:
        rep: dict = {"family": self.name, "n_rows": int(len(features)), "features": {}}
        tgt_panel = panel[[COL_DATE, COL_TICKER, *targets]]
        for spec in self.specs:
            f = spec.name
            cov = float(features[f].notna().mean())
            merged = features[[COL_DATE, COL_TICKER, f]].merge(tgt_panel, on=[COL_DATE, COL_TICKER])
            ics = {}
            for tgt in targets:
                _, summ = information_coefficient(merged, f, tgt)
                ics[tgt] = {"mean_ic": summ.mean_ic, "t_stat": summ.t_stat,
                            "ic_ir": summ.ic_ir, "frac_positive": summ.frac_positive}
            rep["features"][f] = {
                "description": spec.description, "as_of": spec.as_of,
                "missing_rule": spec.missing_rule,
                "coverage": cov, "missing_rate": 1.0 - cov, "diagnostic_ic": ics,
            }
        return rep

    # ---- feature-store IO with provenance ----
    def save(self, features: pd.DataFrame, cache: ParquetCache, *, panel_meta: dict) -> Path:
        path = cache.put("features", self.name, features)
        sidecar = path.with_name(f"{self.name}_meta.json")
        prov = {
            "family": self.name,
            "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "rows": int(len(features)),
            "feature_columns": self.feature_names,
            "normalized_columns": [c for f in self.feature_names for c in (f + "_z", f + "_rank")],
            "specs": [asdict(s) for s in self.specs],
            "source_panel": panel_meta,   # {path, rows, names} so features can't desync from a panel
        }
        sidecar.write_text(json.dumps(prov, indent=2))
        return path
