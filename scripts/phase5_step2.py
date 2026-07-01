"""Phase 5 STEP 2 — delisting-aware small-cap panel + five feature families + baselines, DEVELOPMENT
ONLY (rebalance dates <= 2021-12). The 2022+ hold-out is sealed (no baseline trades or metrics use
it). Resumable: skips the panel/feature stores that already exist.

    .venv/Scripts/python.exe scripts/phase5_step2.py

Outputs: data_cache/panel/panel_smallcap.parquet, data_cache/features_smallcap/<family>.parquet,
reports/phase5_smallcap_baselines.md (dev-only).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as pa_ds

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import SIGNAL, EqualWeightAll, TopFractionEqualWeight, holding_period_returns, run_backtest
from src.baselines.signals import momentum_12_1
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
from src.labels.forward_returns import COL_FWD_RAW, add_excess_targets
from src.labels.honest_panel import delisting_aware_forward_returns, honest_holding_period_returns, sep_price_frame
from src.universe.honest_sp500 import liquidated_tickers
from src.utils.calendars import month_end_rebalance_dates
from src.utils.config import load_config

REPO = Path(__file__).resolve().parents[1]
DEV_END = "2021-12-31"
COSTS = [25.0, 30.0, 50.0, 100.0]
TARGETS = ["fwd_ret_excess_median", "fwd_ret_excess_sector"]
FSC = "features_smallcap"


def _load_sep(cache, tickers, start="2009-10-01"):
    dset = pa_ds.dataset(str(cache.root / "sharadar" / "SEP.parquet"), format="parquet")
    flt = (pa_ds.field("ticker").isin(tickers)) & (pa_ds.field("date") >= start)
    return dset.to_table(columns=["ticker", "date", "closeunadj", "closeadj", "volume"], filter=flt).to_pandas()


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    prov = SharadarProvider(cache)
    tk = cache.get("sharadar", "TICKERS")
    reb = month_end_rebalance_dates(cfg.dates.start, cfg.dates.end, cfg.calendar.exchange)
    membership = cache.get("universe", "smallcap_membership")
    membership[COL_DATE] = pd.to_datetime(membership[COL_DATE])
    tickers = sorted(membership[COL_TICKER].unique())
    prices = sep_price_frame(_load_sep(cache, tickers))
    liq = liquidated_tickers(cache.get("sharadar", "ACTIONS"))
    sector_map = tk.drop_duplicates("ticker", keep="last").set_index("ticker")["sector"].to_dict()
    pmeta = {"path": "data_cache/panel/panel_smallcap.parquet"}

    # ---- delisting-aware panel ----
    if cache.has("panel", "panel_smallcap"):
        panel = cache.get("panel", "panel_smallcap"); panel[COL_DATE] = pd.to_datetime(panel[COL_DATE])
        print(f"[cached] panel_smallcap: {len(panel):,} rows")
    else:
        fwd = delisting_aware_forward_returns(prices, membership[[COL_DATE, COL_TICKER]],
                                              cfg.label.horizon_days, liq, cfg.calendar.exchange)
        panel = membership.merge(fwd, on=[COL_DATE, COL_TICKER], how="inner")
        panel = add_excess_targets(panel, sector_map).dropna(subset=[COL_FWD_RAW, "fwd_ret_excess_median"])
        panel = panel.sort_values([COL_DATE, COL_TICKER]).reset_index(drop=True)
        cache.put("panel", "panel_smallcap", panel)
        print(f"panel_smallcap built: {len(panel):,} rows, {panel[COL_TICKER].nunique()} names")
    pmeta.update(rows=int(len(panel)), names=int(panel[COL_TICKER].nunique()))

    # ---- five feature families (saved under features_smallcap; resumable) ----
    macro = FredMacroProvider(cache, realtime_only=cfg.availability.macro_realtime_only)
    spy = YFinancePriceProvider(cache).get_prices(["SPY"], cfg.dates.start, cfg.dates.end)
    fam_specs = [(MomentumFamily(), {"prices": prices}),
                 (ValuationFamily(), {"fundamentals": prov}),
                 (QualityFamily(), {"fundamentals": prov}),
                 (FundamentalMomentumFamily(), {"fundamentals": prov}),
                 (ContextFamily(), {"fundamentals": prov, "macro": macro, "spy": spy})]
    feats = {}
    for fam, kw in fam_specs:
        if cache.has(FSC, fam.name):
            feats[fam.name] = cache.get(FSC, fam.name)
            print(f"[cached] {fam.name}")
        else:
            df = fam.build(panel, reb, providers=kw, exchange=cfg.calendar.exchange)
            cache.put(FSC, fam.name, df)
            (cache.root / FSC / f"{fam.name}_meta.json").write_text(json.dumps(
                {"family": fam.name, "rows": int(len(df)), "source_panel": pmeta}, indent=2))
            feats[fam.name] = df
            print(f"built {fam.name}: {len(df):,} rows")

    # ---- baselines (DEV ONLY) ----
    dev_dates = reb[reb <= pd.Timestamp(DEV_END)]
    dev_panel = panel[panel[COL_DATE] <= pd.Timestamp(DEV_END)]
    hpr = honest_holding_period_returns(prices, reb, liq)
    iwm = YFinancePriceProvider(cache).get_prices(["IWM"], cfg.dates.start, cfg.dates.end)
    hpr_iwm = holding_period_returns(iwm, reb)

    mom = momentum_12_1(prices, reb, cfg.calendar.exchange)
    mom_scored = dev_panel.merge(mom, on=[COL_DATE, COL_TICKER], how="inner")
    val = feats["valuation"][[COL_DATE, COL_TICKER, "earnings_yield"]].dropna()
    val[COL_DATE] = pd.to_datetime(val[COL_DATE])
    val_scored = dev_panel.merge(val, on=[COL_DATE, COL_TICKER], how="inner")

    def bt(sig_df, signal_col, hold, policy, cost):
        s = sig_df[[COL_DATE, COL_TICKER]].copy(); s[SIGNAL] = sig_df[signal_col]
        s = s[s[COL_DATE] <= pd.Timestamp(DEV_END)]
        return run_backtest(s, hold, policy, cost_bps=cost)

    strategies = {
        "IWM (small-cap proxy)": ("idx", hpr_iwm, EqualWeightAll()),
        "Equal-weight universe": ("ew", hpr, EqualWeightAll()),
        "12-1 Momentum (top decile)": ("mom", hpr, TopFractionEqualWeight(0.10)),
        "Value (cheapest decile)": ("val", hpr, TopFractionEqualWeight(0.10)),
    }
    # build per-strategy signal frames
    sig_frames = {
        "idx": pd.DataFrame({COL_DATE: dev_dates[:-1], COL_TICKER: "IWM", "sig": 1.0}),
        "ew": dev_panel[[COL_DATE, COL_TICKER]].assign(sig=1.0),
        "mom": mom_scored[[COL_DATE, COL_TICKER]].assign(sig=mom_scored[SIGNAL].values),
        "val": val_scored[[COL_DATE, COL_TICKER]].assign(sig=val_scored["earnings_yield"].values),
    }

    perf = {}  # strategy -> cost -> stats
    for name, (key, hold, policy) in strategies.items():
        perf[name] = {}
        for c in COSTS:
            res = bt(sig_frames[key], "sig", hold, policy, c)
            perf[name][f"{c}"] = stats_to_dict(performance_stats(
                res.net_returns, 12, turnover=res.turnover, gross_returns=res.gross_returns))

    # diagnostic ICs (dev) for the two active baselines
    ic = {}
    for tgt in TARGETS:
        ic[f"momentum|{tgt}"] = stats_to_dict_ic(information_coefficient(mom_scored, SIGNAL, tgt)[1])
        ic[f"value_earnings_yield|{tgt}"] = stats_to_dict_ic(information_coefficient(val_scored, "earnings_yield", tgt)[1])

    coverage = {fam.name: {f: float(feats[fam.name][f].notna().mean()) for f in fam.feature_names[:1]}
                for fam, _ in fam_specs}  # quick presence check; full per-feature in Step 3
    fcounts = {fam.name: len(fam.feature_names) for fam, _ in fam_specs}

    out = {"panel": pmeta, "feature_counts": fcounts, "costs": COSTS,
           "dev_window": [str(dev_dates.min().date()), str(dev_dates.max().date()), int(len(dev_dates))],
           "perf": perf, "diagnostic_ic": ic}
    (cache.root / "results" / "phase5_step2.json").write_text(json.dumps(out, indent=2, default=float))
    _write_report(REPO / "reports" / "phase5_smallcap_baselines.md", out)
    print("\nDEV baselines net Sharpe @50bps:",
          {n: round(perf[n]["50.0"]["sharpe"], 2) for n in perf})
    print("momentum/value dev IC:", {k: round(v["mean_ic"], 4) for k, v in ic.items()})
    print("Wrote reports/phase5_smallcap_baselines.md (hold-out sealed).")


def stats_to_dict_ic(summ):
    return {"mean_ic": summ.mean_ic, "ic_ir": summ.ic_ir, "t_stat": summ.t_stat,
            "frac_positive": summ.frac_positive, "n_dates": summ.n_dates}


def _f(x, pct=False, nd=4):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{x*100:+.1f}%" if pct else f"{x:.{nd}f}"


def _write_report(path, o):
    L = ["# Phase 5 (dev) — small/mid-cap panel, features & baselines\n"]
    L.append("> **Development only (≤ 2021-12); 2022+ sealed.** Costs per D18 sweep {25,30,50,100} bps; "
             "**verdict bar = survive ≥ 50 bps.** Delisting-aware labels + holding returns (mid-window "
             "bankruptcies earn their real loss, never NaN-dropped).\n")
    L.append(f"*Panel:* {o['panel']['rows']:,} rows, {o['panel']['names']} names · *dev window* "
             f"{o['dev_window'][0]}→{o['dev_window'][1]} ({o['dev_window'][2]} rebalances). "
             f"*Feature families:* " + ", ".join(f"{k}({v})" for k, v in o['feature_counts'].items()) + ".\n")

    L.append("## Baselines — net CAGR by cost (dev), with Sharpe @50 bps\n")
    L.append("| Strategy | 25 bps | 30 bps | **50 bps** | 100 bps | Sharpe @50 | MaxDD @50 |")
    L.append("|---|---|---|---|---|---|---|")
    for name, byc in o["perf"].items():
        L.append(f"| {name} | {_f(byc['25.0']['cagr'],pct=True)} | {_f(byc['30.0']['cagr'],pct=True)} | "
                 f"**{_f(byc['50.0']['cagr'],pct=True)}** | {_f(byc['100.0']['cagr'],pct=True)} | "
                 f"{_f(byc['50.0']['sharpe'],nd=2)} | {_f(byc['50.0']['max_drawdown'],pct=True)} |")
    L.append("\n*Equal-weight & IWM are low-turnover (cost-insensitive); momentum & value are the "
             "cost-sensitive active baselines — watch whether they survive the 50 bps bar.*\n")

    L.append("## Diagnostic ICs (dev, secondary) — active baselines\n")
    L.append("| Signal × target | Mean IC | IC-IR | t-stat | % pos |")
    L.append("|---|---|---|---|---|")
    for k, v in o["diagnostic_ic"].items():
        L.append(f"| {k} | {_f(v['mean_ic'])} | {_f(v['ic_ir'],nd=2)} | {_f(v['t_stat'],nd=2)} | "
                 f"{_f(v['frac_positive'],pct=True)} |")
    L.append("\n> Diagnostic only (D9). The pre-registered model run (Step 3, dev-only) is next; the "
             "2022+ hold-out stays sealed until the Step-4 gate.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
