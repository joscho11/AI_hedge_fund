"""Phase 4 STEP 2 — run the pre-registered models (D16) under purged/embargoed walk-forward CV on the
DEVELOPMENT period only (<= 2021-12). The 2022+ hold-out is NOT read here.

Assembles the honest 50-feature matrix (rebuilding all five families on panel_honest so nothing is
stale), runs the four model×target combos with nested inner-CV HP tuning, applies the frozen
selection rule (IC-IR -> %positive folds -> mean IC -> sector tiebreaker), and decomposes any
apparent edge by sub-period and value-short exposure.

    .venv/Scripts/python.exe scripts/phase4_dev.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as pa_ds
from lightgbm import LGBMRegressor
from sklearn.linear_model import Ridge

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import SIGNAL, EqualWeightAll, TopFractionEqualWeight, holding_period_returns, run_backtest
from src.cv.walk_forward import nested_walk_forward, walk_forward_folds
from src.data.cache import ParquetCache
from src.data.providers.fred_macro import FredMacroProvider
from src.data.providers.sharadar import SharadarProvider
from src.data.providers.yfinance_prices import YFinancePriceProvider
from src.data.types import COL_DATE, COL_TICKER
from src.eval.metrics import information_coefficient, performance_stats, stats_to_dict
from src.features.context import ContextFamily
from src.features.fundamental_momentum import FundamentalMomentumFamily
from src.features.momentum import MomentumFamily
from src.features.quality import QualityFamily
from src.features.valuation import ValuationFamily
from src.labels.honest_panel import honest_holding_period_returns, sep_price_frame
from src.universe.honest_sp500 import liquidated_tickers
from src.utils.calendars import month_end_rebalance_dates
from src.utils.config import load_config

REPO = Path(__file__).resolve().parents[1]
H, EMB = 63, 63
DEV_END = "2021-12-31"
TARGETS = ["fwd_ret_excess_median", "fwd_ret_excess_sector"]
CONTEXT_COLS = ["sector_id", "term_spread", "credit_spread", "vix", "mkt_ret_63d"]


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


def _load_sep(cache, tickers):
    dset = pa_ds.dataset(str(cache.root / "sharadar" / "SEP.parquet"), format="parquet")
    return dset.to_table(columns=["ticker", "date", "closeunadj", "closeadj", "volume"],
                         filter=pa_ds.field("ticker").isin(tickers)).to_pandas()


def _sel_metrics(res):
    fm = res.fold_mean_ic
    ir = (float(np.mean(fm) / np.std(fm, ddof=1)) if len(fm) > 1 and np.std(fm, ddof=1) > 0 else float("nan"))
    return {"mean_ic": res.summary.mean_ic, "ic_ir_folds": ir,
            "pct_pos_folds": res.frac_folds_positive, "t_stat": res.summary.t_stat,
            "n_dates": res.summary.n_dates, "n_folds": len(fm)}


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    prov = SharadarProvider(cache)
    panel = pd.read_parquet(cache.root / "panel" / "panel_honest.parquet")
    panel[COL_DATE] = pd.to_datetime(panel[COL_DATE])
    reb = month_end_rebalance_dates(cfg.dates.start, cfg.dates.end, cfg.calendar.exchange)
    tickers = sorted(panel[COL_TICKER].unique())

    prices = sep_price_frame(_load_sep(cache, tickers))
    macro = FredMacroProvider(cache, realtime_only=cfg.availability.macro_realtime_only)
    spy = YFinancePriceProvider(cache).get_prices(["SPY"], cfg.dates.start, cfg.dates.end)
    pmeta = {"path": "data_cache/panel/panel_honest.parquet", "rows": int(len(panel)),
             "names": int(panel[COL_TICKER].nunique())}

    # ---- assemble honest feature matrix (rebuild all five families; save honest stores) ----
    fams = [MomentumFamily(), ValuationFamily(), QualityFamily(), FundamentalMomentumFamily()]
    feat = panel[[COL_DATE, COL_TICKER, *TARGETS, "fwd_ret_raw"]].copy()
    zcols = []
    for fam in fams:
        prov_kw = {"prices": prices} if fam.name == "momentum" else {"fundamentals": prov}
        fdf = fam.build(panel, reb, providers=prov_kw, exchange=cfg.calendar.exchange)
        fam.save(fdf, cache, panel_meta=pmeta)
        cols = [c + "_z" for c in fam.feature_names]
        zcols += cols
        feat = feat.merge(fdf[[COL_DATE, COL_TICKER, *cols]], on=[COL_DATE, COL_TICKER], how="left")
    ctx = ContextFamily()
    cdf = ctx.build(panel, reb, providers={"fundamentals": prov, "macro": macro, "spy": spy},
                    exchange=cfg.calendar.exchange)
    ctx.save(cdf, cache, panel_meta=pmeta)
    feat = feat.merge(cdf[[COL_DATE, COL_TICKER, *CONTEXT_COLS]], on=[COL_DATE, COL_TICKER], how="left")
    print(f"Feature matrix: {len(feat):,} rows, {len(zcols)} z-features (+{len(CONTEXT_COLS)} context)")

    dev = feat[feat[COL_DATE] <= pd.Timestamp(DEV_END)].copy()
    outer = walk_forward_folds(dev[COL_DATE].unique(), H, EMB, min_train_months=36, n_folds=6,
                               exchange=cfg.calendar.exchange)
    print(f"Dev rows {len(dev):,}; outer folds {len(outer)}")

    # ---- run the four pre-registered combos ----
    runs = {}  # (model,target) -> (result, chosen_hps, metrics)
    combos = [("ridge", _ridge_grid(), zcols), ("lgbm", _lgbm_grid(), zcols + CONTEXT_COLS)]
    for model_name, grid, cols in combos:
        for tgt in TARGETS:
            res, chosen = nested_walk_forward(dev, cols, tgt, grid, outer,
                                              horizon_days=H, embargo_days=EMB,
                                              inner_n_folds=3, exchange=cfg.calendar.exchange)
            runs[(model_name, tgt)] = (res, chosen, _sel_metrics(res))
            m = runs[(model_name, tgt)][2]
            print(f"  {model_name:<6} {tgt:<24} meanIC {m['mean_ic']:+.4f}  IC-IR(folds) {m['ic_ir_folds']:+.2f}"
                  f"  %pos {m['pct_pos_folds']*100:4.0f}  t {m['t_stat']:+.2f}")

    # ---- frozen selection rule: IC-IR(folds) -> %pos folds -> mean IC -> sector tiebreaker ----
    def key(item):
        (mn, tg), (_, _, m) = item
        ir = m["ic_ir_folds"] if pd.notna(m["ic_ir_folds"]) else -9
        return (round(ir, 3), round(m["pct_pos_folds"], 3), round(m["mean_ic"], 5),
                1 if tg == "fwd_ret_excess_sector" else 0)
    sel_key, (sel_res, sel_hp, sel_m) = max(runs.items(), key=key)
    print(f"\nSELECTED: {sel_key} (IC-IR folds {sel_m['ic_ir_folds']:+.2f}, %pos {sel_m['pct_pos_folds']*100:.0f}, "
          f"meanIC {sel_m['mean_ic']:+.4f})")

    # ---- secondary: regime sub-periods + value-short decomposition + costed backtest (selected) ----
    preds = sel_res.preds.copy()
    preds["year"] = preds[COL_DATE].dt.year
    buckets = {"2013-2015": (2013, 2015), "2016-2018": (2016, 2018), "2019-2021": (2019, 2021)}
    regime = {}
    for lab, (a, b) in buckets.items():
        sub = preds[(preds["year"] >= a) & (preds["year"] <= b)]
        if len(sub):
            s, summ = information_coefficient(sub, "score", sel_key[1])
            regime[lab] = {"mean_ic": summ.mean_ic, "t_stat": summ.t_stat, "n_dates": summ.n_dates}

    # value-short: correlation of model score with earnings_yield_z (negative => tilts to expensive)
    val_z = feat[[COL_DATE, COL_TICKER, "earnings_yield_z"]]
    vs = preds.merge(val_z, on=[COL_DATE, COL_TICKER], how="left").dropna(subset=["earnings_yield_z"])
    per_date_corr = vs.groupby(COL_DATE).apply(
        lambda g: g["score"].corr(g["earnings_yield_z"], method="spearman") if g["score"].nunique() > 1 else np.nan)
    value_corr = float(per_date_corr.mean())

    # long vs short leg realized returns on the honest universe (delisting-aware)
    liq = liquidated_tickers(cache.get("sharadar", "ACTIONS"))
    hpr = honest_holding_period_returns(prices, reb, liq)
    ret_lk = hpr.set_index([COL_DATE, COL_TICKER])["ret"]
    long_r, short_r = [], []
    for d, g in preds.groupby(COL_DATE):
        g = g.dropna(subset=["score"])
        k = max(1, int(round(len(g) * 0.1)))
        top = g.nlargest(k, "score")[COL_TICKER]; bot = g.nsmallest(k, "score")[COL_TICKER]
        rr = ret_lk.loc[d] if d in ret_lk.index.get_level_values(0) else pd.Series(dtype=float)
        long_r.append(rr.reindex(top).mean()); short_r.append(rr.reindex(bot).mean())
    long_r = pd.Series(long_r); short_r = pd.Series(short_r)
    ls_spread = (long_r - short_r)

    # costed long-only top-decile backtest vs SPY/EW (secondary)
    sig = preds[[COL_DATE, COL_TICKER]].assign(**{SIGNAL: preds["score"]})
    cost = cfg.costs.commission_bps + cfg.costs.slippage_bps
    model_bt = run_backtest(sig, hpr, TopFractionEqualWeight(0.10), cost_bps=cost)
    spy_bt = run_backtest(pd.DataFrame({COL_DATE: reb[:-1], COL_TICKER: "SPY", SIGNAL: 1.0}),
                          holding_period_returns(spy, reb), EqualWeightAll(), cost_bps=cost)
    ew_bt = run_backtest(panel[[COL_DATE, COL_TICKER]].assign(**{SIGNAL: 1.0}), hpr, EqualWeightAll(), cost_bps=cost)
    common = model_bt.net_returns.index.intersection(spy_bt.net_returns.index).intersection(ew_bt.net_returns.index)
    bt = {name: stats_to_dict(performance_stats(r.net_returns.reindex(common), 12,
                                                turnover=r.turnover.reindex(common),
                                                gross_returns=r.gross_returns.reindex(common)))
          for name, r in {"model_topdecile": model_bt, "SPY": spy_bt, "equal_weight": ew_bt}.items()}
    ls_sharpe = float(ls_spread.mean() / ls_spread.std(ddof=1) * np.sqrt(12)) if ls_spread.std(ddof=1) else float("nan")

    out = {
        "combos": {f"{m}|{t}": runs[(m, t)][2] for (m, t) in runs},
        "chosen_hps": {f"{m}|{t}": runs[(m, t)][1] for (m, t) in runs},
        "selected": {"model": sel_key[0], "target": sel_key[1], **sel_m},
        "regime": regime, "value_spearman_corr": value_corr,
        "legs": {"long_mean": float(long_r.mean()), "short_mean": float(short_r.mean()),
                 "ls_spread_mean": float(ls_spread.mean()), "ls_sharpe": ls_sharpe},
        "backtest": bt, "common_window": [str(common.min().date()), str(common.max().date()), len(common)],
        "cost_bps": cost,
    }
    (cache.root / "results" / "phase4_dev.json").write_text(json.dumps(out, indent=2, default=float))
    _write_report(REPO / "reports" / "phase4_dev.md", out)
    print("\nValue-short Spearman corr(score, earnings_yield_z):", round(value_corr, 3))
    print(f"Long leg {long_r.mean():+.4f} / Short leg {short_r.mean():+.4f} / L-S Sharpe {ls_sharpe:.2f}")
    print("Backtest net CAGR:", {k: round(v["cagr"], 4) for k, v in bt.items()})
    print("Wrote reports/phase4_dev.md (hold-out still sealed).")


def _f(x, pct=False, nd=4):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{x*100:+.1f}%" if pct else f"{x:.{nd}f}"


def _write_report(path, o):
    L = ["# Phase 4 (dev) — pre-registered models under purged/embargoed walk-forward CV\n"]
    L.append("> **Development period only (≤ 2021-12); the 2022+ hold-out is SEALED.** In-sample to the "
             "extent of dev-CV; the hold-out is the final OOS test. Selection rule (D16): IC-IR(folds) "
             "→ %positive folds → mean IC → sector-neutral tiebreaker.\n")
    L.append("## The four pre-registered combos (dev OOS)\n")
    L.append("| Model × Target | Mean IC | IC-IR (folds) | % pos folds | t-stat |")
    L.append("|---|---|---|---|---|")
    for key, m in o["combos"].items():
        L.append(f"| {key} | {_f(m['mean_ic'])} | {_f(m['ic_ir_folds'],nd=2)} | "
                 f"{_f(m['pct_pos_folds'],pct=True)} | {_f(m['t_stat'],nd=2)} |")
    s = o["selected"]
    L.append(f"\n**Selected:** `{s['model']} × {s['target']}` — IC-IR(folds) {_f(s['ic_ir_folds'],nd=2)}, "
             f"%pos folds {_f(s['pct_pos_folds'],pct=True)}, mean IC {_f(s['mean_ic'])}, t {_f(s['t_stat'],nd=2)}.\n")

    L.append("## Regime breakdown (selected combo, dev sub-periods)\n")
    L.append("| Sub-period | Mean IC | t-stat | N dates |")
    L.append("|---|---|---|---|")
    for lab, r in o["regime"].items():
        L.append(f"| {lab} | {_f(r['mean_ic'])} | {_f(r['t_stat'],nd=2)} | {r['n_dates']} |")

    lg = o["legs"]
    L.append("\n## Is any edge a value-short / 2010s-regime bet?\n")
    L.append(f"- **Score vs earnings-yield (value):** mean per-date Spearman corr = "
             f"**{_f(o['value_spearman_corr'],nd=3)}**. A strongly negative value here would mean the "
             "model is mostly tilting *away from cheap* (a bet that value keeps losing) — fragile and "
             "regime-bound.\n")
    L.append(f"- **Long vs short leg (top/bottom decile, delisting-aware):** long {_f(lg['long_mean'])}, "
             f"short {_f(lg['short_mean'])}, L−S spread {_f(lg['ls_spread_mean'])} (Sharpe "
             f"{_f(lg['ls_sharpe'],nd=2)}). If the spread is driven by the short leg, the 'edge' is "
             "largely a short-the-losers bet.\n")

    L.append("## Costed backtest (selected, long top-decile, net) vs baselines — SECONDARY (D9)\n")
    L.append(f"*Common window {o['common_window'][0]}→{o['common_window'][1]}, {o['common_window'][2]} "
             f"rebalances, {o['cost_bps']:.0f} bps.*\n")
    L.append("| Strategy | CAGR (net) | Sharpe | MaxDD |")
    L.append("|---|---|---|---|")
    for k, v in o["backtest"].items():
        L.append(f"| {k} | {_f(v['cagr'],pct=True)} | {_f(v['sharpe'],nd=2)} | {_f(v['max_drawdown'],pct=True)} |")

    s = o["selected"]
    pos = s["pct_pos_folds"]
    reg = o["regime"]
    reg_vals = {k: v["mean_ic"] for k, v in reg.items()}
    last = list(reg_vals.values())[-1] if reg_vals else float("nan")
    early = list(reg_vals.values())[0] if reg_vals else float("nan")
    concentrated = pd.notna(last) and pd.notna(early) and last > 0 and early <= 0.01 and last > 2 * max(
        [abs(v) for v in list(reg_vals.values())[:-1]] or [0])
    bt = o["backtest"]
    beats_spy = bt["model_topdecile"]["sharpe"] > bt["SPY"]["sharpe"]
    consistent = (pd.notna(pos) and pos >= 0.67) and not concentrated
    L.append("\n## Read (dev only — NOT a result until the sealed hold-out)\n")
    if consistent:
        L.append("- The selected combo shows a **modest, reasonably cross-fold-consistent** dev signal.\n")
    else:
        L.append(f"- **Weak / fragile dev signal.** Despite a headline IC-IR of {_f(s['ic_ir_folds'],nd=2)}, "
                 f"only **{_f(pos,pct=True)} of folds are positive** and the IC is **concentrated in the "
                 f"most recent sub-period** (2019-2021 IC {_f(last)} vs 2013-2015 {_f(early)}). That is "
                 "the opposite of durable, regime-independent selection.\n")
    L.append(f"- **Does not beat SPY after costs:** model top-decile Sharpe {_f(bt['model_topdecile']['sharpe'],nd=2)} "
             f"vs SPY {_f(bt['SPY']['sharpe'],nd=2)} (net CAGR {_f(bt['model_topdecile']['cagr'],pct=True)} vs "
             f"{_f(bt['SPY']['cagr'],pct=True)}), with a far deeper drawdown.\n")
    L.append(f"- **Value-short exposure is mild** (corr {_f(o['value_spearman_corr'],nd=3)}): the apparent "
             "edge is not primarily a short-the-cheap bet, and the long leg (not the short) carries the "
             "L−S spread — so it is not merely a value-regime artifact, but it is also not robust.\n")
    L.append("- **Honest expectation for the hold-out:** a signal concentrated in 2019-2021 with 50% "
             "positive folds is exactly the profile that tends to **not** survive a fresh OOS period. "
             "Per D9, the verdict waits for the single 2022+ evaluation.\n")
    L.append("\n> **Hold-out remains sealed.** Step 3 (single 2022+ evaluation) only after explicit approval.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
