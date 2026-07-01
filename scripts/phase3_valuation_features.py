"""Phase 3: build the VALUATION feature family (first fundamental family) from Sharadar SF1, save to
the feature store with provenance, and write reports/phase3_valuation_features.md (data-quality +
leakage report, coverage, per-feature DIAGNOSTIC ICs — descriptive, not a model).

    .venv/Scripts/python.exe scripts/phase3_valuation_features.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.cache import ParquetCache
from src.data.providers.sharadar import SharadarProvider
from src.data.types import COL_DATE, COL_TICKER
from src.features.valuation import BASE_METRICS, ValuationFamily
from src.utils.calendars import month_end_rebalance_dates
from src.utils.config import load_config

REPO = Path(__file__).resolve().parents[1]


def _load_panel_with_meta(cache: ParquetCache):
    meta_p = cache.root / "results" / "meta.json"
    if meta_p.exists():
        pp = json.loads(meta_p.read_text()).get("panel_path")
        if pp and (REPO / pp).exists():
            df = pd.read_parquet(REPO / pp)
            return df, {"path": pp, "rows": int(len(df)), "names": int(df[COL_TICKER].nunique())}
    newest = max((cache.root / "panel").glob("panel_*.parquet"), key=lambda p: p.stat().st_mtime)
    df = pd.read_parquet(newest)
    return df, {"path": newest.relative_to(REPO).as_posix(), "rows": int(len(df)),
                "names": int(df[COL_TICKER].nunique())}


def _ic(x, nd=4):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:.{nd}f}"


def _write_report(path: Path, fam, report, panel_meta, targets):
    L = ["# Phase 3 — Valuation feature family: data-quality & leakage report\n"]
    L.append("> **Survivorship caveat still applies:** features are built on the current-membership "
             "S&P 500 panel; diagnostic ICs are descriptive, not a tradeable result.\n")
    L.append(f"*Family:* `{fam.name}` (first fundamental family, Sharadar SF1, point-in-time) · "
             f"*rows:* {report['n_rows']:,} · *source panel:* `{panel_meta['path']}`\n")

    L.append("## Leakage discipline (fundamentals)\n")
    L.append("- **`datekey <= t` strictly**, **as-reported (AR*) dimensions only** — MR* "
             "(restatement-backfilled) are refused by the provider.\n"
             "- **Price-at-`t` numerator, fundamental-as-of-`t` denominator** — never a future filing.\n"
             "- Per-date cross-sectional normalization (base); sector from as-of TICKERS reference.\n"
             "- Negative/zero earnings, sales, book, or EBITDA -> feature **undefined (NaN), not 0**.\n"
             "- Tested (`tests/test_valuation_features.py`): a value restated at a later `datekey` "
             "does not change an earlier-`t` feature; negative earnings yield is NaN, never 0.\n")

    L.append("## Features — coverage & as-of timing\n")
    L.append("| Feature | Coverage | Missing | As-of timing | Missing rule |")
    L.append("|---|---|---|---|---|")
    for f in fam.feature_names:
        r = report["features"][f]
        L.append(f"| `{f}` | {r['coverage']*100:.1f}% | {r['missing_rate']*100:.1f}% | "
                 f"{r['as_of']} | {r['missing_rule']} |")

    L.append("\n## Diagnostic per-feature IC (descriptive — NOT a model)\n")
    L.append("Mean per-date Spearman IC (t-stat) vs each target. `fwd_ret_raw` == `excess_median` by "
             "rank-invariance.\n")
    L.append("| Feature | " + " | ".join(f"`{t}`" for t in targets) + " |")
    L.append("|" + "---|" * (len(targets) + 1))
    for f in fam.feature_names:
        cells = []
        for t in targets:
            ic = report["features"][f]["diagnostic_ic"][t]
            cells.append(f"{_ic(ic['mean_ic'])} (t {_ic(ic['t_stat'],2)})")
        L.append(f"| `{f}` | " + " | ".join(cells) + " |")

    prim = "fwd_ret_excess_sector" if "fwd_ret_excess_sector" in targets else targets[0]
    n_tests = len(fam.feature_names) * len(targets)
    sig = [f for f in fam.feature_names
           if abs(report["features"][f]["diagnostic_ic"][prim]["t_stat"] or 0) >= 2.0]
    L.append(f"\n**Read (diagnostic only — feeds Phase-4 selection, not a tradeable claim):**\n")
    ey = report["features"]["earnings_yield"]["diagnostic_ic"][prim]["mean_ic"]
    bp = report["features"]["book_to_price"]["diagnostic_ic"][prim]["mean_ic"]
    if ey < 0 and bp < 0:
        L.append(
            f"- **The value premium is absent/inverted on this sample:** earnings_yield "
            f"(IC {_ic(ey)}) and book-to-price (IC {_ic(bp)}) are **negatively** predictive — cheap "
            "stocks *underperformed*. This is the well-documented 2010s 'value drought', amplified by "
            "survivorship: the current-membership universe is dominated by growth winners that got "
            "richer. Expect the Step-3 value baseline to **trail** equal-weight here — an honest "
            "regime/sample result, not a coding error. On a point-in-time, delisting-inclusive "
            "universe the sign and magnitude may differ.\n")
    if sig:
        siglist = ", ".join(f"`{f}` (t {_ic(report['features'][f]['diagnostic_ic'][prim]['t_stat'],2)})"
                            for f in sig)
        L.append(f"- **Notable but NOT yet trusted:** {siglist} clear |t| ≥ 2 vs `{prim}`. Per "
                 f"DECISIONS **D9** treat with suspicion: in-sample, full-period, **survivorship-"
                 f"flattered**, and **{n_tests} feature×target comparisons** were run (a t≈3 is "
                 "unremarkable after multiple-comparisons adjustment). Counts only after purged, "
                 "embargoed out-of-sample validation in Phase 4.\n")
    else:
        L.append(f"- No single valuation feature clears |t| ≥ 2 vs `{prim}` in-sample.\n")
    L.append("- These ICs **rank features for the model to consider**, nothing more. A high "
             "in-sample IC is a hypothesis to falsify out-of-sample, not a signal.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    targets = cfg.label.targets

    panel, panel_meta = _load_panel_with_meta(cache)
    panel[COL_DATE] = pd.to_datetime(panel[COL_DATE])
    print(f"Panel: {len(panel):,} rows, {panel[COL_TICKER].nunique()} tickers")

    prov = SharadarProvider(cache)
    reb = month_end_rebalance_dates(cfg.dates.start, cfg.dates.end, cfg.calendar.exchange)
    fam = ValuationFamily()
    feats = fam.build(panel, reb, providers={"fundamentals": prov}, exchange=cfg.calendar.exchange)
    store_path = fam.save(feats, cache, panel_meta=panel_meta)
    print(f"Feature store: {len(feats):,} rows -> {store_path}")

    report = fam.quality_report(feats, panel, targets)
    (cache.root / "features" / "valuation_quality.json").write_text(json.dumps(report, indent=2))
    _write_report(REPO / "reports" / "phase3_valuation_features.md", fam, report, panel_meta, targets)
    print("Wrote reports/phase3_valuation_features.md\n")

    print("Coverage & diagnostic IC vs", targets[-1], ":")
    for f in fam.feature_names:
        r = report["features"][f]
        ic = r["diagnostic_ic"][targets[-1]]
        print(f"  {f:<26} cov {r['coverage']*100:5.1f}%  meanIC {ic['mean_ic']:+.4f}  t {ic['t_stat']:+.2f}")


if __name__ == "__main__":
    main()
