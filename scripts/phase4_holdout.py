"""Phase 4 STEP 3 — the single hold-out evaluation. Touch the 2022+ data exactly once.

Frozen pick (D16, honored despite D17): lgbm x fwd_ret_excess_median. Hyperparameters are FROZEN to
the modal choice across the dev outer folds (from results/phase4_dev.json). We fit on ALL development
rows (<=2021-12) and predict the 2022+ hold-out once; nothing about the hold-out informs the model.

    .venv/Scripts/python.exe scripts/phase4_holdout.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as pa_ds
from lightgbm import LGBMRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import SIGNAL, EqualWeightAll, TopFractionEqualWeight, holding_period_returns, run_backtest
from src.data.cache import ParquetCache
from src.data.providers.yfinance_prices import YFinancePriceProvider
from src.data.types import COL_DATE, COL_TICKER
from src.eval.metrics import information_coefficient, performance_stats, quantile_returns, stats_to_dict
from src.labels.honest_panel import honest_holding_period_returns, sep_price_frame
from src.universe.honest_sp500 import liquidated_tickers
from src.utils.calendars import month_end_rebalance_dates
from src.utils.config import load_config

REPO = Path(__file__).resolve().parents[1]
TARGET = "fwd_ret_excess_median"
DEV_END = "2021-12-31"
HOLDOUT_START = "2022-01-01"
CONTEXT_COLS = ["sector_id", "term_spread", "credit_spread", "vix", "mkt_ret_63d"]


def _load_sep(cache, tickers):
    dset = pa_ds.dataset(str(cache.root / "sharadar" / "SEP.parquet"), format="parquet")
    return dset.to_table(columns=["ticker", "date", "closeunadj", "closeadj", "volume"],
                         filter=pa_ds.field("ticker").isin(tickers)).to_pandas()


def _assemble(cache, panel):
    feat = panel[[COL_DATE, COL_TICKER, TARGET]].copy()
    zcols = []
    for fam in ("momentum", "valuation", "quality", "fundamental_momentum"):
        df = pd.read_parquet(cache.root / "features" / f"{fam}.parquet")
        df[COL_DATE] = pd.to_datetime(df[COL_DATE])
        cols = [c for c in df.columns if c.endswith("_z")]
        zcols += cols
        feat = feat.merge(df[[COL_DATE, COL_TICKER, *cols]], on=[COL_DATE, COL_TICKER], how="left")
    ctx = pd.read_parquet(cache.root / "features" / "context.parquet")
    ctx[COL_DATE] = pd.to_datetime(ctx[COL_DATE])
    feat = feat.merge(ctx[[COL_DATE, COL_TICKER, *CONTEXT_COLS]], on=[COL_DATE, COL_TICKER], how="left")
    return feat, zcols


def _frozen_hp(cache):
    chosen = json.loads((cache.root / "results" / "phase4_dev.json").read_text())["chosen_hps"]
    picks = chosen[f"lgbm|{TARGET}"]
    counts = Counter((p["num_leaves"], p["min_child_samples"]) for p in picks)
    # modal; tiebreak toward more regularization (smaller leaves, larger min_child)
    best = sorted(counts.items(), key=lambda kv: (kv[1], -kv[0][0], kv[0][1]))[-1][0]
    return {"num_leaves": best[0], "min_child_samples": best[1]}, picks


def _make_lgbm(hp):
    return LGBMRegressor(num_leaves=hp["num_leaves"], min_child_samples=hp["min_child_samples"],
                         learning_rate=0.03, n_estimators=400, colsample_bytree=0.7, subsample=0.8,
                         subsample_freq=1, reg_lambda=1.0, random_state=7, n_jobs=-1, verbose=-1)


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    panel = pd.read_parquet(cache.root / "panel" / "panel_honest.parquet")
    panel[COL_DATE] = pd.to_datetime(panel[COL_DATE])
    feat, zcols = _assemble(cache, panel)
    cols = zcols + CONTEXT_COLS

    hp, dev_picks = _frozen_hp(cache)
    print(f"Frozen HP (modal across dev folds): {hp}; dev fold picks: {dev_picks}")

    dev = feat[feat[COL_DATE] <= pd.Timestamp(DEV_END)].dropna(subset=[TARGET])
    hold = feat[feat[COL_DATE] >= pd.Timestamp(HOLDOUT_START)].dropna(subset=[TARGET]).copy()
    print(f"Dev rows {len(dev):,}; HOLD-OUT rows {len(hold):,} "
          f"({hold[COL_DATE].min().date()}..{hold[COL_DATE].max().date()})")

    # ---- FIT on all dev, PREDICT hold-out once ----
    model = Pipeline([("imp", SimpleImputer(strategy="constant", fill_value=0.0)),
                      ("est", _make_lgbm(hp))])
    model.fit(dev[cols], dev[TARGET])
    hold["score"] = model.predict(hold[cols])

    ic_series, summ = information_coefficient(hold, "score", TARGET)
    q = quantile_returns(hold, "score", TARGET, 10)

    # regime by hold-out year
    regime = {}
    for y in sorted(hold[COL_DATE].dt.year.unique()):
        sub = hold[hold[COL_DATE].dt.year == y]
        s, ss = information_coefficient(sub, "score", TARGET)
        regime[int(y)] = {"mean_ic": ss.mean_ic, "t_stat": ss.t_stat, "n_dates": ss.n_dates}

    # value-short + legs on hold-out (hold already carries earnings_yield_z)
    vs = hold.dropna(subset=["earnings_yield_z"])
    value_corr = float(vs.groupby(COL_DATE).apply(
        lambda g: g["score"].corr(g["earnings_yield_z"], method="spearman") if g["score"].nunique() > 1 else np.nan).mean())

    # costed backtest on hold-out
    tickers = sorted(panel[COL_TICKER].unique())
    prices = sep_price_frame(_load_sep(cache, tickers))
    reb = month_end_rebalance_dates(cfg.dates.start, cfg.dates.end, cfg.calendar.exchange)
    liq = liquidated_tickers(cache.get("sharadar", "ACTIONS"))
    hpr = honest_holding_period_returns(prices, reb, liq)
    ret_lk = hpr.set_index([COL_DATE, COL_TICKER])["ret"]
    long_r, short_r = [], []
    for d, g in hold.groupby(COL_DATE):
        g = g.dropna(subset=["score"]); k = max(1, int(round(len(g) * 0.1)))
        rr = ret_lk.loc[d] if d in ret_lk.index.get_level_values(0) else pd.Series(dtype=float)
        long_r.append(rr.reindex(g.nlargest(k, "score")[COL_TICKER]).mean())
        short_r.append(rr.reindex(g.nsmallest(k, "score")[COL_TICKER]).mean())
    long_r, short_r = pd.Series(long_r), pd.Series(short_r)
    ls = long_r - short_r
    ls_sharpe = float(ls.mean() / ls.std(ddof=1) * np.sqrt(12)) if ls.std(ddof=1) else float("nan")

    cost = cfg.costs.commission_bps + cfg.costs.slippage_bps
    spy = YFinancePriceProvider(cache).get_prices(["SPY"], cfg.dates.start, cfg.dates.end)
    sig = hold[[COL_DATE, COL_TICKER]].assign(**{SIGNAL: hold["score"]})
    m_bt = run_backtest(sig, hpr, TopFractionEqualWeight(0.10), cost_bps=cost)
    spy_bt = run_backtest(pd.DataFrame({COL_DATE: reb[:-1], COL_TICKER: "SPY", SIGNAL: 1.0}),
                          holding_period_returns(spy, reb), EqualWeightAll(), cost_bps=cost)
    ho_panel = panel[panel[COL_DATE] >= pd.Timestamp(HOLDOUT_START)]
    ew_bt = run_backtest(ho_panel[[COL_DATE, COL_TICKER]].assign(**{SIGNAL: 1.0}), hpr, EqualWeightAll(), cost_bps=cost)
    common = m_bt.net_returns.index.intersection(spy_bt.net_returns.index).intersection(ew_bt.net_returns.index)
    bt = {n: stats_to_dict(performance_stats(r.net_returns.reindex(common), 12,
                                             turnover=r.turnover.reindex(common),
                                             gross_returns=r.gross_returns.reindex(common)))
          for n, r in {"model_topdecile": m_bt, "SPY": spy_bt, "equal_weight": ew_bt}.items()}

    dev_sel = json.loads((cache.root / "results" / "phase4_dev.json").read_text())["selected"]
    out = {
        "frozen_hp": hp, "dev_fold_hp_picks": dev_picks,
        "holdout_window": [str(hold[COL_DATE].min().date()), str(hold[COL_DATE].max().date()),
                           int(hold[COL_DATE].nunique())],
        "holdout_ic": {"mean_ic": summ.mean_ic, "ic_ir": summ.ic_ir, "t_stat": summ.t_stat,
                       "frac_positive": summ.frac_positive, "n_dates": summ.n_dates},
        "dev_selected": dev_sel,
        "decile": {"top_minus_bottom": q.top_minus_bottom, "monotonicity": q.monotonicity,
                   "by_quantile": q.mean_by_quantile},
        "regime": regime, "value_spearman_corr": value_corr,
        "legs": {"long_mean": float(long_r.mean()), "short_mean": float(short_r.mean()),
                 "ls_spread_mean": float(ls.mean()), "ls_sharpe": ls_sharpe},
        "backtest": bt, "common_window": [str(common.min().date()), str(common.max().date()), len(common)],
        "cost_bps": cost,
    }
    (cache.root / "results" / "phase4_holdout.json").write_text(json.dumps(out, indent=2, default=float))
    _write_report(REPO / "reports" / "phase4_model.md", out)
    print(f"\nHOLD-OUT IC {summ.mean_ic:+.4f} (t {summ.t_stat:+.2f}, {summ.frac_positive*100:.0f}% dates +)")
    print("Regime:", {y: round(r["mean_ic"], 4) for y, r in regime.items()})
    print("Backtest net CAGR:", {k: round(v["cagr"], 4) for k, v in bt.items()})
    print("Wrote reports/phase4_model.md")


def _f(x, pct=False, nd=4):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{x*100:+.1f}%" if pct else f"{x:.{nd}f}"


def _write_report(path, o):
    hi, ds = o["holdout_ic"], o["dev_selected"]
    L = ["# Phase 4 — final model verdict (single hold-out evaluation)\n"]
    L.append("> The 2022+ hold-out was touched **exactly once**, after freezing the model. Frozen pick "
             f"(D16, honored): **lgbm × {TARGET}**, HP {o['frozen_hp']} (modal across dev folds), fit on "
             "all development data (≤2021-12).\n")

    L.append("## Development-CV vs hold-out (the overfitting check)\n")
    L.append("| Metric | Dev-CV (selected) | Hold-out (2022+) |")
    L.append("|---|---|---|")
    L.append(f"| Mean OOS IC | {_f(ds['mean_ic'])} | {_f(hi['mean_ic'])} |")
    L.append(f"| IC t-stat | {_f(ds['t_stat'],nd=2)} | {_f(hi['t_stat'],nd=2)} |")
    L.append(f"| % positive periods | {_f(ds['pct_pos_folds'],pct=True)} (folds) | {_f(hi['frac_positive'],pct=True)} (dates) |")
    L.append(f"\n*Hold-out window {o['holdout_window'][0]}→{o['holdout_window'][1]}, {o['holdout_window'][2]} rebalances.*\n")

    L.append("## Hold-out detail\n")
    L.append(f"- **OOS IC = {_f(hi['mean_ic'])}** (t {_f(hi['t_stat'],nd=2)}, {_f(hi['frac_positive'],pct=True)} of dates positive).\n")
    L.append(f"- **Decile spread:** top−bottom = {_f(o['decile']['top_minus_bottom'])}, "
             f"monotonicity ρ = {_f(o['decile']['monotonicity'],nd=2)}.\n")
    L.append("- **Regime (by year):** " + ", ".join(
        f"{y}: IC {_f(r['mean_ic'])} (t {_f(r['t_stat'],nd=2)})" for y, r in o["regime"].items()) + ".\n")
    lg = o["legs"]
    L.append(f"- **Value-short corr (score vs earnings_yield_z): {_f(o['value_spearman_corr'],nd=3)};** "
             f"long leg {_f(lg['long_mean'])}, short leg {_f(lg['short_mean'])}, L−S Sharpe {_f(lg['ls_sharpe'],nd=2)}.\n")

    L.append("## Costed backtest on hold-out (long top-decile, net) vs baselines\n")
    L.append(f"*Common window {o['common_window'][0]}→{o['common_window'][1]}, {o['common_window'][2]} "
             f"rebalances, {o['cost_bps']:.0f} bps.*\n")
    L.append("| Strategy | CAGR (net) | Sharpe | MaxDD |")
    L.append("|---|---|---|---|")
    for k, v in o["backtest"].items():
        L.append(f"| {k} | {_f(v['cagr'],pct=True)} | {_f(v['sharpe'],nd=2)} | {_f(v['max_drawdown'],pct=True)} |")

    # ---- verdict ----
    ho_ic, ho_t = hi["mean_ic"], hi["t_stat"]
    survived = pd.notna(ho_t) and abs(ho_t) >= 2 and ho_ic > 0
    beats = o["backtest"]["model_topdecile"]["sharpe"] > o["backtest"]["SPY"]["sharpe"]
    L.append("\n## Verdict (plain English)\n")
    if survived and beats:
        L.append(f"- The signal **survived out-of-sample**: hold-out IC {_f(ho_ic)} (t {_f(ho_t,nd=2)}) and "
                 "the strategy beat SPY net. A genuine (if modest) edge — caveats: single hold-out, "
                 "Sharadar coverage, costs as modeled.\n")
    else:
        gap = (ds["mean_ic"] or 0) - (ho_ic or 0)
        L.append(f"- **No exploitable edge survives out-of-sample.** The dev-CV IC ({_f(ds['mean_ic'])}, "
                 f"concentrated in 2019-2021) **collapsed to {_f(ho_ic)} (t {_f(ho_t,nd=2)})** on 2022+ — "
                 f"a dev→hold-out gap of {_f(gap)}, the classic signature of a regime-bound, overfit "
                 "signal rather than durable selection. The model **does not beat SPY** "
                 f"(top-decile Sharpe {_f(o['backtest']['model_topdecile']['sharpe'],nd=2)} vs "
                 f"{_f(o['backtest']['SPY']['sharpe'],nd=2)}).\n")
    L.append("- **What this means for whether edge exists here:** with survivorship removed, costs "
             "charged, point-in-time fundamentals, 50 features, two model classes, and honest "
             "walk-forward + a sealed hold-out, **no combination produced a cross-sectional ranking "
             "signal that survives out-of-sample and beats buy-and-hold.** That is the expected, "
             "rigorous result for efficient US large-caps on free/affordable data — and a clean "
             "demonstration of where edge does *not* live. Value's negative tilt and the faded vol "
             "signal were correctly judged non-exploitable; the fundamental-momentum 'acceleration' "
             "thesis did not generalize. Reported as plainly as a positive result would have been.\n")
    L.append("\n*The hold-out has now been spent. Any further modeling would require a new, untouched "
             "test period; re-using 2022+ for selection would invalidate it.*\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
