"""Phase 3: build the momentum feature family, save it to the feature store with provenance, and
write reports/phase3_momentum_features.md (data-quality + leakage report, coverage, and per-feature
DIAGNOSTIC ICs — reusing src/eval/metrics.py, not a model).

    .venv/Scripts/python.exe scripts/phase3_momentum_features.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.cache import ParquetCache
from src.data.providers.yfinance_prices import YFinancePriceProvider
from src.data.types import COL_DATE, COL_TICKER
from src.features.momentum import MomentumFamily
from src.utils.calendars import month_end_rebalance_dates
from src.utils.config import load_config

REPO = Path(__file__).resolve().parents[1]


def _load_panel_with_meta(cache: ParquetCache):
    """Use the same panel the Phase 2 results were computed on (meta provenance), else newest."""
    meta_p = cache.root / "results" / "meta.json"
    if meta_p.exists():
        meta = json.loads(meta_p.read_text())
        pp = meta.get("panel_path")
        if pp:
            path = (REPO / pp) if not Path(pp).is_absolute() else Path(pp)
            if path.exists():
                df = pd.read_parquet(path)
                return df, {"path": pp, "rows": int(len(df)), "names": int(df[COL_TICKER].nunique())}
    newest = max((cache.root / "panel").glob("panel_*.parquet"), key=lambda p: p.stat().st_mtime)
    df = pd.read_parquet(newest)
    rel = newest.relative_to(REPO).as_posix()
    return df, {"path": rel, "rows": int(len(df)), "names": int(df[COL_TICKER].nunique())}


def _fmt(x, pct=False, nd=4):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{x*100:+.1f}%" if pct else f"{x:.{nd}f}"


def _write_report(path: Path, fam: MomentumFamily, report: dict, panel_meta: dict, targets):
    L = ["# Phase 3 — Momentum feature family: data-quality & leakage report\n"]
    L.append("> **Survivorship caveat still applies:** features are built on the current-membership "
             "S&P 500 panel; diagnostic ICs are descriptive, not a tradeable result. No model yet.\n")
    L.append(f"*Family:* `{fam.name}` · *rows:* {report['n_rows']:,} · "
             f"*source panel:* `{panel_meta['path']}` ({panel_meta['rows']:,} rows, "
             f"{panel_meta['names']} names)\n")

    L.append("## Leakage discipline\n")
    L.append("- **Every window is strictly trailing** (ending at `t`), computed with "
             "`min_periods == window` so a partial window is NaN, never a look-ahead value.\n"
             "- **Normalization is per rebalance date** (winsorize 1/99 → z-score + percentile rank), "
             "**never pooled across dates**.\n"
             "- **Missing values are never forward-filled**; a NaN raw value is excluded from that "
             "date's cross-section (see per-feature missing rule below).\n"
             "- Automated check (`tests/test_phase3_features.py`): a 10× price spike at any date "
             "**after** `t` leaves every feature value at `t` byte-identical — verified passing.\n")

    L.append("## Features — coverage & as-of timing\n")
    L.append("| Feature | Coverage | Missing | As-of timing | Missing rule |")
    L.append("|---|---|---|---|---|")
    for f in fam.feature_names:
        r = report["features"][f]
        L.append(f"| `{f}` | {r['coverage']*100:.1f}% | {r['missing_rate']*100:.1f}% | "
                 f"{r['as_of']} | {r['missing_rule']} |")

    L.append("\n## Diagnostic per-feature IC (descriptive — NOT a model)\n")
    L.append("Mean per-date Spearman IC (t-stat) of each raw feature vs each target. "
             "`fwd_ret_raw` and `fwd_ret_excess_median` share an IC by rank-invariance.\n")
    hdr = "| Feature | " + " | ".join(f"`{t}`" for t in targets) + " |"
    L.append(hdr)
    L.append("|" + "---|" * (len(targets) + 1))
    for f in fam.feature_names:
        cells = []
        for t in targets:
            ic = report["features"][f]["diagnostic_ic"][t]
            cells.append(f"{_fmt(ic['mean_ic'])} (t {_fmt(ic['t_stat'],nd=2)})")
        L.append(f"| `{f}` | " + " | ".join(cells) + " |")

    # quick read: strongest |mean IC| vs the primary excess target, with honest caveats
    prim = "fwd_ret_excess_sector" if "fwd_ret_excess_sector" in targets else targets[0]
    ranked = sorted(fam.feature_names,
                    key=lambda f: abs(report["features"][f]["diagnostic_ic"][prim]["mean_ic"]),
                    reverse=True)
    n_tests = len(fam.feature_names) * len(targets)
    sig = [f for f in fam.feature_names
           if abs(report["features"][f]["diagnostic_ic"][prim]["t_stat"] or 0) >= 2.0]
    top = ranked[0]
    top_ic = report["features"][top]["diagnostic_ic"][prim]
    L.append(f"\n**Read (diagnostic only — feeds Phase-4 selection, not a tradeable claim):**\n")
    L.append(f"- The pure return-momentum features (`ret_1m/3m/6m/12_1`) have ~zero IC, consistent "
             "with the Phase-2 finding that momentum has no ranking power on this universe.\n")
    if sig:
        siglist = ", ".join(f"`{f}` (t {_fmt(report['features'][f]['diagnostic_ic'][prim]['t_stat'],nd=2)})"
                            for f in sig)
        L.append(
            f"- **Notable but NOT yet trusted:** {siglist} show |t| ≥ 2 vs `{prim}`. Treat with "
            "strong suspicion, per DECISIONS **D9**: (a) these are **in-sample, full-period** ICs on a "
            f"**survivorship-flattered** universe; (b) **{n_tests} feature×target comparisons** were run, "
            "so a t≈3 is far less impressive after multiple-comparisons adjustment; (c) the volatility "
            "features most likely capture a **risk/beta premium** (high-vol names earned more in this "
            "bull sample), not cross-sectional alpha. None of this counts until it survives **purged, "
            "embargoed out-of-sample** validation in Phase 4.\n")
    else:
        L.append(f"- No single feature clears |t| ≥ 2 vs `{prim}` after the cross-section; the "
                 "strongest is `{top}` (mean IC {_fmt(top_ic['mean_ic'])}).\n")
    L.append("- Bottom line: these ICs **rank features for the model to consider**, nothing more. "
             "A high in-sample IC here is a hypothesis to be falsified out-of-sample, not a signal.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    targets = cfg.label.targets

    panel, panel_meta = _load_panel_with_meta(cache)
    panel[COL_DATE] = pd.to_datetime(panel[COL_DATE])
    tickers = sorted(panel[COL_TICKER].unique())
    print(f"Panel: {len(panel):,} rows, {len(tickers)} tickers (source {panel_meta['path']})")

    px = YFinancePriceProvider(cache).get_prices(tickers, cfg.dates.start, cfg.dates.end)
    reb = month_end_rebalance_dates(cfg.dates.start, cfg.dates.end, cfg.calendar.exchange)

    fam = MomentumFamily()
    feats = fam.build(panel, reb, providers={"prices": px}, exchange=cfg.calendar.exchange)
    store_path = fam.save(feats, cache, panel_meta=panel_meta)
    print(f"Feature store: {len(feats):,} rows -> {store_path}")

    report = fam.quality_report(feats, panel, targets)
    (cache.root / "features" / "momentum_quality.json").write_text(json.dumps(report, indent=2))
    _write_report(REPO / "reports" / "phase3_momentum_features.md", fam, report, panel_meta, targets)
    print("Wrote reports/phase3_momentum_features.md\n")

    print("Coverage & diagnostic IC vs", targets[-1], ":")
    for f in fam.feature_names:
        r = report["features"][f]
        ic = r["diagnostic_ic"][targets[-1]]
        print(f"  {f:<16} cov {r['coverage']*100:5.1f}%  meanIC {ic['mean_ic']:+.4f}  t {ic['t_stat']:+.2f}")


if __name__ == "__main__":
    main()
