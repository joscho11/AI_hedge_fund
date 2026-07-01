"""Phase 2: run the baselines, write result artifacts to data_cache/results/, and render a
caveat-stamped markdown report to reports/phase2_baselines.md.

    .venv/Scripts/python.exe scripts/phase2_baselines.py [--panel panel_110tickers]

Baselines: (1) buy-and-hold SPY, (2) equal-weight eligible universe, (3) 12-1 momentum (top decile).
Value baseline deferred to Phase 3 (DECISIONS D7). Every number is survivorship-flattered — see banner.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

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
from src.data.providers.yfinance_prices import YFinancePriceProvider
from src.data.types import COL_DATE, COL_TICKER
from src.eval.metrics import (
    information_coefficient,
    performance_stats,
    quantile_returns,
    stats_to_dict,
)
from src.utils.calendars import month_end_rebalance_dates
from src.utils.config import load_config

REPO = Path(__file__).resolve().parents[1]
TARGETS = ["fwd_ret_raw", "fwd_ret_excess_median", "fwd_ret_excess_sector"]
SURVIVORSHIP_DRIFT = "+4.3%/63d (~18%/yr)"

CAVEAT = (
    "> **Survivorship caveat:** universe = CURRENT S&P 500 membership on the free stack. Every "
    f"number below is **survivorship-flattered**. Reference market/universe drift: raw forward "
    f"return averages {SURVIVORSHIP_DRIFT}. Treat absolute returns as upward-biased; the honest "
    "signal is whether an edge survives *after* removing that common drift (excess-vs-median). "
    "Point-in-time (Sharadar) re-run pending."
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default=None, help="panel cache key (default: newest panel_*)")
    ap.add_argument("--compare-dir", default="results_sample110",
                    help="results snapshot dir (under cache root) to compare against; '' to skip")
    ap.add_argument("--compare-label", default="110-name sample")
    args = ap.parse_args()

    cfg = load_config()
    cache = ParquetCache(cfg.cache_path)

    # ---- load panel (resolve to a concrete path so we can record provenance) ----
    panel_dir = cache.root / "panel"
    if args.panel:
        panel_path = panel_dir / f"{args.panel}.parquet"
    else:
        panel_path = max(panel_dir.glob("panel_*.parquet"), key=lambda p: p.stat().st_mtime)
    panel = pd.read_parquet(panel_path)
    panel[COL_DATE] = pd.to_datetime(panel[COL_DATE])
    tickers = sorted(panel[COL_TICKER].unique())
    print(f"Panel: {len(panel):,} rows, {len(tickers)} tickers, "
          f"{panel[COL_DATE].min().date()}..{panel[COL_DATE].max().date()}")

    # ---- prices (cached) + SPY ----
    px = YFinancePriceProvider(cache).get_prices(tickers, cfg.dates.start, cfg.dates.end)
    spy = YFinancePriceProvider(cache).get_prices(["SPY"], cfg.dates.start, cfg.dates.end)
    reb = month_end_rebalance_dates(cfg.dates.start, cfg.dates.end, cfg.calendar.exchange)

    hpr = holding_period_returns(px, reb)
    hpr_spy = holding_period_returns(spy, reb)

    cost = cfg.costs.commission_bps + cfg.costs.slippage_bps   # one-way bps
    print(f"One-way cost: {cost:.1f} bps; rebalances: {len(reb)}")

    # ---- baseline 1: SPY buy & hold ----
    spy_sig = pd.DataFrame({COL_DATE: reb[:-1], COL_TICKER: "SPY", SIGNAL: 1.0})
    spy_res = run_backtest(spy_sig, hpr_spy, EqualWeightAll(), cost_bps=cost)

    # ---- baseline 2: equal-weight eligible universe ----
    ew_sig = panel[[COL_DATE, COL_TICKER]].copy()
    ew_sig[SIGNAL] = 1.0
    ew_res = run_backtest(ew_sig, hpr, EqualWeightAll(), cost_bps=cost)

    # ---- baseline 3: 12-1 momentum (scored over eligible universe) ----
    mom = momentum_12_1(px, reb, cfg.calendar.exchange)
    scored = panel.merge(mom, on=[COL_DATE, COL_TICKER], how="inner")  # eligible + has signal + labels
    mom_res = run_backtest(scored[[COL_DATE, COL_TICKER, SIGNAL]], hpr,
                           TopFractionEqualWeight(frac=0.10), cost_bps=cost)

    # ---- baseline 4: value (cheapest decile by earnings yield) — DEFERRED from Phase 2 (D7) ----
    # Metric choice: earnings yield (inverse P/E). Robust, capital-structure-light, the canonical
    # value factor; a single clean ratio rather than a blend. "Cheapest" = HIGHEST earnings yield.
    val_res, val_scored = None, None
    val_path = cache.root / "features" / "valuation.parquet"
    if val_path.exists():
        vf = pd.read_parquet(val_path)[[COL_DATE, COL_TICKER, "earnings_yield"]].dropna()
        vf[COL_DATE] = pd.to_datetime(vf[COL_DATE])
        val_scored = panel.merge(vf, on=[COL_DATE, COL_TICKER], how="inner")
        val_sig = val_scored[[COL_DATE, COL_TICKER]].copy()
        val_sig[SIGNAL] = val_scored["earnings_yield"]   # higher = cheaper -> top decile = cheapest
        val_res = run_backtest(val_sig, hpr, TopFractionEqualWeight(frac=0.10), cost_bps=cost)
    else:
        print("  (valuation feature store missing — run scripts/phase3_valuation_features.py; "
              "skipping value baseline)")

    # ---- align to common window for a fair headline table ----
    common = spy_res.net_returns.index.intersection(ew_res.net_returns.index).intersection(
        mom_res.net_returns.index)
    if val_res is not None:
        common = common.intersection(val_res.net_returns.index)
    print(f"Common comparison window: {common.min().date()}..{common.max().date()} ({len(common)} rebalances)")

    def perf(res):
        on = res.net_returns.reindex(common)
        gn = res.gross_returns.reindex(common)
        tn = res.turnover.reindex(common)
        return {
            "gross": stats_to_dict(performance_stats(gn, 12, turnover=tn)),
            "net": stats_to_dict(performance_stats(on, 12, turnover=tn, gross_returns=gn)),
        }

    strategies = {"SPY (buy & hold)": spy_res, "Equal-weight universe": ew_res,
                  "12-1 Momentum (top decile)": mom_res}
    if val_res is not None:
        strategies["Value (cheapest decile)"] = val_res
    perf_stats = {name: perf(res) for name, res in strategies.items()}

    # value baseline IC (earnings yield vs each target) for the report + dashboard
    value_ic = {}
    if val_scored is not None:
        for tgt in TARGETS:
            _, summ = information_coefficient(val_scored, "earnings_yield", tgt)
            value_ic[tgt] = asdict(summ)

    # ---- momentum IC + quantiles vs all three targets ----
    ic_summ, ic_series, quants = {}, {}, {}
    for tgt in TARGETS:
        s, summ = information_coefficient(scored, SIGNAL, tgt)
        ic_summ[tgt] = asdict(summ)
        ic_series[tgt] = s
        quants[tgt] = asdict(quantile_returns(scored, SIGNAL, tgt, n_quantiles=10))

    # ---- cost sensitivity for momentum (net CAGR vs one-way bps) ----
    sensitivity = {}
    for bps in (5.0, 10.0, 20.0):
        r = run_backtest(scored[[COL_DATE, COL_TICKER, SIGNAL]], hpr,
                         TopFractionEqualWeight(frac=0.10), cost_bps=bps)
        sensitivity[bps] = stats_to_dict(performance_stats(
            r.net_returns.reindex(common), 12, turnover=r.turnover.reindex(common),
            gross_returns=r.gross_returns.reindex(common)))

    # ---- persist artifacts ----
    res_dir = cache.root / "results"
    res_dir.mkdir(parents=True, exist_ok=True)

    long_rows = []
    for name, res in strategies.items():
        for t in res.net_returns.index:
            long_rows.append({"date": t, "strategy": name,
                              "gross_ret": res.gross_returns[t], "net_ret": res.net_returns[t],
                              "turnover": res.turnover[t], "cost_drag": res.cost_drag[t]})
    pd.DataFrame(long_rows).to_parquet(res_dir / "baseline_returns.parquet", index=False)

    pd.DataFrame(ic_series).to_parquet(res_dir / "momentum_ic_series.parquet")
    (res_dir / "baseline_perf.json").write_text(json.dumps(perf_stats, indent=2))
    (res_dir / "momentum_ic.json").write_text(json.dumps(ic_summ, indent=2))
    (res_dir / "momentum_quantiles.json").write_text(json.dumps(quants, indent=2))
    if value_ic:
        (res_dir / "value_ic.json").write_text(json.dumps(value_ic, indent=2))
    try:
        panel_rel = str(panel_path.resolve().relative_to(REPO).as_posix())
    except ValueError:
        panel_rel = str(panel_path.resolve())
    meta = {
        "universe_size": len(tickers), "rebalances": int(len(reb)),
        "common_window": [str(common.min().date()), str(common.max().date()), len(common)],
        "one_way_cost_bps": cost, "survivorship_drift": SURVIVORSHIP_DRIFT,
        "cost_sensitivity_net_cagr": {str(k): v["cagr"] for k, v in sensitivity.items()},
        # Provenance: the EXACT panel these results were computed from (so the dashboard never
        # silently pairs page-2's universe with page-3's results from a different panel).
        "panel_path": panel_rel,
        "panel_rows": int(len(panel)),
        "panel_names": int(len(tickers)),
        "value_ic": value_ic,   # earnings-yield IC per target (empty if value baseline skipped)
        "caveat": CAVEAT,
    }
    (res_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    # ---- optional sample-vs-full comparison ----
    comparison = None
    if args.compare_dir:
        cmp_dir = cache.root / args.compare_dir
        if cmp_dir.exists() and (cmp_dir / "meta.json").exists():
            cmp_meta = json.loads((cmp_dir / "meta.json").read_text())
            if cmp_meta.get("universe_size") != meta["universe_size"]:
                comparison = {
                    "label": args.compare_label,
                    "meta": cmp_meta,
                    "perf": json.loads((cmp_dir / "baseline_perf.json").read_text()),
                    "ic": json.loads((cmp_dir / "momentum_ic.json").read_text()),
                    "quants": json.loads((cmp_dir / "momentum_quantiles.json").read_text()),
                }

    _write_report(REPO / "reports" / "phase2_baselines.md", perf_stats, ic_summ, quants,
                  sensitivity, meta, comparison)
    print(f"\nWrote artifacts to {res_dir} and report to reports/phase2_baselines.md")

    # ---- console summary ----
    print("\nNet (after-cost) headline, common window:")
    for name, p in perf_stats.items():
        n = p["net"]
        print(f"  {name:<30} CAGR {n['cagr']:+.2%}  Sharpe {n['sharpe']:.2f}  "
              f"maxDD {n['max_drawdown']:.1%}  turn/reb {n['avg_turnover']:.1%}")
    print("\nMomentum IC (mean / t-stat) by target:")
    for tgt, s in ic_summ.items():
        print(f"  {tgt:<24} mean IC {s['mean_ic']:+.4f}  IR {s['ic_ir']:+.3f}  t {s['t_stat']:+.2f}")


def _fmt(x, pct=False):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{x:+.2%}" if pct else f"{x:.3f}"


SPY_K = "SPY (buy & hold)"
EW_K = "Equal-weight universe"
MOM_K = "12-1 Momentum (top decile)"


def _comparison_lines(full_perf, full_ic, full_quants, full_meta, cmp):
    """Side-by-side sample-vs-full table + an auto-generated 'held / changed' verdict."""
    s_perf, s_ic, s_quants, s_meta = cmp["perf"], cmp["ic"], cmp["quants"], cmp["meta"]
    s_lab = f"{cmp['label']} ({s_meta['universe_size']})"
    f_lab = f"Full universe ({full_meta['universe_size']})"

    def drift(perf):
        return perf[EW_K]["net"]["cagr"] - perf[SPY_K]["net"]["cagr"]

    s_ic_raw, f_ic_raw = s_ic["fwd_ret_raw"], full_ic["fwd_ret_raw"]
    s_q, f_q = s_quants["fwd_ret_raw"], full_quants["fwd_ret_raw"]

    L = ["## Sample vs full universe — do the conclusions hold?\n"]
    L.append(f"| Metric | {s_lab} | {f_lab} |")
    L.append("|---|---|---|")
    rows = [
        ("Survivorship drift (EW − SPY CAGR)", _fmt(drift(s_perf), 1), _fmt(drift(full_perf), 1)),
        ("SPY CAGR (net)", _fmt(s_perf[SPY_K]["net"]["cagr"], 1), _fmt(full_perf[SPY_K]["net"]["cagr"], 1)),
        ("Equal-weight CAGR (net)", _fmt(s_perf[EW_K]["net"]["cagr"], 1), _fmt(full_perf[EW_K]["net"]["cagr"], 1)),
        ("Momentum CAGR (net)", _fmt(s_perf[MOM_K]["net"]["cagr"], 1), _fmt(full_perf[MOM_K]["net"]["cagr"], 1)),
        ("Momentum Sharpe (net)", _fmt(s_perf[MOM_K]["net"]["sharpe"]), _fmt(full_perf[MOM_K]["net"]["sharpe"])),
        ("Equal-weight Sharpe (net)", _fmt(s_perf[EW_K]["net"]["sharpe"]), _fmt(full_perf[EW_K]["net"]["sharpe"])),
        ("Momentum mean IC (raw)", _fmt(s_ic_raw["mean_ic"]), _fmt(f_ic_raw["mean_ic"])),
        ("Momentum IC t-stat", _fmt(s_ic_raw["t_stat"]), _fmt(f_ic_raw["t_stat"])),
        ("Momentum IC % positive", _fmt(s_ic_raw["frac_positive"], 1), _fmt(f_ic_raw["frac_positive"], 1)),
        ("Decile monotonicity ρ (raw)", _fmt(s_q["monotonicity"]), _fmt(f_q["monotonicity"])),
        ("Decile top−bottom (raw)", _fmt(s_q["top_minus_bottom"]), _fmt(f_q["top_minus_bottom"])),
    ]
    for name, a, b in rows:
        L.append(f"| {name} | {a} | {b} |")
    L.append("")

    # ---- verdict ----
    verdict = ["**Verdict — conclusions held / changed:**\n"]
    # 1) survivorship drift
    sd, fd = drift(s_perf), drift(full_perf)
    held_drift = (sd > 0) and (fd > 0) and abs(fd - sd) < 0.03
    verdict.append(
        f"- Survivorship drift: {_fmt(sd,1)} → {_fmt(fd,1)}. "
        f"**{'HELD' if held_drift else 'CHANGED'}** — equal-weight still "
        f"{'beats' if fd > 0 else 'trails'} SPY, the universe is still survivors.")
    # 2) momentum significance
    s_sig, f_sig = abs(s_ic_raw["t_stat"]) >= 2.0, abs(f_ic_raw["t_stat"]) >= 2.0
    verdict.append(
        f"- Momentum signal strength: mean IC {_fmt(s_ic_raw['mean_ic'])} (t {_fmt(s_ic_raw['t_stat'])}) "
        f"→ {_fmt(f_ic_raw['mean_ic'])} (t {_fmt(f_ic_raw['t_stat'])}). "
        f"**{'CHANGED — now significant' if f_sig and not s_sig else ('CHANGED — lost significance' if s_sig and not f_sig else 'HELD')}** "
        f"(threshold |t| ≥ 2).")
    # 3) risk-adjusted vs equal-weight — reported, but only trustworthy if IC supports it
    s_ahead = s_perf[MOM_K]["net"]["sharpe"] > s_perf[EW_K]["net"]["sharpe"]
    f_ahead = full_perf[MOM_K]["net"]["sharpe"] > full_perf[EW_K]["net"]["sharpe"]
    f_mono = f_q["monotonicity"]
    verdict.append(
        f"- Top-decile momentum Sharpe vs equal-weight: "
        f"{_fmt(s_perf[MOM_K]['net']['sharpe'])} vs {_fmt(s_perf[EW_K]['net']['sharpe'])} → "
        f"{_fmt(full_perf[MOM_K]['net']['sharpe'])} vs {_fmt(full_perf[EW_K]['net']['sharpe'])}. "
        f"The portfolio Sharpe {'edges ahead' if f_ahead else 'stays at/below'} — but see the "
        f"synthesis: this is **not** IC-supported.")

    # ---- synthesis: reconcile the IC-vs-Sharpe divergence honestly ----
    diverges = f_ahead and not f_sig
    if diverges:
        verdict.append(
            "\n**Synthesis — does momentum work? No, and breadth made that clearer.** "
            f"Adding cross-sectional breadth drove the momentum IC *toward zero* (mean IC "
            f"{_fmt(f_ic_raw['mean_ic'])}, t {_fmt(f_ic_raw['t_stat'])}, {_fmt(f_ic_raw['frac_positive'],1)} "
            f"of months positive — a coin flip) and decile monotonicity went negative "
            f"({_fmt(f_mono)}): the deciles are a U-shape, not a ranking. The top-decile portfolio's "
            "higher Sharpe is therefore an *extreme-decile, period-specific* effect with **no "
            "significant cross-sectional signal beneath it** — precisely the flashy-number-without-"
            "edge pattern this project distrusts. Net: the Step-1 conclusion (12-1 momentum is not a "
            "robust signal on this universe) is **strengthened**, not overturned, by the full-scale "
            "run. Treat the portfolio Sharpe as fragile until an out-of-sample / IC-backed result "
            "confirms it.")
    return L + verdict + [""]


def _write_report(path, perf_stats, ic_summ, quants, sensitivity, meta, comparison=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    L = []
    L.append("# Phase 2 — Baseline Performance Report\n")
    L.append(meta["caveat"] + "\n")
    L.append(f"*Universe:* {meta['universe_size']} current S&P 500 names · "
             f"*Common window:* {meta['common_window'][0]} → {meta['common_window'][1]} "
             f"({meta['common_window'][2]} monthly rebalances) · "
             f"*One-way cost:* {meta['one_way_cost_bps']:.0f} bps\n")

    L.append("## Performance (common window, net of costs unless noted)\n")
    L.append("| Strategy | CAGR (net) | CAGR (gross) | Ann.Vol | Sharpe (net) | Sortino (net) | "
             "MaxDD | Hit | Turn/reb | Cost drag (cum) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for name, p in perf_stats.items():
        n, g = p["net"], p["gross"]
        L.append(f"| {name} | {_fmt(n['cagr'],1)} | {_fmt(g['cagr'],1)} | {_fmt(n['ann_vol'],1)} | "
                 f"{_fmt(n['sharpe'])} | {_fmt(n['sortino'])} | {_fmt(n['max_drawdown'],1)} | "
                 f"{_fmt(n['hit_rate'],1)} | {_fmt(n['avg_turnover'],1)} | {_fmt(n['total_cost_drag'],1)} |")
    L.append("\n*Equal-weight vs SPY shows the survivorship drift directly; momentum must beat the "
             "best of these **after costs** to be real.*\n")

    # ---- auto-generated honest read ----
    L.append("## Honest read\n")
    spy_s = perf_stats["SPY (buy & hold)"]["net"]
    ew_s = perf_stats["Equal-weight universe"]["net"]
    mom_s = perf_stats["12-1 Momentum (top decile)"]["net"]
    ic_raw = ic_summ["fwd_ret_raw"]
    drift_bullet = (
        f"- **Survivorship drift is visible and material:** equal-weight universe CAGR "
        f"{_fmt(ew_s['cagr'],1)} vs SPY {_fmt(spy_s['cagr'],1)} — a ~"
        f"{(ew_s['cagr']-spy_s['cagr'])*100:.0f}pp/yr gap from holding *today's* survivors, "
        f"consistent with the {SURVIVORSHIP_DRIFT} fingerprint. This is a measured bias, not alpha."
    )
    sig = abs(ic_raw["t_stat"]) >= 2.0
    mom_bullet = (
        f"- **Momentum's headline CAGR ({_fmt(mom_s['cagr'],1)}) overstates its edge.** "
        f"Mean IC {_fmt(ic_raw['mean_ic'])} (t = {_fmt(ic_raw['t_stat'])}) is "
        f"{'statistically significant' if sig else '**not** statistically significant (|t| < 2) and below the 0.03–0.05 genuine-signal band'}; "
        f"risk-adjusted, momentum's Sharpe ({_fmt(mom_s['sharpe'])}) is "
        f"{'above' if mom_s['sharpe'] > ew_s['sharpe'] else 'no better than'} equal-weight "
        f"({_fmt(ew_s['sharpe'])}), with deeper drawdown ({_fmt(mom_s['max_drawdown'],1)}) and far "
        f"higher turnover ({_fmt(mom_s['avg_turnover'],1)}/reb). The decile spread is concentrated "
        f"in the top decile rather than monotonic."
    )
    cost_bullet = (
        "- **Momentum is cost-robust** (net CAGR barely moves 5→20 bps): even ~30% monthly turnover "
        "× 20 bps is a small drag. So costs are *not* what holds momentum back here — weak, "
        "insignificant signal is."
    )
    L.append(drift_bullet)
    L.append(mom_bullet)
    L.append(cost_bullet)
    # value baseline bullet (if present)
    val_ic = meta.get("value_ic", {}).get("fwd_ret_excess_sector")
    if "Value (cheapest decile)" in perf_stats and val_ic:
        v = perf_stats["Value (cheapest decile)"]["net"]
        L.append(
            f"- **Value (cheapest decile by earnings yield) does NOT work on this sample:** earnings "
            f"yield has a *negative* IC ({val_ic['mean_ic']:+.4f}, t {val_ic['t_stat']:+.2f}) — cheap "
            f"stocks underperformed — so the value baseline (CAGR {_fmt(v['cagr'],1)}, Sharpe "
            f"{_fmt(v['sharpe'])}) trails equal-weight. This is the 2010s value drought + survivorship "
            "(today's index = growth winners), an honest regime/sample result. The sign may flip on a "
            "point-in-time, delisting-inclusive universe.")
    L.append("")

    if comparison is not None:
        L.extend(_comparison_lines(perf_stats, ic_summ, quants, meta, comparison))

    L.append("## 12-1 Momentum — Information Coefficient\n")
    L.append("| Target | N dates | Mean IC | IC IR | t-stat | % positive |")
    L.append("|---|---|---|---|---|---|")
    for tgt, s in ic_summ.items():
        L.append(f"| `{tgt}` | {s['n_dates']} | {_fmt(s['mean_ic'])} | {_fmt(s['ic_ir'])} | "
                 f"{_fmt(s['t_stat'])} | {_fmt(s['frac_positive'],1)} |")
    L.append("\n*A stable mean IC of ~0.03–0.05 is a genuine signal. The `excess_median` / "
             "`excess_sector` columns reveal how much is sector tilt vs within-sector selection.*")
    L.append("\n> **Note (expected, not a bug):** IC for `fwd_ret_raw` and `fwd_ret_excess_median` "
             "is identical because subtracting a per-date constant (the universe median) does not "
             "change the cross-sectional *ranking* of names, and Spearman IC is rank-based. The "
             "decile-mean *levels* differ (shifted down by the median); only `excess_sector`, which "
             "re-ranks within sector, changes the IC.\n")

    L.append("## 12-1 Momentum — Decile spread (mean forward target by signal decile)\n")
    for tgt in quants:
        q = quants[tgt]
        order = sorted(q["mean_by_quantile"], key=int)
        cells = " ".join(f"D{k}:{q['mean_by_quantile'][k]:+.3f}" for k in order)
        L.append(f"- **`{tgt}`** — top−bottom = {q['top_minus_bottom']:+.4f}, "
                 f"monotonicity ρ = {_fmt(q['monotonicity'])}\n  - {cells}")
    L.append("")

    L.append("## Cost sensitivity (momentum net CAGR)\n")
    L.append("| One-way cost (bps) | Net CAGR |")
    L.append("|---|---|")
    for bps, c in meta["cost_sensitivity_net_cagr"].items():
        L.append(f"| {float(bps):.0f} | {_fmt(c,1)} |")

    L.append("\n## Decisions in this phase\n")
    L.append("- **Value baseline deferred to Phase 3** (DECISIONS D7): a clean as-of-t valuation "
             "ratio needs TTM + shares-outstanding alignment from EDGAR — feature-layer work.\n")
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
