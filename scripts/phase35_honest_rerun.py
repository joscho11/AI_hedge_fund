"""Phase 3.5 Steps 2-3: rebuild the labeled panel on the HONEST (point-in-time, delisting-inclusive)
universe with delisting-aware labels, re-run the baselines + momentum/valuation feature ICs on it,
and write the honest-vs-flattered comparison. Honest results become the dashboard default; the
flattered results (snapshotted to data_cache/results_flattered/) remain as the 'before'.

    .venv/Scripts/python.exe scripts/phase35_honest_rerun.py
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import pyarrow.dataset as pa_ds

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import (
    SIGNAL,
    EqualWeightAll,
    TopFractionEqualWeight,
    holding_period_returns,
    run_backtest,
)
from src.baselines.signals import momentum_12_1
from src.data.cache import ParquetCache
from src.data.providers.sharadar import SharadarProvider
from src.data.providers.yfinance_prices import YFinancePriceProvider
from src.data.types import COL_DATE, COL_TICKER
from src.eval.metrics import (
    information_coefficient,
    performance_stats,
    quantile_returns,
    stats_to_dict,
)
from src.features.momentum import MomentumFamily
from src.features.valuation import ValuationFamily
from src.labels.honest_panel import (
    build_honest_panel,
    honest_holding_period_returns,
    sep_price_frame,
)
from src.universe.honest_sp500 import liquidated_tickers, members_on, membership_intervals
from src.utils.calendars import month_end_rebalance_dates
from src.utils.config import load_config

REPO = Path(__file__).resolve().parents[1]
TARGETS = ["fwd_ret_raw", "fwd_ret_excess_median", "fwd_ret_excess_sector"]
SPY_K, EW_K, MOM_K, VAL_K = ("SPY (buy & hold)", "Equal-weight universe",
                             "12-1 Momentum (top decile)", "Value (cheapest decile)")


def _load_sep(cache: ParquetCache, tickers: list[str]) -> pd.DataFrame:
    path = cache.root / "sharadar" / "SEP.parquet"
    dset = pa_ds.dataset(str(path), format="parquet")
    tbl = dset.to_table(columns=["ticker", "date", "closeunadj", "closeadj", "volume"],
                        filter=pa_ds.field("ticker").isin(tickers))
    return tbl.to_pandas()


def main():
    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)
    prov = SharadarProvider(cache)
    sp500 = cache.get("sharadar", "SP500")
    tickers_df = cache.get("sharadar", "TICKERS")
    actions = cache.get("sharadar", "ACTIONS")
    reb = month_end_rebalance_dates(cfg.dates.start, cfg.dates.end, cfg.calendar.exchange)

    # honest member tickers across the window
    intervals = membership_intervals(sp500)
    member_tickers = sorted({tk for t in reb for tk in members_on(intervals, t)})
    print(f"Honest member tickers across window: {len(member_tickers)}")

    sep = _load_sep(cache, member_tickers)
    prices = sep_price_frame(sep)
    print(f"SEP rows (honest tickers): {len(prices):,}")
    liquidation = liquidated_tickers(actions)
    sector_map = (tickers_df.drop_duplicates("ticker", keep="last")
                  .set_index("ticker")["sector"].to_dict())

    panel = build_honest_panel(
        prices, sp500, sector_map, liquidation, reb,
        horizon_days=cfg.label.horizon_days, min_price=cfg.universe.min_price,
        min_dollar_volume=cfg.universe.min_dollar_volume, exchange=cfg.calendar.exchange)
    panel_path = cache.put("panel", "panel_honest", panel)
    print(f"Honest panel: {len(panel):,} rows, {panel[COL_TICKER].nunique()} names, "
          f"{panel[COL_DATE].min().date()}..{panel[COL_DATE].max().date()} -> {panel_path}")

    cost = cfg.costs.commission_bps + cfg.costs.slippage_bps
    hpr = honest_holding_period_returns(prices, reb, liquidation)        # delisting-aware
    spy = YFinancePriceProvider(cache).get_prices(["SPY"], cfg.dates.start, cfg.dates.end)
    hpr_spy = holding_period_returns(spy, reb)

    # ---- baselines on the honest universe ----
    spy_sig = pd.DataFrame({COL_DATE: reb[:-1], COL_TICKER: "SPY", SIGNAL: 1.0})
    spy_res = run_backtest(spy_sig, hpr_spy, EqualWeightAll(), cost_bps=cost)
    ew_sig = panel[[COL_DATE, COL_TICKER]].assign(**{SIGNAL: 1.0})
    ew_res = run_backtest(ew_sig, hpr, EqualWeightAll(), cost_bps=cost)
    mom = momentum_12_1(prices, reb, cfg.calendar.exchange)
    scored = panel.merge(mom, on=[COL_DATE, COL_TICKER], how="inner")
    mom_res = run_backtest(scored[[COL_DATE, COL_TICKER, SIGNAL]], hpr,
                           TopFractionEqualWeight(0.10), cost_bps=cost)

    val_fam = ValuationFamily()
    val_feats = val_fam.build(panel, reb, providers={"fundamentals": prov},
                              exchange=cfg.calendar.exchange)
    val_scored = panel.merge(val_feats[[COL_DATE, COL_TICKER, "earnings_yield"]].dropna(),
                             on=[COL_DATE, COL_TICKER], how="inner")
    val_sig = val_scored[[COL_DATE, COL_TICKER]].assign(**{SIGNAL: val_scored["earnings_yield"]})
    val_res = run_backtest(val_sig, hpr, TopFractionEqualWeight(0.10), cost_bps=cost)

    strategies = {SPY_K: spy_res, EW_K: ew_res, MOM_K: mom_res, VAL_K: val_res}
    common = spy_res.net_returns.index
    for r in (ew_res, mom_res, val_res):
        common = common.intersection(r.net_returns.index)
    print(f"Common window: {common.min().date()}..{common.max().date()} ({len(common)} rebalances)")

    def perf(res):
        on, gn, tn = (res.net_returns.reindex(common), res.gross_returns.reindex(common),
                      res.turnover.reindex(common))
        return {"gross": stats_to_dict(performance_stats(gn, 12, turnover=tn)),
                "net": stats_to_dict(performance_stats(on, 12, turnover=tn, gross_returns=gn))}
    perf_stats = {k: perf(v) for k, v in strategies.items()}

    # ---- ICs / quantiles ----
    ic_summ, ic_series, quants = {}, {}, {}
    for tgt in TARGETS:
        s, summ = information_coefficient(scored, SIGNAL, tgt)
        ic_summ[tgt] = asdict(summ); ic_series[tgt] = s
        quants[tgt] = asdict(quantile_returns(scored, SIGNAL, tgt, 10))
    value_ic = {tgt: asdict(information_coefficient(val_scored, "earnings_yield", tgt)[1])
                for tgt in TARGETS}

    # ---- feature-family ICs on the honest panel ----
    mom_fam = MomentumFamily()
    mom_feats = mom_fam.build(panel, reb, providers={"prices": prices}, exchange=cfg.calendar.exchange)
    mom_quality = mom_fam.quality_report(mom_feats, panel, TARGETS)
    val_quality = val_fam.quality_report(val_feats, panel, TARGETS)
    fh = cache.root / "features_honest"; fh.mkdir(parents=True, exist_ok=True)
    (fh / "momentum_quality.json").write_text(json.dumps(mom_quality, indent=2))
    (fh / "valuation_quality.json").write_text(json.dumps(val_quality, indent=2))

    # ---- write honest results (becomes the dashboard default) ----
    res_dir = cache.root / "results"
    long_rows = [{"date": t, "strategy": k, "gross_ret": v.gross_returns[t],
                  "net_ret": v.net_returns[t], "turnover": v.turnover[t], "cost_drag": v.cost_drag[t]}
                 for k, v in strategies.items() for t in v.net_returns.index]
    pd.DataFrame(long_rows).to_parquet(res_dir / "baseline_returns.parquet", index=False)
    pd.DataFrame(ic_series).to_parquet(res_dir / "momentum_ic_series.parquet")
    (res_dir / "baseline_perf.json").write_text(json.dumps(perf_stats, indent=2))
    (res_dir / "momentum_ic.json").write_text(json.dumps(ic_summ, indent=2))
    (res_dir / "momentum_quantiles.json").write_text(json.dumps(quants, indent=2))
    (res_dir / "value_ic.json").write_text(json.dumps(value_ic, indent=2))
    meta = {
        "universe_size": int(panel[COL_TICKER].nunique()), "rebalances": int(len(reb)),
        "common_window": [str(common.min().date()), str(common.max().date()), len(common)],
        "one_way_cost_bps": cost, "universe_kind": "honest (point-in-time, delisting-inclusive)",
        "panel_path": panel_path.resolve().relative_to(REPO).as_posix(),
        "panel_rows": int(len(panel)), "panel_names": int(panel[COL_TICKER].nunique()),
        "value_ic": value_ic,
        "caveat": ("> **Backtested research, not investment advice.** Survivorship is now ADDRESSED "
                   "(point-in-time membership + delisted names included). Remaining caveats: results "
                   "are in-sample (no out-of-sample/Phase-4 validation yet), use current-classification "
                   "sector/fundamentals limits, and Sharadar's coverage. Past performance ≠ future."),
    }
    (res_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    _write_comparison(REPO / "reports" / "honest_vs_flattered.md",
                      cache.root / "results_flattered", perf_stats, ic_summ, value_ic,
                      mom_quality, val_quality, meta)
    print("\nNet headline (honest), common window:")
    for k, p in perf_stats.items():
        n = p["net"]
        print(f"  {k:<30} CAGR {n['cagr']:+.2%}  Sharpe {n['sharpe']:.2f}  maxDD {n['max_drawdown']:.1%}")
    print("Wrote reports/honest_vs_flattered.md + honest results (default).")


def _g(d, *keys, default=None):
    for k in keys:
        if d is None:
            return default
        d = d.get(k)
    return default if d is None else d


def _pct(x):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x*100:+.1f}%"


def _num(x):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:.3f}"


def _write_comparison(path, flat_dir, h_perf, h_ic, h_value_ic, h_mom_q, h_val_q, meta):
    fperf = json.loads((flat_dir / "baseline_perf.json").read_text())
    fic = json.loads((flat_dir / "momentum_ic.json").read_text())
    fvic = json.loads((flat_dir / "value_ic.json").read_text()) if (flat_dir / "value_ic.json").exists() else {}
    feat = REPO / "data_cache" / "features"
    f_mom_q = json.loads((feat / "momentum_quality.json").read_text()) if (feat / "momentum_quality.json").exists() else {}
    f_val_q = json.loads((feat / "valuation_quality.json").read_text()) if (feat / "valuation_quality.json").exists() else {}
    T = "fwd_ret_excess_sector"

    def drift(perf):
        return perf[EW_K]["net"]["cagr"] - perf[SPY_K]["net"]["cagr"]

    fd, hd = drift(fperf), drift(h_perf)
    L = ["# Honest vs flattered universe — the survivorship-free re-run\n"]
    L.append("> **Backtested research, not advice. In-sample (no Phase-4 OOS yet).** 'Flattered' = "
             "current-membership S&P 500 (survivors only). 'Honest' = point-in-time membership + "
             "delisted names, with delisting-aware labels and holding returns.\n")

    L.append("## Headline: does the survivorship drift collapse?\n")
    L.append(f"Equal-weight − SPY CAGR: **{_pct(fd)} (flattered) → {_pct(hd)} (honest)**. ")
    if abs(hd) < abs(fd) * 0.6:
        L.append(f"The ~{fd*100:.1f}pp/yr 'edge' from holding today's survivors **collapses toward "
                 f"zero** once removed/delisted names are included — confirming it was bias, not skill.\n")
    else:
        L.append("The drift did not collapse as expected — investigate before trusting the rest.\n")

    L.append("## Baselines — flattered → honest (net, common window)\n")
    L.append("| Strategy | CAGR flat → honest | Sharpe flat → honest | MaxDD flat → honest |")
    L.append("|---|---|---|---|")
    for k in (SPY_K, EW_K, MOM_K, VAL_K):
        if k in h_perf and k in fperf:
            fn, hn = fperf[k]["net"], h_perf[k]["net"]
            L.append(f"| {k} | {_pct(fn['cagr'])} → {_pct(hn['cagr'])} | "
                     f"{_num(fn['sharpe'])} → {_num(hn['sharpe'])} | "
                     f"{_pct(fn['max_drawdown'])} → {_pct(hn['max_drawdown'])} |")

    L.append("\n## Do the prior findings survive contact with delisted names?\n")
    # value
    fey, hey = _g(fvic, T, "mean_ic"), _g(h_value_ic, T, "mean_ic")
    fey_t, hey_t = _g(fvic, T, "t_stat"), _g(h_value_ic, T, "t_stat")
    L.append(f"- **Inverted value premium:** earnings-yield IC {_num(fey)} (t {_num(fey_t)}) → "
             f"{_num(hey)} (t {_num(hey_t)}). "
             + ("Sign **flips positive** — value works once cheap delisted names are included.\n"
                if (fey or 0) < 0 <= (hey or 0) else
                ("Stays **negative** — value still didn't pay here, not merely a survivorship artifact.\n"
                 if (hey or 0) < 0 else "Changed; see numbers.\n")))
    # vol
    fv = _g(f_val_q, "features", "earnings_yield")  # placeholder guard
    for feat_name in ("vol_6m", "vol_12m"):
        fvi = _g(f_mom_q, "features", feat_name, "diagnostic_ic", T, "mean_ic")
        fvt = _g(f_mom_q, "features", feat_name, "diagnostic_ic", T, "t_stat")
        hvi = _g(h_mom_q, "features", feat_name, "diagnostic_ic", T, "mean_ic")
        hvt = _g(h_mom_q, "features", feat_name, "diagnostic_ic", T, "t_stat")
        verdict = ("**fades** (|t|<2)" if abs(hvt or 0) < 2 <= abs(fvt or 0)
                   else ("**survives** (|t|>=2)" if abs(hvt or 0) >= 2 else "weak both"))
        L.append(f"- **{feat_name}:** IC {_num(fvi)} (t {_num(fvt)}) → {_num(hvi)} (t {_num(hvt)}) — {verdict}.")
    # momentum
    fm, hm = _g(fic, "fwd_ret_raw", "mean_ic"), _g(h_ic, "fwd_ret_raw", "mean_ic")
    fmt, hmt = _g(fic, "fwd_ret_raw", "t_stat"), _g(h_ic, "fwd_ret_raw", "t_stat")
    L.append(f"- **12-1 momentum (signal):** IC {_num(fm)} (t {_num(fmt)}) → {_num(hm)} (t {_num(hmt)}) — "
             + ("still null.\n" if abs(hmt or 0) < 2 else "now significant — investigate.\n"))

    L.append("\n> **D9 / multiple-comparisons caution:** this is the first out-of-the-survivorship-"
             "bubble read, **still in-sample**. A sign-flip or surviving IC here is a stronger "
             "hypothesis than before, but not yet a tradeable edge — that requires the Phase-4 "
             "purged, embargoed out-of-sample test.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
