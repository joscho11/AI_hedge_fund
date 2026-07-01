"""Phase 3 finish: build the quality, fundamental-momentum, and context feature families on the
HONEST panel; save stores (+provenance), write per-family reports with diagnostic ICs (cross-
sectional families only), and tally the total feature surface going into Phase 4.

    .venv/Scripts/python.exe scripts/phase3_build_families.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.cache import ParquetCache
from src.data.providers.fred_macro import FredMacroProvider
from src.data.providers.sharadar import SharadarProvider
from src.data.providers.yfinance_prices import YFinancePriceProvider
from src.data.types import COL_TICKER
from src.features.context import ContextFamily
from src.features.fundamental_momentum import FundamentalMomentumFamily
from src.features.quality import QualityFamily
from src.features.valuation import ValuationFamily
from src.features.momentum import MomentumFamily
from src.utils.calendars import month_end_rebalance_dates
from src.utils.config import load_config

REPO = Path(__file__).resolve().parents[1]
TARGETS = ["fwd_ret_raw", "fwd_ret_excess_median", "fwd_ret_excess_sector"]


def _ic(x, nd=4):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:.{nd}f}"


def _xs_report(path, fam, report, panel_meta, headliner_note=""):
    L = [f"# Phase 3 — {fam.name} feature family (honest universe)\n"]
    L.append("> **Backtested, in-sample, honest universe (survivorship-addressed).** Diagnostic ICs "
             "are exploratory — they count only if they survive Phase-4 purged/embargoed OOS (D9).\n")
    L.append(f"*Family:* `{fam.name}` · *features:* {len(fam.feature_names)} · *rows:* "
             f"{report['n_rows']:,} · *source panel:* `{panel_meta['path']}`\n")
    if headliner_note:
        L.append(headliner_note + "\n")
    L.append("## Features — coverage & as-of timing\n")
    L.append("| Feature | Coverage | Missing | As-of timing | Missing rule |")
    L.append("|---|---|---|---|---|")
    for f in fam.feature_names:
        r = report["features"][f]
        L.append(f"| `{f}` | {r['coverage']*100:.1f}% | {r['missing_rate']*100:.1f}% | "
                 f"{r['as_of']} | {r['missing_rule']} |")
    L.append("\n## Diagnostic per-feature IC (descriptive — NOT a model)\n")
    L.append("| Feature | " + " | ".join(f"`{t}`" for t in TARGETS) + " |")
    L.append("|" + "---|" * (len(TARGETS) + 1))
    for f in fam.feature_names:
        cells = [f"{_ic(report['features'][f]['diagnostic_ic'][t]['mean_ic'])} "
                 f"(t {_ic(report['features'][f]['diagnostic_ic'][t]['t_stat'],2)})" for t in TARGETS]
        L.append(f"| `{f}` | " + " | ".join(cells) + " |")
    prim = "fwd_ret_excess_sector"
    n_tests = len(fam.feature_names) * len(TARGETS)
    sig = [f for f in fam.feature_names
           if abs(report["features"][f]["diagnostic_ic"][prim]["t_stat"] or 0) >= 2.0]
    if sig:
        s = ", ".join(f"`{f}` (t {_ic(report['features'][f]['diagnostic_ic'][prim]['t_stat'],2)})" for f in sig)
        L.append(f"\n**Notable in-sample (NOT yet trusted):** {s} clear |t|≥2 vs `{prim}`. With "
                 f"{n_tests} comparisons in this family alone, treat as hypotheses for Phase-4 OOS, "
                 "not results (D9).\n")
    else:
        L.append(f"\n**No feature clears |t|≥2 vs `{prim}` in-sample** ({n_tests} comparisons).\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


def _context_report(path, fam, feats, panel_meta):
    L = [f"# Phase 3 — context (sector/macro) family (honest universe)\n"]
    L.append("> Conditioning inputs for the model, **not** standalone ranking signals.\n")
    L.append(f"*Family:* `{fam.name}` · *features:* {len(fam.feature_names)} · "
             f"*source panel:* `{panel_meta['path']}`\n")
    L.append("**No cross-sectional IC is reported here, by design:** the macro features "
             "(`term_spread`, `credit_spread`, `vix`, `mkt_ret_63d`) are **date-level** — constant "
             "across names on a given date — so their cross-sectional IC is ~0 by construction; they "
             "are regime-conditioning inputs for model interactions. `sector_id` is categorical. "
             "Sector-relative ranking content already lives in the valuation/quality families.\n")
    L.append("## Features — coverage & as-of timing\n")
    L.append("| Feature | Coverage | Kind | As-of timing |")
    L.append("|---|---|---|---|")
    for spec in fam.specs:
        cov = feats[spec.name].notna().mean()
        kind = "cross-sectional (categorical)" if spec.name == "sector_id" else "date-level"
        L.append(f"| `{spec.name}` | {cov*100:.1f}% | {kind} | {spec.as_of} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    panel = pd.read_parquet(cache.root / "panel" / "panel_honest.parquet")
    panel_meta = {"path": "data_cache/panel/panel_honest.parquet", "rows": int(len(panel)),
                  "names": int(panel[COL_TICKER].nunique())}
    reb = month_end_rebalance_dates(cfg.dates.start, cfg.dates.end, cfg.calendar.exchange)
    prov = SharadarProvider(cache)
    print(f"Honest panel: {len(panel):,} rows, {panel_meta['names']} names")

    counts = {"momentum": len(MomentumFamily.specs), "valuation": len(ValuationFamily.specs)}

    # ---- cross-sectional fundamental families ----
    headliners = {
        "fundamental_momentum": (
            "**Headliner family.** Best prior for real signal ('improving fundamentals before price "
            "reprices'). NOTE: analyst estimate revisions are absent — SF1 is reported fundamentals, "
            "not estimates; no proxy is fabricated. Any in-sample IC below is a hypothesis for "
            "Phase-4 OOS, not a result."),
    }
    for fam in (QualityFamily(), FundamentalMomentumFamily()):
        feats = fam.build(panel, reb, providers={"fundamentals": prov}, exchange=cfg.calendar.exchange)
        fam.save(feats, cache, panel_meta=panel_meta)
        report = fam.quality_report(feats, panel, TARGETS)
        (cache.root / "features" / f"{fam.name}_quality.json").write_text(json.dumps(report, indent=2))
        _xs_report(REPO / "reports" / f"phase3_{fam.name}_features.md", fam, report, panel_meta,
                   headliners.get(fam.name, ""))
        counts[fam.name] = len(fam.feature_names)
        print(f"\n{fam.name}: {len(fam.feature_names)} features, {len(feats):,} rows")
        for f in fam.feature_names:
            ic = report["features"][f]["diagnostic_ic"][TARGETS[-1]]
            print(f"  {f:<24} cov {report['features'][f]['coverage']*100:5.1f}%  "
                  f"meanIC {ic['mean_ic']:+.4f}  t {ic['t_stat']:+.2f}")

    # ---- context (conditioning; no IC) ----
    macro = FredMacroProvider(cache, realtime_only=cfg.availability.macro_realtime_only)
    spy = YFinancePriceProvider(cache).get_prices(["SPY"], cfg.dates.start, cfg.dates.end)
    ctx = ContextFamily()
    cfeats = ctx.build(panel, reb, providers={"fundamentals": prov, "macro": macro, "spy": spy},
                       exchange=cfg.calendar.exchange)
    ctx.save(cfeats, cache, panel_meta=panel_meta)
    _context_report(REPO / "reports" / "phase3_context_features.md", ctx, cfeats, panel_meta)
    counts["context"] = len(ctx.feature_names)
    print(f"\ncontext: {len(ctx.feature_names)} conditioning features (no cross-sectional IC)")

    xs_total = counts["momentum"] + counts["valuation"] + counts["quality"] + counts["fundamental_momentum"]
    print("\n=== Feature surface going into Phase 4 ===")
    for k, v in counts.items():
        print(f"  {k:<22} {v}")
    print(f"  {'CROSS-SECTIONAL TOTAL':<22} {xs_total}  (+ {counts['context']} context conditioning)")
    print(f"  multiple-comparisons surface (xs features x 3 targets): {xs_total*3}")


if __name__ == "__main__":
    main()
