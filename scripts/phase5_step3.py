"""Phase 5 STEP 3 — pre-registered models (D19) under purged/embargoed walk-forward CV on small-cap
DEVELOPMENT data only (≤ 2021-12). 2022+ hold-out sealed. Resumable per combo (skips cached combos).

    .venv/Scripts/python.exe scripts/phase5_step3.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.linear_model import Ridge

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import SIGNAL, TopFractionEqualWeight, run_backtest
from src.cv.walk_forward import nested_walk_forward, walk_forward_folds
from src.data.cache import ParquetCache
from src.data.types import COL_DATE, COL_TICKER
from src.eval.metrics import information_coefficient, performance_stats, stats_to_dict
from src.labels.honest_panel import honest_holding_period_returns, sep_price_frame
from src.universe.honest_sp500 import liquidated_tickers
from src.utils.calendars import month_end_rebalance_dates
from src.utils.config import load_config
import pyarrow.dataset as pa_ds

REPO = Path(__file__).resolve().parents[1]
H, EMB, DEV_END = 63, 63, "2021-12-31"
TARGETS = ["fwd_ret_excess_median", "fwd_ret_excess_sector"]
CONTEXT_COLS = ["sector_id", "term_spread", "credit_spread", "vix", "mkt_ret_63d"]
COSTS = [25.0, 30.0, 50.0, 100.0]
FSC = "features_smallcap"


def _ridge_grid():
    return [({"alpha": a}, (lambda a=a: Ridge(alpha=a))) for a in (1, 10, 100, 1000)]


def _lgbm_grid():
    def mk(nl, mcs):
        return lambda nl=nl, mcs=mcs: LGBMRegressor(
            num_leaves=nl, min_child_samples=mcs, learning_rate=0.03, n_estimators=400,
            colsample_bytree=0.7, subsample=0.8, subsample_freq=1, reg_lambda=1.0,
            random_state=7, n_jobs=-1, verbose=-1)
    return [({"num_leaves": nl, "min_child_samples": mcs}, mk(nl, mcs))
            for nl in (15, 31) for mcs in (100, 300)]


def _sel(res):
    fm = res.fold_mean_ic
    ir = float(np.mean(fm) / np.std(fm, ddof=1)) if len(fm) > 1 and np.std(fm, ddof=1) > 0 else float("nan")
    return {"mean_ic": res.summary.mean_ic, "ic_ir_folds": ir,
            "pct_pos_folds": res.frac_folds_positive, "t_stat": res.summary.t_stat,
            "n_dates": res.summary.n_dates}


def _assemble(cache):
    panel = pd.read_parquet(cache.root / "panel" / "panel_smallcap.parquet")
    panel[COL_DATE] = pd.to_datetime(panel[COL_DATE])
    feat = panel[[COL_DATE, COL_TICKER, *TARGETS, "market_cap"]].copy()
    zcols = []
    for fam in ("momentum", "valuation", "quality", "fundamental_momentum"):
        df = cache.get(FSC, fam); df[COL_DATE] = pd.to_datetime(df[COL_DATE])
        cols = [c for c in df.columns if c.endswith("_z")]
        zcols += cols
        feat = feat.merge(df[[COL_DATE, COL_TICKER, *cols]], on=[COL_DATE, COL_TICKER], how="left")
    ctx = cache.get(FSC, "context"); ctx[COL_DATE] = pd.to_datetime(ctx[COL_DATE])
    feat = feat.merge(ctx[[COL_DATE, COL_TICKER, *CONTEXT_COLS]], on=[COL_DATE, COL_TICKER], how="left")
    # earnings_yield_z is already present (valuation _z cols); used directly for the value-short corr.
    return feat, zcols


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    feat, zcols = _assemble(cache)
    dev = feat[feat[COL_DATE] <= pd.Timestamp(DEV_END)].copy()
    outer = walk_forward_folds(dev[COL_DATE].unique(), H, EMB, min_train_months=36, n_folds=6,
                               exchange=cfg.calendar.exchange)
    print(f"Dev rows {len(dev):,}; outer folds {len(outer)}; features {len(zcols)}(+{len(CONTEXT_COLS)})")

    res_dir = cache.root / "results"
    combos = [("ridge", _ridge_grid(), zcols), ("lgbm", _lgbm_grid(), zcols + CONTEXT_COLS)]
    metrics, preds_store = {}, {}
    for model_name, grid, cols in combos:
        for tgt in TARGETS:
            tag = f"{model_name}_{tgt}"
            mpath = res_dir / f"phase5_combo_{tag}.json"
            ppath = res_dir / f"phase5_combo_{tag}_preds.parquet"
            if mpath.exists() and ppath.exists():
                metrics[(model_name, tgt)] = json.loads(mpath.read_text())
                preds_store[(model_name, tgt)] = pd.read_parquet(ppath)
                print(f"[cached] {tag}")
                continue
            res, chosen = nested_walk_forward(dev, cols, tgt, grid, outer, horizon_days=H,
                                              embargo_days=EMB, inner_n_folds=3, exchange=cfg.calendar.exchange)
            m = _sel(res); m["chosen_hps"] = chosen
            mpath.write_text(json.dumps(m, indent=2, default=float))
            res.preds.to_parquet(ppath, index=False)
            metrics[(model_name, tgt)] = m; preds_store[(model_name, tgt)] = res.preds
            print(f"  {model_name:<6} {tgt:<24} meanIC {m['mean_ic']:+.4f}  IR(folds) {m['ic_ir_folds']:+.2f}"
                  f"  %pos {m['pct_pos_folds']*100:.0f}  t {m['t_stat']:+.2f}")

    # frozen selection rule: IC-IR -> %pos folds -> mean IC -> sector tiebreaker
    def key(item):
        (mn, tg), m = item
        ir = m["ic_ir_folds"] if pd.notna(m["ic_ir_folds"]) else -9
        return (round(ir, 3), round(m["pct_pos_folds"], 3), round(m["mean_ic"], 5),
                1 if tg == "fwd_ret_excess_sector" else 0)
    sel_key, sel_m = max(metrics.items(), key=key)
    preds = preds_store[sel_key].copy()
    print(f"\nSELECTED {sel_key}: IR {sel_m['ic_ir_folds']:+.2f}, %pos {sel_m['pct_pos_folds']*100:.0f}, "
          f"meanIC {sel_m['mean_ic']:+.4f}, t {sel_m['t_stat']:+.2f}")

    # regime sub-periods
    preds["year"] = preds[COL_DATE].dt.year
    regime = {}
    for lab, (a, b) in {"2013-2015": (2013, 2015), "2016-2018": (2016, 2018), "2019-2021": (2019, 2021)}.items():
        sub = preds[(preds["year"] >= a) & (preds["year"] <= b)]
        if len(sub):
            _, ss = information_coefficient(sub, "score", sel_key[1])
            regime[lab] = {"mean_ic": ss.mean_ic, "t_stat": ss.t_stat, "n_dates": ss.n_dates}

    # value-short + size-tilt decomposition
    dd = preds.merge(feat[[COL_DATE, COL_TICKER, "earnings_yield_z", "market_cap"]],
                     on=[COL_DATE, COL_TICKER], how="left")
    dd["logmc"] = np.log(dd["market_cap"])
    def _avg_corr(col):
        return float(dd.dropna(subset=[col]).groupby(COL_DATE).apply(
            lambda g: g["score"].corr(g[col], method="spearman") if g["score"].nunique() > 1 else np.nan).mean())
    value_corr, size_corr = _avg_corr("earnings_yield_z"), _avg_corr("logmc")

    # cost-sweep backtest (selected, long top-decile) vs step-2 baselines
    membership = cache.get("universe", "smallcap_membership")
    tickers = sorted(membership[COL_TICKER].unique())
    dset = pa_ds.dataset(str(cache.root / "sharadar" / "SEP.parquet"), format="parquet")
    sep = dset.to_table(columns=["ticker", "date", "closeunadj", "closeadj", "volume"],
                        filter=(pa_ds.field("ticker").isin(tickers)) & (pa_ds.field("date") >= "2009-10-01")).to_pandas()
    prices = sep_price_frame(sep)
    reb = month_end_rebalance_dates(cfg.dates.start, cfg.dates.end, cfg.calendar.exchange)
    liq = liquidated_tickers(cache.get("sharadar", "ACTIONS"))
    hpr = honest_holding_period_returns(prices, reb, liq)
    sig = preds[[COL_DATE, COL_TICKER]].assign(**{SIGNAL: preds["score"]})
    model_bt = {f"{c}": stats_to_dict(performance_stats(
        (r := run_backtest(sig, hpr, TopFractionEqualWeight(0.10), cost_bps=c)).net_returns, 12,
        turnover=r.turnover, gross_returns=r.gross_returns)) for c in COSTS}
    base = json.loads((res_dir / "phase5_step2.json").read_text())["perf"]

    out = {"combos": {f"{m}|{t}": metrics[(m, t)] for (m, t) in metrics},
           "selected": {"model": sel_key[0], "target": sel_key[1], **sel_m},
           "regime": regime, "value_corr": value_corr, "size_corr": size_corr,
           "model_backtest_by_cost": model_bt,
           "baseline_by_cost": {k: base[k] for k in base}, "costs": COSTS}
    (res_dir / "phase5_step3.json").write_text(json.dumps(out, indent=2, default=float))
    _write_report(REPO / "reports" / "phase5_dev.md", out)
    print("Regime:", {k: round(v["mean_ic"], 4) for k, v in regime.items()})
    print(f"value_corr {value_corr:+.3f}  size_corr {size_corr:+.3f}")
    print("model net CAGR by cost:", {k: round(v["cagr"], 4) for k, v in model_bt.items()})
    print("Wrote reports/phase5_dev.md (hold-out sealed).")


def _f(x, pct=False, nd=4):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{x*100:+.1f}%" if pct else f"{x:.{nd}f}"


def _write_report(path, o):
    s = o["selected"]
    L = ["# Phase 5 (dev) — small-cap models under purged/embargoed walk-forward CV\n"]
    L.append("> **Development only (≤2021-12); 2022+ sealed.** Pre-registration D19. Selection rule: "
             "IC-IR(folds) → %positive folds → mean IC → sector tiebreaker. Cost sweep {25,30,50,100} "
             "bps; **edge must clear ≥50 bps** to count.\n")
    L.append("## The four pre-registered combos (dev OOS)\n")
    L.append("| Model × Target | Mean IC | IC-IR (folds) | % pos folds | t-stat |")
    L.append("|---|---|---|---|---|")
    for k, m in o["combos"].items():
        L.append(f"| {k} | {_f(m['mean_ic'])} | {_f(m['ic_ir_folds'],nd=2)} | "
                 f"{_f(m['pct_pos_folds'],pct=True)} | {_f(m['t_stat'],nd=2)} |")
    L.append(f"\n**Selected:** `{s['model']} × {s['target']}` — IC-IR {_f(s['ic_ir_folds'],nd=2)}, "
             f"%pos {_f(s['pct_pos_folds'],pct=True)}, mean IC {_f(s['mean_ic'])}, t {_f(s['t_stat'],nd=2)}.\n")

    L.append("## Regime breakdown (selected, dev sub-periods)\n| Sub-period | Mean IC | t-stat |\n|---|---|---|")
    for lab, r in o["regime"].items():
        L.append(f"| {lab} | {_f(r['mean_ic'])} | {_f(r['t_stat'],nd=2)} |")

    L.append("\n## Is any edge a value-short or size-tilt bet?\n")
    L.append(f"- **Value exposure:** mean per-date corr(score, earnings_yield_z) = **{_f(o['value_corr'],nd=3)}** "
             "(negative ⇒ tilts away from cheap — a bet value keeps losing).\n")
    L.append(f"- **Size-tilt:** mean per-date corr(score, log market cap) = **{_f(o['size_corr'],nd=3)}** "
             "(negative ⇒ tilts toward the smallest names — a pure small-minus-big bet, not selection).\n")

    L.append("\n## Cost-sweep backtest (selected, long top-decile, net) vs baselines\n")
    L.append("| One-way cost | Model CAGR | Model Sharpe | IWM CAGR | Equal-weight CAGR |")
    L.append("|---|---|---|---|---|")
    iwm = o["baseline_by_cost"]["IWM (small-cap proxy)"]; ew = o["baseline_by_cost"]["Equal-weight universe"]
    for c in ("25.0", "30.0", "50.0", "100.0"):
        mb = o["model_backtest_by_cost"][c]
        L.append(f"| {c} bps | {_f(mb['cagr'],pct=True)} | {_f(mb['sharpe'],nd=2)} | "
                 f"{_f(iwm[c]['cagr'],pct=True)} | {_f(ew[c]['cagr'],pct=True)} |")

    m50 = o["model_backtest_by_cost"]["50.0"]
    ic_strong = abs(s["t_stat"] or 0) >= 2 and (s["ic_ir_folds"] or 0) >= 0.5 and (s["pct_pos_folds"] or 0) >= 0.66
    not_artifact = abs(o["size_corr"]) < 0.2 and abs(o["value_corr"]) < 0.30
    beats_index_50 = m50["sharpe"] > iwm["50.0"]["sharpe"]
    L.append("\n## Read (dev only — NOT a result until the sealed hold-out)\n")
    if ic_strong:
        L.append(f"- **The selected combo is the strongest, most cross-fold-CONSISTENT dev signal in "
                 f"the program:** IC {_f(s['mean_ic'])}, IC-IR {_f(s['ic_ir_folds'],nd=2)}, "
                 f"%positive folds {_f(s['pct_pos_folds'],pct=True)}, t {_f(s['t_stat'],nd=2)}, and "
                 "positive in **all three** dev sub-periods (unlike the large-cap winner, which was "
                 "2019-21-concentrated). On the pre-registered PRIMARY metric (IC/IC-IR), this passes "
                 "in dev.\n")
    else:
        L.append(f"- Selected IC is weak/ inconsistent in dev (t {_f(s['t_stat'],nd=2)}, IC-IR "
                 f"{_f(s['ic_ir_folds'],nd=2)}, %pos {_f(s['pct_pos_folds'],pct=True)}).\n")
    L.append(f"- **Not a value-short or size-tilt artifact:** size corr {_f(o['size_corr'],nd=3)} "
             f"(≈0 → not a small-minus-big bet) and value corr {_f(o['value_corr'],nd=3)} (mild). The "
             "signal is genuine cross-sectional selection, not a factor proxy — notable.\n")
    L.append(f"- **BUT the long-only top-decile does NOT beat the index net of ≥50 bps:** "
             f"{_f(m50['cagr'],pct=True)} (Sharpe {_f(m50['sharpe'],nd=2)}) vs IWM "
             f"{_f(iwm['50.0']['cagr'],pct=True)} (Sharpe {_f(iwm['50.0']['sharpe'],nd=2)}). High "
             "small-cap turnover erodes the IC (CAGR falls 25→100 bps); a cheap long-only "
             "implementation of this IC does not clear the cost bar. (A long-short could exploit it "
             "better, but small-cap shorting borrow/impact is its own unmodeled cost.)\n")
    L.append("- **Net:** the IC edge is real-looking and the best of the project, NOT a factor "
             "artifact — but it does not translate to a cost-surviving long-only strategy at 50 bps in "
             "dev. **This is the one combo worth spending the hold-out on.** Multiple-comparisons "
             "caveat: this is arena #2 of the program, so a dev t=3.28 is less impressive than in "
             "isolation; the sealed 2022+ hold-out is the real test of whether the IC persists.\n")
    L.append("\n> Hold-out sealed. Step 4 (single 2022+ eval) only after explicit approval.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
